"""Tests del índice de recuperación BM25 (core/rag.py) y la tool search_code."""
import tempfile
from pathlib import Path

from core.rag import CodeIndex, tokenize
from core.tools.base import ToolContext
from core.tools.search_code import search_code


def _mk_workspace():
    ws = Path(tempfile.mkdtemp())
    (ws / "auth.py").write_text(
        "def login(user, password):\n    return check_credentials(user, password)\n")
    (ws / "db.py").write_text(
        "def check_credentials(u, p):\n    return query_db(u) == hash_password(p)\n")
    (ws / "ui.py").write_text(
        'def render_button(label):\n    return f"<button>{label}</button>"\n')
    return ws


def test_tokenize_splits_identifiers():
    toks = set(tokenize("getUserName user_id"))
    assert {"user", "name", "id", "getusername"} <= toks


def test_search_ranks_relevant_first():
    idx = CodeIndex(_mk_workspace())
    idx.build()
    res = idx.search("login check_credentials", k=3)
    assert res, "debería haber resultados"
    assert res[0]["path"] in ("auth.py", "db.py")
    assert all(r["path"] != "ui.py" for r in res)


def test_incremental_reindex():
    ws = _mk_workspace()
    assert CodeIndex(ws).build()["changed"] == 3      # primera vez: todo
    assert CodeIndex(ws).build()["changed"] == 0      # sin cambios
    (ws / "auth.py").write_text((ws / "auth.py").read_text() + "\n# jwt tokens\n")
    assert CodeIndex(ws).build()["changed"] == 1      # solo el que cambió
    assert (ws / ".deep" / "index" / "chunks.json").exists()


def test_index_skips_its_own_dir():
    ws = _mk_workspace()
    CodeIndex(ws).build()
    # reconstruir no debe indexar los archivos del propio índice (.deep/)
    chunks = CodeIndex(ws).build()["chunks"]
    assert all(not c["path"].startswith(".deep") for c in CodeIndex(ws).chunks)
    assert chunks == 3


def test_tool_returns_locations_and_caches():
    ws = _mk_workspace()
    ctx = ToolContext(workspace=ws)
    out = search_code(ctx, "check_credentials login")
    assert "check_credentials" in out
    assert ":" in out                       # trae archivo:línea
    assert getattr(ctx, "_code_index", None) is not None  # índice cacheado en el ctx


def test_tool_empty_query_no_match():
    ws = _mk_workspace()
    ctx = ToolContext(workspace=ws)
    assert "sin coincidencias" in search_code(ctx, "zzz_inexistente_xyz")
