"""Test del paralelismo de sub-agentes en el AgentLoop.

Determinista (sin timing frágil): el dispatch falso espera en un threading.Barrier
de 2 partes. Si los dos spawn_agent corrieran en SECUENCIA, el primero bloquearía para
siempre en el barrier → el test detectaría el deadlock por timeout. Que pase confirma
que se ejecutaron concurrentemente.
"""
import tempfile
import threading

import core.agent_loop as al
from core.agent_loop import AgentLoop


class _FakeClient:
    """Devuelve 2 spawn_agent el primer turno, y una respuesta final después."""
    def __init__(self):
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "success": True, "content": "", "finish_reason": "tool_calls",
                "tool_calls": [
                    {"id": "a", "function": {"name": "spawn_agent",
                                             "arguments": '{"task": "modulo A"}'}},
                    {"id": "b", "function": {"name": "spawn_agent",
                                             "arguments": '{"task": "modulo B"}'}},
                ],
            }
        return {"success": True, "content": "listo", "finish_reason": "stop",
                "tool_calls": None}

    def get_stats(self):
        return {"by_model": {}, "estimated_cost_usd": 0.0}


def test_subagents_run_in_parallel(monkeypatch):
    barrier = threading.Barrier(2, timeout=5)
    seen_threads = set()

    def fake_dispatch(name, args, ctx):
        assert name == "spawn_agent"
        seen_threads.add(threading.get_ident())
        barrier.wait()      # deadlock+timeout si fueran secuenciales
        return "OK sub-agente"

    monkeypatch.setattr(al, "dispatch", fake_dispatch)

    loop = AgentLoop(_FakeClient(), tempfile.mkdtemp(),
                     confirm=lambda d: True, parallel_subagents=True)
    res = loop.run("construí A y B en paralelo")

    assert res["success"], res
    assert len(seen_threads) == 2, "los dos sub-agentes deberían correr en threads distintos"


def test_sequential_when_disabled(monkeypatch):
    """Con parallel_subagents=False, los spawn van uno por uno (sin barrier que trabe)."""
    order = []

    def fake_dispatch(name, args, ctx):
        order.append(args.get("task"))
        return "OK"

    monkeypatch.setattr(al, "dispatch", fake_dispatch)
    loop = AgentLoop(_FakeClient(), tempfile.mkdtemp(),
                     confirm=lambda d: True, parallel_subagents=False)
    res = loop.run("A y B")
    assert res["success"]
    assert order == ["modulo A", "modulo B"]   # orden secuencial preservado
