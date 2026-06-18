"""Tools de filesystem: read_file, write_file, edit_file, list_dir, glob."""
from core.tools.base import ToolContext, safe_path, rel, truncate

_READ_MAX_LINES = 2000


def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = None) -> str:
    p = safe_path(ctx, path)
    if not p.exists():
        return f"ERROR: no existe {path}"
    if p.is_dir():
        return f"ERROR: {path} es un directorio (usá list_dir)"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR leyendo {path}: {e}"
    lines = content.splitlines()
    if not lines:
        return "(archivo vacío)"
    start = max(int(offset), 0)
    lim = int(limit) if limit is not None else _READ_MAX_LINES
    sliced = lines[start:start + lim]
    if not sliced:
        return f"ERROR: offset {start} fuera de rango ({len(lines)} líneas)"
    numbered = "\n".join(f"{start + i + 1:>6}\t{ln}" for i, ln in enumerate(sliced))
    if start + lim < len(lines):
        numbered += f"\n[... {len(lines) - (start + lim)} líneas más; usá offset={start + lim} ...]"
    return truncate(numbered)


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    p = safe_path(ctx, path)
    existed = p.exists()
    if not ctx.confirm(f"escribir {rel(ctx, p)} ({len(content)} chars)"):
        return "CANCELADO por el usuario"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"ERROR escribiendo {path}: {e}"
    ctx.on_event("file_write", {"path": rel(ctx, p), "bytes": len(content)})
    return f"OK: {rel(ctx, p)} {'actualizado' if existed else 'creado'} ({len(content)} chars)"


def edit_file(ctx: ToolContext, path: str, old_string: str,
              new_string: str, replace_all: bool = False) -> str:
    p = safe_path(ctx, path)
    if not p.exists():
        return f"ERROR: no existe {path}"
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR leyendo {path}: {e}"
    count = content.count(old_string)
    if count == 0:
        return f"ERROR: old_string no encontrado en {path}"
    if count > 1 and not replace_all:
        return (f"ERROR: old_string aparece {count} veces en {path}; "
                f"hacelo único (con más contexto) o usá replace_all=true")
    if not ctx.confirm(f"editar {rel(ctx, p)}"):
        return "CANCELADO por el usuario"
    n = count if replace_all else 1
    new_content = content.replace(old_string, new_string, -1 if replace_all else 1)
    try:
        p.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"ERROR escribiendo {path}: {e}"
    ctx.on_event("file_edit", {"path": rel(ctx, p), "replacements": n})
    return f"OK: {rel(ctx, p)} editado ({n} reemplazo{'s' if n > 1 else ''})"


def list_dir(ctx: ToolContext, path: str = ".") -> str:
    p = safe_path(ctx, path)
    if not p.exists():
        return f"ERROR: no existe {path}"
    if not p.is_dir():
        return f"ERROR: {path} no es un directorio"
    entries = []
    for d in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if d.name in (".git", "__pycache__"):
            continue
        entries.append(f"{d.name}/" if d.is_dir() else d.name)
    return truncate("\n".join(entries)) if entries else "(directorio vacío)"


def glob_files(ctx: ToolContext, pattern: str) -> str:
    ws = ctx.workspace.resolve()
    matches = sorted(str(m.relative_to(ws)) for m in ws.glob(pattern) if m.is_file())
    if not matches:
        return f"(sin coincidencias para {pattern})"
    return truncate("\n".join(matches[:500]))


TOOLS = {
    "read_file": {
        "impl": read_file,
        "schema": {
            "name": "read_file",
            "description": "Lee un archivo del workspace. Devuelve el contenido con números de línea. Usá offset/limit para archivos grandes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa al workspace"},
                    "offset": {"type": "integer", "description": "Línea inicial (0-based)"},
                    "limit": {"type": "integer", "description": "Cantidad de líneas a leer"},
                },
                "required": ["path"],
            },
        },
    },
    "write_file": {
        "impl": write_file,
        "schema": {
            "name": "write_file",
            "description": "Crea o sobreescribe un archivo con el contenido completo que VOS escribís. Es tu herramienta principal para crear archivos nuevos. Para modificar uno existente preferí edit_file (quirúrgico).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa al workspace"},
                    "content": {"type": "string", "description": "Contenido completo del archivo"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "edit_file": {
        "impl": edit_file,
        "schema": {
            "name": "edit_file",
            "description": "Tu herramienta PRINCIPAL para modificar código: reemplaza una porción exacta de texto en un archivo existente, tocando solo lo que cambia. Leé el archivo antes; old_string debe coincidir carácter por carácter y ser único (salvo replace_all). Nunca reescribas el archivo entero para un cambio puntual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa al workspace"},
                    "old_string": {"type": "string", "description": "Texto exacto a reemplazar (con contexto suficiente para ser único)"},
                    "new_string": {"type": "string", "description": "Texto nuevo"},
                    "replace_all": {"type": "boolean", "description": "Reemplazar todas las ocurrencias"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    "list_dir": {
        "impl": list_dir,
        "schema": {
            "name": "list_dir",
            "description": "Lista los archivos y subdirectorios de un directorio del workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa al workspace (default: raíz)"},
                },
            },
        },
    },
    "glob": {
        "impl": glob_files,
        "schema": {
            "name": "glob",
            "description": "Busca archivos por patrón glob (ej. '**/*.py', 'src/*.js') dentro del workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Patrón glob"},
                },
                "required": ["pattern"],
            },
        },
    },
}
