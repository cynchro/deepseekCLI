"""Tool search_code: recuperación semántico-léxica (BM25) sobre el codebase.

Indexa el workspace (incremental) y devuelve los fragmentos de código MÁS relevantes
a una consulta en lenguaje natural, con su ubicación archivo:línea. A diferencia de
grep —que matchea o no, sin ranking— esto rankea por relevancia, así que sirve para
ubicar "dónde se hace X" en codebases grandes sin leer todo.
"""
import threading

from core.tools.base import ToolContext, truncate

_PREVIEW_LINES = 16

# Caché a nivel de PROCESO (no por ToolContext/AgentLoop). spawn_agent y explore
# lanzan sub-agentes en threads propios —cada uno con su propio ToolContext— pero
# casi siempre sobre el MISMO workspace que el padre. Cachear por ToolContext hacía
# que cada sub-agente cargara su propia copia del modelo de embeddings más el
# índice completo de vectores (~1GB medido en un proyecto mediano): con varios
# sub-agentes corriendo en paralelo (parallel_subagents, default hasta 4) eso
# multiplicaba la RAM y terminó en un OOM kill del proceso. Compartiendo embedder
# e índice por workspace, y serializando build+search con un lock, el costo queda
# acotado a una sola copia sin importar cuántos agentes busquen a la vez.
_embedder = "unset"
_indexes: dict = {}
_lock = threading.Lock()


def _shared_index(workspace):
    from core.rag import CodeIndex, get_embedder
    global _embedder
    key = str(workspace.resolve())
    if _embedder == "unset":
        _embedder = get_embedder()        # None si no hay backend semántico
    index = _indexes.get(key)
    if index is None:
        index = CodeIndex(workspace, embedder=_embedder)
        _indexes[key] = index
    return index


def search_code(ctx: ToolContext, query: str, k: int = 8) -> str:
    with _lock:
        index = _shared_index(ctx.workspace)
        try:
            stats = index.build()
        except Exception as e:
            return f"ERROR indexando el workspace: {e}"
        results = index.search(query, k=int(k) if k else 8)
    ctx.on_event("search_code", {"query": query[:120], "chunks": stats["chunks"],
                                 "semantic": stats.get("semantic", False)})
    if not results:
        if stats["chunks"] == 0:
            return "(no hay nada indexable en el workspace todavía)"
        return f"(sin coincidencias relevantes para: {query})"
    parts = [f"{len(results)} fragmentos relevantes (de {stats['chunks']} chunks):"]
    for r in results:
        preview = "\n".join(r["text"].splitlines()[:_PREVIEW_LINES])
        parts.append(f"\n### {r['path']}:{r['start']}-{r['end']}  (score {r['score']})\n{preview}")
    return truncate("\n".join(parts))


TOOLS = {
    "search_code": {
        "impl": search_code,
        "schema": {
            "name": "search_code",
            "description": ("Busca en el codebase por RELEVANCIA y devuelve los fragmentos más "
                            "pertinentes a una consulta en lenguaje natural, con su ubicación "
                            "archivo:línea. Mejor que grep para ubicar 'dónde se maneja X' o "
                            "'cómo se implementa Y' en proyectos grandes: rankea en vez de solo "
                            "matchear. Usalo para orientarte antes de leer; después abrí los "
                            "archivos puntuales con read_file."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Qué buscás, en lenguaje natural o por identificadores (ej. 'registro y dispatch de tools')"},
                    "k": {"type": "integer", "description": "Cuántos fragmentos devolver (default 8)"},
                },
                "required": ["query"],
            },
        },
    },
}
