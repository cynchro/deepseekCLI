"""Tests de DeepSeekLearningSystem._resolve_plan (fase 1 del build).

Verifican el contrato que usa claudejob: un plan dict se usa TAL CUAL (sin
re-planificar), un str siembra el planner, y None planifica desde cero. Se
instancia el system con object.__new__ para no abrir cliente ni red.
"""
from core.system import DeepSeekLearningSystem


def _bare_system():
    return object.__new__(DeepSeekLearningSystem)


def test_dict_plan_used_directly_without_replanning():
    sys = _bare_system()
    called = {"planned": False}

    def _must_not_plan(*a, **k):
        called["planned"] = True
        return {}

    sys._plan_structured = _must_not_plan
    plan_in = {
        "architecture": "arch del arquitecto",
        "files": [{"path": "auth/login.py", "description": "login", "depends_on": []},
                  {"path": "auth/jwt.py", "description": "tokens", "depends_on": []}],
    }
    out = sys._resolve_plan("tarea", plan_in)

    assert called["planned"] is False, "un plan estructurado NO debe re-planificar"
    assert sorted(f["path"] for f in out["files"]) == ["auth/jwt.py", "auth/login.py"]
    assert out["architecture"] == "arch del arquitecto"


def test_str_plan_seeds_the_planner():
    sys = _bare_system()
    captured = {}

    def _seeded(task, external_plan=None):
        captured["task"] = task
        captured["external_plan"] = external_plan
        return {"architecture": "x", "files": [], "order": []}

    sys._plan_structured = _seeded
    sys._resolve_plan("mi tarea", "plan de texto de Claude")

    assert captured["task"] == "mi tarea"
    assert captured["external_plan"] == "plan de texto de Claude"


def test_none_plans_from_scratch():
    sys = _bare_system()
    captured = {}

    def _plan(task, external_plan=None):
        captured["external_plan"] = external_plan
        return {"architecture": "x", "files": [], "order": []}

    sys._plan_structured = _plan
    sys._resolve_plan("mi tarea", None)

    assert captured["external_plan"] is None
