"""Tool de búsqueda: grep (regex sobre archivos del workspace, en Python puro)."""
import re

from core.tools.base import ToolContext, safe_path, truncate

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              ".deep", "dist", "build", ".rag"}
_MAX_MATCHES = 200


def grep(ctx: ToolContext, pattern: str, path: str = ".",
         ignore_case: bool = False, glob: str = None) -> str:
    base = safe_path(ctx, path)
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        return f"ERROR: regex inválida: {e}"

    if base.is_file():
        files = [base]
    elif base.is_dir():
        it = base.rglob(glob) if glob else base.rglob("*")
        files = [f for f in it
                 if f.is_file() and not any(part in _SKIP_DIRS for part in f.parts)]
    else:
        return f"ERROR: no existe {path}"

    ws = ctx.workspace.resolve()
    out = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{f.relative_to(ws)}:{i}:{line.strip()[:200]}")
                    if len(out) >= _MAX_MATCHES:
                        out.append(f"[... cortado en {_MAX_MATCHES} coincidencias ...]")
                        return truncate("\n".join(out))
        except Exception:
            continue
    return truncate("\n".join(out)) if out else f"(sin coincidencias para /{pattern}/)"


TOOLS = {
    "grep": {
        "impl": grep,
        "schema": {
            "name": "grep",
            "description": "Busca un patrón regex en los archivos del workspace. Devuelve líneas como 'archivo:nº:texto'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Patrón regex a buscar"},
                    "path": {"type": "string", "description": "Archivo o directorio donde buscar (default: raíz)"},
                    "ignore_case": {"type": "boolean", "description": "Ignorar mayúsculas/minúsculas"},
                    "glob": {"type": "string", "description": "Filtrar archivos por glob (ej. '*.py')"},
                },
                "required": ["pattern"],
            },
        },
    },
}
