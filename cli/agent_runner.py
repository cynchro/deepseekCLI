"""Runner de consola para el agent loop: imprime la actividad de tools,
maneja permisos interactivos y muestra telemetría de tokens/costo por modelo."""
from pathlib import Path

from core.client import DeepSeekClient
from core.agent_loop import AgentLoop

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
    elif kind == "tool_result":
        first = (data["result"].splitlines() or [""])[0]
        color = _C["red"] if first.startswith("ERROR") else _C["dim"]
        print(f"    {color}↳ {first[:100]}{_C['reset']}")


def _confirm(desc: str) -> bool:
    try:
        ans = input(f"  {_C['yellow']}¿Permitir {desc}? [s/N]{_C['reset']} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("s", "si", "sí", "y", "yes")


def make_agent(api_key: str, workspace=None, rules=None, auto: bool = False) -> AgentLoop:
    workspace = Path(workspace) if workspace else Path.cwd()
    client = DeepSeekClient(api_key)
    confirm = (lambda desc: True) if auto else _confirm
    return AgentLoop(client, workspace, rules=rules, on_event=_printer, confirm=confirm)


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
