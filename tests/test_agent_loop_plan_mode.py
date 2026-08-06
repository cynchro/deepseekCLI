"""Tests de plan mode en core/agent_loop.py: exclusión dinámica de tools por modo,
la tool exit_plan_mode disparando el round-trip de aprobación (ctx.confirm_plan), la
transición "aprobado -> tools de escritura disponibles en el mismo run()", y que la
directiva de modo plan se inyecta solo al modelo (no al evento 'user') y nunca a
sub-agentes."""
import json

from core.agent_loop import AgentLoop


class _FakeClient:
    """Devuelve una secuencia fija de respuestas de complete(); registra qué tools
    (nombres) se ofrecieron en cada llamada."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.tools_per_call = []

    def complete(self, messages, tools=None, **kwargs):
        self.calls += 1
        self.tools_per_call.append({t["function"]["name"] for t in (tools or [])})
        return self._responses.pop(0)

    def get_stats(self):
        return {}


def _final(text="listo"):
    return {"success": True, "content": text, "tool_calls": None, "finish_reason": "stop"}


def _call_exit_plan_mode(plan="1. hacer X\n2. hacer Y"):
    return {
        "success": True, "content": "", "finish_reason": "tool_calls",
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "exit_plan_mode",
                                     "arguments": json.dumps({"plan": plan})}}],
    }


def test_write_tools_excluded_in_plan_mode(tmp_path):
    # Dos respuestas: la primera no llama exit_plan_mode y dispara el reinject
    # (red de seguridad de modo plan), la segunda cierra el turno normalmente.
    client = _FakeClient([_final(), _final()])
    loop = AgentLoop(client, tmp_path, mode="plan", auto_verify=False)
    loop.run("agregá una función")

    offered = client.tools_per_call[0]
    for blocked in ("write_file", "edit_file", "run_command", "write_tasks",
                    "update_task", "spawn_agent", "browser_click"):
        assert blocked not in offered, f"{blocked} no debería ofrecerse en modo plan"
    assert "read_file" in offered
    assert "exit_plan_mode" in offered


def test_exit_plan_mode_excluded_outside_plan_mode(tmp_path):
    client = _FakeClient([_final()])
    loop = AgentLoop(client, tmp_path, mode="ask", auto_verify=False)
    loop.run("agregá una función")

    offered = client.tools_per_call[0]
    assert "exit_plan_mode" not in offered
    assert "write_file" in offered


def test_exit_plan_mode_triggers_plan_proposed_event_and_confirm_plan(tmp_path):
    client = _FakeClient([_call_exit_plan_mode("mi plan"), _final()])
    events = []
    confirm_plan_calls = []

    def confirm_plan(plan):
        confirm_plan_calls.append(plan)
        return False  # rechazado: se queda en modo plan

    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: "plan",
                      confirm_plan=confirm_plan,
                      on_event=lambda k, d: events.append((k, d)), auto_verify=False)
    result = loop.run("proponeme un plan")

    assert result["success"] is True
    assert confirm_plan_calls == ["mi plan"]
    plan_events = [d for k, d in events if k == "plan_proposed"]
    assert plan_events == [{"plan": "mi plan"}]


def test_approved_plan_unlocks_write_tools_in_same_run(tmp_path):
    """Tras aprobar, el modo cambia (compartido vía get_mode) y el PASO SIGUIENTE
    del mismo run() ya ofrece las tools de escritura, sin terminar el turno."""
    state = {"mode": "plan"}

    def confirm_plan(plan):
        state["mode"] = "ask"  # simula Permissions.confirm_plan cambiando el modo
        return True

    client = _FakeClient([_call_exit_plan_mode(), _final()])
    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: state["mode"],
                      confirm_plan=confirm_plan, auto_verify=False)
    result = loop.run("hacé el cambio")

    assert result["success"] is True
    assert client.calls == 2
    assert "exit_plan_mode" in client.tools_per_call[0]
    assert "write_file" not in client.tools_per_call[0]     # paso 1: todavía en plan
    assert "write_file" in client.tools_per_call[1]         # paso 2: ya aprobado


def test_rejected_plan_keeps_write_tools_blocked(tmp_path):
    client = _FakeClient([_call_exit_plan_mode(), _final()])
    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: "plan",
                      confirm_plan=lambda plan: False, auto_verify=False)
    loop.run("hacé el cambio")

    assert "write_file" not in client.tools_per_call[1]
    assert "exit_plan_mode" in client.tools_per_call[1]


def test_plan_directive_injected_to_model_but_not_to_user_event(tmp_path):
    client = _FakeClient([_final(), _final()])  # 2da respuesta: tras el reinject de plan mode
    events = []
    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: "plan",
                      on_event=lambda k, d: events.append((k, d)), auto_verify=False)
    loop.run("che, arreglá el bug")

    user_events = [d for k, d in events if k == "user"]
    assert user_events == [{"content": "che, arreglá el bug"}]  # texto ORIGINAL

    model_msg = next(m for m in loop.messages if m["role"] == "user")
    assert "[MODO PLAN activo]" in model_msg["content"]
    assert model_msg["content"].endswith("che, arreglá el bug")


def test_subagent_never_gets_plan_directive(tmp_path):
    client = _FakeClient([_final()])
    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: "plan",
                      is_subagent=True, auto_verify=False)
    loop.run("tarea delegada")

    model_msg = next(m for m in loop.messages if m["role"] == "user")
    assert model_msg["content"] == "tarea delegada"  # sin directiva, aunque mode=="plan"


def test_final_answer_without_exit_plan_mode_gets_reinjected_once(tmp_path):
    """Regresión del bug real reportado: el modelo a veces 'propone' el plan como
    texto libre en vez de llamar a exit_plan_mode, rompiendo el flujo de aprobación.
    Debe reinyectarse un pedido forzando la tool, UNA sola vez."""
    client = _FakeClient([_final("acá tenés el plan: 1. hacer X"), _final("listo")])
    events = []
    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: "plan",
                      on_event=lambda k, d: events.append((k, d)), auto_verify=False)
    result = loop.run("agregá una función")

    assert client.calls == 2
    assert result["success"] is True
    assert result["content"] == "listo"
    reinjects = [d for k, d in events if k == "plan_reinject"]
    assert reinjects == [{"attempt": 1}]


def test_final_answer_without_exit_plan_mode_only_reinjects_once(tmp_path):
    """Si el modelo insiste en no llamar la tool (p.ej. porque era una pregunta
    puramente informativa), no debe loopear para siempre: un solo reintento."""
    client = _FakeClient([_final("primera"), _final("segunda, tampoco llamo la tool")])
    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: "plan", auto_verify=False)
    result = loop.run("¿qué hace este archivo?")

    assert client.calls == 2  # no un tercer intento
    assert result["success"] is True
    assert result["content"] == "segunda, tampoco llamo la tool"


def test_no_reinject_when_exit_plan_mode_was_called_and_rejected(tmp_path):
    """Si el modelo SÍ llamó exit_plan_mode (aunque el usuario haya rechazado el
    plan), no se lo debe forzar de nuevo — puede cerrar el turno en texto libre."""
    client = _FakeClient([_call_exit_plan_mode(), _final("dale, ajusto y te aviso")])
    events = []
    loop = AgentLoop(client, tmp_path, mode="plan", get_mode=lambda: "plan",
                      confirm_plan=lambda plan: False,
                      on_event=lambda k, d: events.append((k, d)), auto_verify=False)
    result = loop.run("agregá una función")

    assert client.calls == 2
    assert result["content"] == "dale, ajusto y te aviso"
    assert [d for k, d in events if k == "plan_reinject"] == []
