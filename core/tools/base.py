"""Infra compartida de tools: contexto de ejecución, seguridad de paths, truncado."""
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Set

MAX_RESULT_CHARS = 30_000  # tope de lo que una tool devuelve al modelo
_DIFF_MAX_LINES = 80       # tope de líneas de diff que se muestran / devuelven al modelo


@dataclass
class ToolContext:
    """Estado que comparten todas las tools durante un run del agente."""
    workspace: Path
    on_event: Callable[[str, dict], None] = lambda kind, data: None
    confirm: Callable[[str], bool] = lambda desc: True
    builder: object = None  # CodeBuilder (FLASH) para generate_code / apply_edit
    spawn: Callable[..., str] = None  # delega una tarea a un sub-agente (spawn_agent)
    explore: Callable[..., str] = None  # investigación read-only delegada a FLASH (explore)
    # Archivos que el agente ya conoce (leyó o escribió) en este run. Sirve para el
    # guard read-before-edit: editar a ciegas un archivo no visto es fuente de errores.
    known_files: Set[str] = field(default_factory=set)


def make_diff(old: str, new: str, path: str, max_lines: int = _DIFF_MAX_LINES) -> str:
    """Diff unificado compacto entre dos versiones de un archivo. '' si no hay cambios."""
    diff = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="", n=2,
    ))
    if not diff:
        return ""
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... (+{len(diff) - max_lines} líneas de diff omitidas)"]
    return "\n".join(diff)


def safe_path(ctx: ToolContext, path: str) -> Path:
    """Resuelve `path` dentro del workspace. Bloquea escapes (`..`, absolutos fuera)."""
    raw = Path(path)
    p = (raw if raw.is_absolute() else ctx.workspace / raw).resolve()
    ws = ctx.workspace.resolve()
    if p != ws and not p.is_relative_to(ws):
        raise ValueError(f"Ruta fuera del workspace: {path}")
    return p


def rel(ctx: ToolContext, p: Path) -> str:
    """Path relativo al workspace para mostrar (cae a absoluto si no se puede)."""
    try:
        r = p.resolve().relative_to(ctx.workspace.resolve())
        return str(r) if str(r) != "." else "."
    except Exception:
        return str(p)


def truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncado, {len(text) - limit} chars más ...]"
