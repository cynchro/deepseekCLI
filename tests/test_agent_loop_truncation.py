"""Test del manejo de finish_reason == 'length' en core/agent_loop.py: si el modelo
corta a mitad de un tool_calls, el batch queda con arguments JSON incompletos. El fix
descarta ese assistant SIN adjuntarle tool_calls (si no, queda un grupo sin sus mensajes
'tool' y la próxima llamada a la API lo rechaza con 400) y le pide al modelo reintentar
con llamadas más chicas, en vez de romper el historial."""
from core.agent_loop import AgentLoop


class _FakeClient:
    """Devuelve una secuencia fija de respuestas de complete(), una por llamada."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        return self._responses.pop(0)

    def get_stats(self):
        return {}


_TRUNCATED = {
    "success": True,
    "content": "",
    "tool_calls": [{"id": "call_1", "type": "function",
                    "function": {"name": "write_file",
                                 "arguments": '{"path": "a.py", "cont'}}],
    "finish_reason": "length",
}

_FINAL = {
    "success": True,
    "content": "listo",
    "tool_calls": None,
    "finish_reason": "stop",
}


def test_truncated_tool_calls_are_discarded_not_persisted(tmp_path):
    client = _FakeClient([_TRUNCATED, _FINAL])
    events = []
    loop = AgentLoop(client, tmp_path, on_event=lambda k, d: events.append((k, d)),
                      auto_verify=False)

    result = loop.run("hacé algo")

    assert result["success"] is True
    assert result["content"] == "listo"
    assert client.calls == 2  # se reintentó una vez tras el corte, no más

    # Ningún mensaje del historial quedó con tool_calls sin sus respuestas 'tool'.
    for i, m in enumerate(loop.messages):
        if m.get("tool_calls"):
            ids_needed = {tc["id"] for tc in m["tool_calls"]}
            ids_answered = {
                mm["tool_call_id"] for mm in loop.messages[i + 1:]
                if mm.get("role") == "tool" and mm.get("tool_call_id") in ids_needed
            }
            assert ids_needed == ids_answered, "quedó un tool_calls sin su mensaje 'tool'"

    assert ("truncated", {"finish_reason": "length"}) in events
    retry_msgs = [m["content"] for m in loop.messages if m["role"] == "user"]
    assert any("se cortó por límite de tokens" in c for c in retry_msgs)
