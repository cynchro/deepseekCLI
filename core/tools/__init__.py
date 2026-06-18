"""Registry de tools del agente: schemas para la API + dispatch de ejecución."""
from core.tools import fs, search, shell, build, tasks, subagent, explore
from core.tools.base import ToolContext  # noqa: F401 (re-export)

_REGISTRY = {}
for _mod in (fs, search, shell, build, tasks, subagent, explore):
    _REGISTRY.update(_mod.TOOLS)


def schemas(exclude=None) -> list:
    """Definiciones de tools en formato OpenAI. `exclude` filtra por nombre."""
    ex = set(exclude or ())
    return [{"type": "function", "function": t["schema"]}
            for n, t in _REGISTRY.items() if n not in ex]


def tool_names() -> list:
    return list(_REGISTRY)


def dispatch(name: str, args: dict, ctx: ToolContext) -> str:
    """Ejecuta una tool por nombre. Nunca levanta: devuelve el error como texto
    para que el modelo lo vea y se recupere."""
    tool = _REGISTRY.get(name)
    if not tool:
        return f"ERROR: tool desconocida '{name}'"
    try:
        return tool["impl"](ctx, **(args or {}))
    except TypeError as e:
        return f"ERROR: argumentos inválidos para {name}: {e}"
    except Exception as e:
        return f"ERROR en {name}: {e}"
