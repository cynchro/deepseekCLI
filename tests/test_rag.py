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


# ── camino semántico (embedder opcional) ────────────────────────────────────────

def _stub_embedder(texts):
    """Embedder falso por conceptos: agrupa sinónimos ES/EN en la misma dimensión,
    así 'credenciales' (query) y 'credentials' (código) caen cerca aunque no compartan
    ni un token léxico. Determinista, sin red ni modelo."""
    auth = {"login", "credentials", "credenciales", "auth", "autenticar",
            "autenticacion", "autenticación", "password", "usuario", "user"}
    math = {"prime", "primo", "number", "numero", "número", "factor", "math"}
    ui = {"button", "render", "boton", "botón", "ui", "html", "label"}
    out = []
    for t in texts:
        tl = t.lower()
        out.append([float(sum(w in tl for w in group)) for group in (auth, math, ui)])
    return out


def test_semantic_rescues_crosslanguage_query():
    ws = _mk_workspace()
    query = "autenticación de credenciales del usuario"   # español; el código está en inglés

    # BM25 puro: sin solape léxico no debería encontrar auth.py
    lexical = CodeIndex(ws).search(query, k=3)
    assert all(r["path"] != "auth.py" for r in lexical), "BM25 no debería matchear cross-idioma"

    # Con embedder semántico: auth.py se rescata por coseno
    idx = CodeIndex(ws, embedder=_stub_embedder)
    st = idx.build()
    assert st["semantic"] is True
    res = idx.search(query, k=3)
    paths = [r["path"] for r in res]
    assert res and paths[0] in ("auth.py", "db.py"), res   # rescata lo relacionado a auth
    assert "ui.py" not in paths                            # y descarta lo no relacionado
    assert (ws / ".deep" / "index" / "vectors.json").exists()


def test_vectors_incremental_reuse():
    ws = _mk_workspace()
    CodeIndex(ws, embedder=_stub_embedder).build()
    calls = {"n": 0}

    def counting_embedder(texts):
        calls["n"] += len(list(texts))
        return _stub_embedder(texts)

    # Reconstruir sin cambios: no debería re-embeddear ningún chunk (todos cacheados).
    CodeIndex(ws, embedder=counting_embedder).build()
    assert calls["n"] == 0
