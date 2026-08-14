"""Tests de enrutado de modelo por rol en spawn_agent (core.router.model_for +
AgentLoop._spawn_subagent). Valida que el hijo NO herede el modelo del padre, sino
que lo resuelva por role (regresión del bug que motivó este cambio)."""
import tempfile

from core.agent_loop import AgentLoop
from core.models import MODEL_FLASH, MODEL_PRO, ROLE_MODELS
from core.router import model_for
from core.tools.subagent import TOOLS as _SUBAGENT_TOOLS


def test_model_for_known_roles():
    for role, model in ROLE_MODELS.items():
        assert model_for(role) == model


def test_model_for_unknown_role_defaults_to_flash():
    assert model_for("no-existe") == MODEL_FLASH
    assert model_for("") == MODEL_FLASH
    assert model_for(None) == MODEL_FLASH


def test_spawn_agent_schema_exposes_role_enum():
    params = _SUBAGENT_TOOLS["spawn_agent"]["schema"]["parameters"]["properties"]
    assert set(params["role"]["enum"]) == set(ROLE_MODELS)


class _RoleFakeClient:
    """Registra el `model` de cada complete(): 1er turno (padre) delega con un role
    dado, 2do turno (ya el hijo) cierra."""
    def __init__(self, role_arg):
        self.role_arg = role_arg
        self.calls = 0
        self.models_seen = []

    def complete(self, messages, model=None, **kwargs):
        self.models_seen.append(model)
        self.calls += 1
        if self.calls == 1:
            args = f'{{"task": "hacelo", "role": "{self.role_arg}"}}' if self.role_arg \
                else '{"task": "hacelo"}'
            return {"success": True, "content": "", "finish_reason": "tool_calls",
                    "tool_calls": [{"id": "a", "function": {"name": "spawn_agent",
                                                             "arguments": args}}]}
        return {"success": True, "content": "listo", "finish_reason": "stop",
                "tool_calls": None}

    def get_stats(self):
        return {"by_model": {}, "estimated_cost_usd": 0.0}


def test_spawn_agent_defaults_to_flash_even_though_parent_is_pro():
    client = _RoleFakeClient(role_arg=None)
    loop = AgentLoop(client, tempfile.mkdtemp(), model=MODEL_PRO,
                     confirm=lambda d: True, parallel_subagents=False)
    res = loop.run("delegá una parte chica")
    assert res["success"], res
    assert client.models_seen[0] == MODEL_PRO        # padre en PRO
    assert client.models_seen[1] == MODEL_FLASH       # hijo NO hereda: default FLASH


def test_spawn_agent_role_pro_even_though_parent_is_flash():
    client = _RoleFakeClient(role_arg="review")
    loop = AgentLoop(client, tempfile.mkdtemp(), model=MODEL_FLASH,
                     confirm=lambda d: True, parallel_subagents=False)
    res = loop.run("delegá algo que necesita criterio")
    assert res["success"], res
    assert client.models_seen[0] == MODEL_FLASH
    assert client.models_seen[1] == MODEL_PRO         # hijo pide PRO, no hereda FLASH
