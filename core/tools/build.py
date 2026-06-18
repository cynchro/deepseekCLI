"""Tools de construcción que delegan a FLASH: generate_code, apply_edit.

PRO llama estas tools con una especificación/instrucción compacta; el CodeBuilder
(FLASH) produce el contenido completo. Se devuelve un resumen a PRO, no el código,
para mantener su contexto liviano.
"""
from core.tools.base import ToolContext, safe_path, rel


def generate_code(ctx: ToolContext, path: str, spec: str, context_files: list = None) -> str:
    if ctx.builder is None:
        return "ERROR: builder no disponible; usá write_file"
    p = safe_path(ctx, path)
    ctx.on_event("build", {"action": "generate", "path": rel(ctx, p), "model": "flash"})
    res = ctx.builder.generate(rel(ctx, p), spec, ctx.workspace, context_files)
    if not res.get("success"):
        return f"ERROR generando {path} (flash): {res.get('error')}"
    content = res["content"]
    if not ctx.confirm(f"escribir {rel(ctx, p)} ({len(content)} chars, generado por flash)"):
        return "CANCELADO por el usuario"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"ERROR escribiendo {path}: {e}"
    ctx.on_event("file_write", {"path": rel(ctx, p), "bytes": len(content)})
    return f"OK: {rel(ctx, p)} generado por flash ({len(content)} chars, {content.count(chr(10)) + 1} líneas)"


def apply_edit(ctx: ToolContext, path: str, instructions: str, context_files: list = None) -> str:
    if ctx.builder is None:
        return "ERROR: builder no disponible; usá edit_file"
    p = safe_path(ctx, path)
    if not p.exists():
        return f"ERROR: no existe {path} (usá generate_code para crearlo)"
    try:
        current = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR leyendo {path}: {e}"
    ctx.on_event("build", {"action": "edit", "path": rel(ctx, p), "model": "flash"})
    res = ctx.builder.edit(rel(ctx, p), instructions, current, ctx.workspace, context_files)
    if not res.get("success"):
        return f"ERROR editando {path} (flash): {res.get('error')}"
    new = res["content"]
    if new.strip() == current.strip():
        return f"Sin cambios en {rel(ctx, p)} (flash devolvió contenido idéntico)"
    if not ctx.confirm(f"actualizar {rel(ctx, p)} (editado por flash)"):
        return "CANCELADO por el usuario"
    try:
        p.write_text(new, encoding="utf-8")
    except Exception as e:
        return f"ERROR escribiendo {path}: {e}"
    ctx.on_event("file_edit", {"path": rel(ctx, p), "replacements": 1})
    old_n, new_n = current.count("\n") + 1, new.count("\n") + 1
    return f"OK: {rel(ctx, p)} editado por flash ({old_n}→{new_n} líneas)"


TOOLS = {
    "generate_code": {
        "impl": generate_code,
        "schema": {
            "name": "generate_code",
            "description": ("EXCEPCIÓN, no la regla: crea un archivo delegando la escritura a un "
                            "modelo rápido y más barato (FLASH). Usalo SOLO para volumen mecánico de "
                            "bajo riesgo (boilerplate, scaffolding, fixtures, traducir formatos). Para "
                            "lógica, algoritmos o APIs públicas escribí vos con write_file. Pasá "
                            "context_files con los archivos relevantes si necesita contexto."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del archivo a crear (relativa al workspace)"},
                    "spec": {"type": "string", "description": "Especificación clara y completa de qué debe contener/hacer el archivo"},
                    "context_files": {"type": "array", "items": {"type": "string"},
                                      "description": "Rutas de archivos existentes que FLASH debería leer como contexto"},
                },
                "required": ["path", "spec"],
            },
        },
    },
    "apply_edit": {
        "impl": apply_edit,
        "schema": {
            "name": "apply_edit",
            "description": ("EXCEPCIÓN, no la regla: modifica un archivo delegando a un modelo rápido "
                            "(FLASH), que REESCRIBE el archivo completo. Riesgoso para código fino "
                            "(puede alterar lo que no debía). Usalo SOLO para cambios masivos y mecánicos "
                            "de bajo riesgo. Para modificar código que importa, usá edit_file (quirúrgico). "
                            "No tenés que leer el archivo primero: FLASH ya recibe su contenido."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del archivo a modificar (relativa al workspace)"},
                    "instructions": {"type": "string", "description": "Qué cambio aplicar, en lenguaje natural"},
                    "context_files": {"type": "array", "items": {"type": "string"},
                                      "description": "Otros archivos que FLASH debería leer como contexto"},
                },
                "required": ["path", "instructions"],
            },
        },
    },
}
