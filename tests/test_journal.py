"""Tests de la bitácora persistente entre sesiones (core/journal.py)."""
from core import journal as jn


class _FakeClient:
    """Devuelve una respuesta fija (JSON o texto) y cuenta llamadas."""
    def __init__(self, content, success=True):
        self.content = content
        self.success = success
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        return {"success": self.success, "content": self.content}


def test_append_and_load_recap_roundtrip(tmp_path):
    jn.append_entry(tmp_path, {"hecho": "creé app.py", "proximo_paso": "agregar tests",
                               "stamp": "2026-06-20 10:00"})
    jn.append_entry(tmp_path, {"hecho": "agregué tests", "proximo_paso": "deploy",
                               "stamp": "2026-06-20 12:00"})
    recap = jn.load_recap(tmp_path)
    assert "## 2026-06-20 12:00" in recap        # devuelve la ÚLTIMA entrada
    assert "agregué tests" in recap
    assert "creé app.py" not in recap            # no la anterior
    assert jn.journal_path(tmp_path).exists()


def test_load_recap_empty_when_no_file(tmp_path):
    assert jn.load_recap(tmp_path) == ""


def test_entries_capped(tmp_path):
    for i in range(jn._MAX_ENTRIES + 10):
        jn.append_entry(tmp_path, {"hecho": f"paso {i}", "stamp": f"2026-06-20 {i:02d}:00"})
    entries = jn._split_entries(jn.journal_path(tmp_path).read_text(encoding="utf-8"))
    assert len(entries) == jn._MAX_ENTRIES       # se podó a las últimas N
    assert f"paso {jn._MAX_ENTRIES + 9}" in entries[-1]   # la más reciente quedó


def test_summarize_session_parses_json(tmp_path):
    client = _FakeClient('{"hecho": "edité a.py", "decisiones": "usar sqlite", '
                         '"proximo_paso": "migrar datos"}')
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "arreglá a.py"},
            {"role": "assistant", "content": "listo, edité a.py"}]
    entry = jn.summarize_session(client, msgs)
    assert entry["hecho"] == "edité a.py"
    assert entry["proximo_paso"] == "migrar datos"
    assert "stamp" in entry
    assert client.calls == 1


def test_summarize_session_none_when_empty(tmp_path):
    client = _FakeClient('{"hecho": "x"}')
    # Solo el system: no hay turnos -> ni siquiera llama al modelo.
    assert jn.summarize_session(client, [{"role": "system", "content": "sys"}]) is None
    assert client.calls == 0


def test_summarize_session_fallback_on_non_json(tmp_path):
    client = _FakeClient("resumen en texto plano sin json")
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "hacé algo"}]
    entry = jn.summarize_session(client, msgs)
    assert entry["hecho"] == "resumen en texto plano sin json"


def test_summarize_session_none_on_failed_call(tmp_path):
    client = _FakeClient("", success=False)
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "hacé algo"}]
    assert jn.summarize_session(client, msgs) is None
