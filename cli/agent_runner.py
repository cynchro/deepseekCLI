"""Runner de consola para el agent loop: imprime la actividad de tools,
maneja permisos interactivos y muestra telemetría de tokens/costo por modelo."""
from pathlib import Path

from core.client import DeepSeekClient
from core.agent_loop import AgentLoop
from core.context import load_project_context

MODES = ("ask", "auto", "plan", "yolo")
_MODE_HELP = {
    "ask":  "pide permiso para escribir y ejecutar (default)",
    "auto": "acepta ediciones de archivos; pregunta para shell",
    "plan": "solo lectura: bloquea escrituras y shell",
    "yolo": "acepta todo sin preguntar",
}

_C = {
    "dim": "\033[2m", "green": "\033[32m", "yellow": "\033[33m",
    "cyan": "\033[36m", "red": "\033[31m", "reset": "\033[0m", "bold": "\033[1m",
}


def _fmt_args(name: str, args: dict) -> str:
    if name in ("read_file", "write_file", "edit_file", "list_dir"):
        return str(args.get("path", ""))
    if name == "grep":
        return f"/{args.get('pattern', '')}/"
    if name == "glob":
        return str(args.get("pattern", ""))
    if name == "run_command":
        return str(args.get("command", ""))
    return ", ".join(f"{k}={v}" for k, v in (args or {}).items())[:80]


def _printer(kind: str, data: dict):
    if kind == "tool_call":
        print(f"  {_C['cyan']}⚙ {data['name']}{_C['reset']} "
              f"{_C['dim']}{_fmt_args(data['name'], data['args'])}{_C['reset']}")
    elif kind == "build":
        print(f"    {_C['dim']}↳ {data['action']} con flash…{_C['reset']}")
    elif kind == "tool_result":
        first = (data["result"].splitlines() or [""])[0]
        color = _C["red"] if first.startswith("ERROR") else _C["dim"]
        print(f"    {color}↳ {first[:100]}{_C['reset']}")


class Permissions:
    """Gate de permisos con modo mutable. Clasifica la acción por el texto del
    pedido (las tools llaman ctx.confirm('ejecutar: ...') para shell).

    En el prompt interactivo se puede responder 'a' para no volver a preguntar en
    toda la sesión: eso cambia el modo a 'auto' (escrituras automáticas, el shell
    sigue preguntando) o a 'yolo' si la acción era un comando de shell."""

    def __init__(self, mode: str = "ask", interactive: bool = True):
        self.mode = mode if mode in MODES else "ask"
        self.interactive = interactive

    def __call__(self, desc: str) -> bool:
        is_shell = desc.startswith("ejecutar")
        if self.mode == "plan":
            return False              # solo lectura
        if self.mode == "yolo":
            return True
        if self.mode == "auto" and not is_shell:
            return True               # escrituras automáticas; shell sí pregunta
        if not self.interactive:
            return False              # no se puede preguntar (no debería pasar en CLI)
        return self._prompt(desc, is_shell)

    def _prompt(self, desc: str, is_shell: bool) -> bool:
        try:
            ans = input(
                f"  {_C['yellow']}¿Permitir {desc}?{_C['reset']} [s/N/{_C['bold']}a{_C['reset']}] "
                f"{_C['dim']}(a = no preguntar más esta sesión){_C['reset']} "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if ans in ("a", "always", "todo", "t"):
            self.mode = "yolo" if is_shell else "auto"
            que = "todo, incluido el shell" if is_shell else "las escrituras/ediciones"
            print(f"  {_C['green']}✓ No vuelvo a preguntar por {que} esta sesión "
                  f"(modo {self.mode}). Volvé a 'ask' con /mode ask.{_C['reset']}")
            return True
        return ans in ("s", "si", "sí", "y", "yes")


def make_agent(api_key: str, workspace=None, rules=None, auto: bool = False,
               mode: str = None, model=None) -> AgentLoop:
    workspace = Path(workspace) if workspace else Path.cwd()
    client = DeepSeekClient(api_key)
    perms = Permissions(mode="yolo" if auto else (mode or "ask"))
    kwargs = {"model": model} if model else {}
    loop = AgentLoop(
        client, workspace, rules=rules,
        project_context=load_project_context(workspace),
        on_event=_printer, confirm=perms, **kwargs,
    )
    loop.permissions = perms          # para que el REPL pueda cambiar el modo
    return loop


def run_turn(loop: AgentLoop, task: str) -> dict:
    result = loop.run(task)
    if result.get("success"):
        content = (result.get("content") or "").strip()
        if content:
            print(f"\n{content}\n")
    else:
        print(f"\n{_C['red']}❌ {result.get('error')}{_C['reset']}\n")
    _print_stats(result.get("stats", {}), result.get("steps", 0))
    return result


def _print_stats(stats: dict, steps: int):
    by_model = stats.get("by_model", {})
    cost = stats.get("estimated_cost_usd", 0.0)
    models = " · ".join(
        f"{m.split('-')[-1]} {v['tokens']}tok"
        for m, v in by_model.items()
    )
    line = f"{steps} paso{'s' if steps != 1 else ''}"
    if models:
        line += f" · {models}"
    line += f" · ~${cost:.4f}"
    print(f"{_C['dim']}{line}{_C['reset']}")


def run_agent(task: str, api_key: str, workspace=None, rules=None, auto: bool = False):
    """One-shot: crea un agente y corre una sola tarea (para la CLI legacy)."""
    loop = make_agent(api_key, workspace=workspace, rules=rules, auto=auto)
    print(f"{_C['dim']}workspace: {loop.workspace}{_C['reset']}\n")
    return run_turn(loop, task)
