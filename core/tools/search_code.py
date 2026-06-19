"""Tool search_code: recuperación semántico-léxica (BM25) sobre el codebase.

Indexa el workspace (incremental) y devuelve los fragmentos de código MÁS relevantes
a una consulta en lenguaje natural, con su ubicación archivo:línea. A diferencia de
grep —que matchea o no, sin ranking— esto rankea por relevancia, así que sirve para
ubicar "dónde se hace X" en codebases grandes sin leer todo.
"""
from core.tools.base import ToolContext, truncate

_PREVIEW_LINES = 16


def search_code(ctx: ToolContext, query: str, k: int = 8) -> str:
    from core.rag import CodeIndex, get_embedder
    # Caché del índice y del embedder por run: evita recargar y recargar el modelo.
    index = getattr(ctx, "_code_index", None)
    if index is None or str(index.workspace) != str(ctx.workspace.resolve()):
        embedder = getattr(ctx, "_embedder", "unset")
        if embedder == "unset":
            embedder = get_embedder()        # None si no hay backend semántico
            ctx._embedder = embedder
        index = CodeIndex(ctx.workspace, embedder=embedder)
        ctx._code_index = index
    try:
        stats = index.build()
    except Exception as e:
        return f"ERROR indexando el workspace: {e}"
    ctx.on_event("search_code", {"query": query[:120], "chunks": stats["chunks"],
                                 "semantic": stats.get("semantic", False)})
    results = index.search(query, k=int(k) if k else 8)
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
