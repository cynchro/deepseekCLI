"""Tests de la compactación fiel del historial (core/compaction.py)."""
from core import compaction as cp


class _FakeClient:
    """Devuelve un resumen marcado por llamada y cuenta las invocaciones."""
    def __init__(self):
        self.calls = 0
        self.systems = []

    def complete(self, messages, **kwargs):
        self.calls += 1
        self.systems.append(messages[0]["content"])
        return {"success": True, "content": f"RESUMEN#{self.calls}"}


def test_render_keeps_content_and_truncates_only_huge():
    msgs = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "x" * (cp._PER_MSG_CAP + 500)},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}, {"function": {"name": "grep"}}]},
        {"role": "tool", "content": ""},  # vacío y sin tool_calls -> se omite
    ]
    parts = cp._render(msgs)
    assert parts[0] == "USER: hola"                       # no se trunca lo corto
    assert "chars omitidos" in parts[1]                    # lo enorme se trunca con nota
    assert len(parts[1]) < cp._PER_MSG_CAP + 200
    assert "llamó tools: read_file, grep" in parts[2]      # mensaje sin texto -> tool_calls
    assert len(parts) == 3                                  # el vacío se omitió


def test_segments_split_by_budget():
    parts = ["a" * 30, "b" * 30, "c" * 30]
    assert len(cp._segments(parts, budget=50)) == 3   # dos de 30 (=60) > 50 -> uno c/u
    assert len(cp._segments(parts, budget=70)) == 2   # caben 2 (=60<=70), el 3ro aparte
    assert len(cp._segments(parts, budget=100)) == 1  # entran los tres (=90<=100)


def test_summarize_head_single_call():
    client = _FakeClient()
    head = [{"role": "user", "content": "tarea chica"},
            {"role": "assistant", "content": "hecho"}]
    out = cp.summarize_head(client, head)
    assert out == "RESUMEN#1"
    assert client.calls == 1       # un solo segmento -> una sola llamada


def test_summarize_head_map_reduce():
    client = _FakeClient()
    # 20 mensajes de ~6000 chars -> ~120k chars -> 2 segmentos -> 2 map + 1 combine
    head = [{"role": "assistant", "content": "y" * cp._PER_MSG_CAP} for _ in range(20)]
    out = cp.summarize_head(client, head)
    assert client.calls == 3                  # 2 map + 1 reduce
    assert out == "RESUMEN#3"                 # el resultado es el combine final
    assert cp._SYS_COMBINE in client.systems  # se usó el prompt de combinación


def test_empty_head_returns_empty():
    assert cp.summarize_head(_FakeClient(), []) == ""
