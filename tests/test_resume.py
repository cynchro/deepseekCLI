"""Test del auto-resume al agotar max_steps con tareas abiertas en el plan."""
import tempfile

import core.agent_loop as al
from core.agent_loop import AgentLoop


class _NeverFinishesClient:
    """Siempre devuelve una tool call -> el loop nunca llega a respuesta final."""
    def __init__(self):
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        return {"success": True, "content": "", "finish_reason": "tool_calls",
                "tool_calls": [{"id": f"t{self.calls}",
                                "function": {"name": "noop", "arguments": "{}"}}]}

    def get_stats(self):
        return {"by_model": {}, "estimated_cost_usd": 0.0}


def _count_events(loop_kwargs, has_open, monkeypatch):
    monkeypatch.setattr(al, "dispatch", lambda name, args, ctx: "ok")
    monkeypatch.setattr(al._taskstore, "load_tasks", lambda ws: {})
    monkeypatch.setattr(al._taskstore, "has_open", lambda td: has_open)
    events = []
    loop = AgentLoop(_NeverFinishesClient(), tempfile.mkdtemp(),
                     on_event=lambda k, d: events.append(k),
                     confirm=lambda d: True, max_steps=1, **loop_kwargs)
    res = loop.run("hacé un montón de cosas")
    return res, events.count("auto_resume")


def test_auto_resume_until_cap(monkeypatch):
    res, resumes = _count_events({"max_auto_resume": 2}, has_open=True, monkeypatch=monkeypatch)
    assert resumes == 2, f"debería reintentar hasta el tope, hubo {resumes}"
    assert res.get("max_steps_reached") is True   # tras agotar los resumes, corta


def test_no_resume_without_open_tasks(monkeypatch):
    res, resumes = _count_events({"max_auto_resume": 3}, has_open=False, monkeypatch=monkeypatch)
    assert resumes == 0, "sin tareas abiertas no debe auto-reanudar"
    assert res.get("max_steps_reached") is True


def test_subagent_does_not_auto_resume(monkeypatch):
    res, resumes = _count_events({"max_auto_resume": 3, "is_subagent": True},
                                 has_open=True, monkeypatch=monkeypatch)
    assert resumes == 0, "los sub-agentes no auto-reanudan (los maneja el padre)"
