import json
import os
import shlex
import sys
from pathlib import Path

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import NestedCompleter
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    _HAS_PROMPT_TOOLKIT = False

from core.rules import load_rules
from cli.commands import run_build, run_balance, run_history, run_fix_current

_HISTORY_FILE = Path.home() / ".config" / "deep" / "history"

_BANNER = """\033[1m
╔══════════════════════════════════════════════════╗
║           deep — Ecosistema DeepSeek             ║
╚══════════════════════════════════════════════════╝\033[0m
  Comandos: build  fix  balance  history  help  exit
"""

_HELP = """
  build <tarea>          Genera un proyecto completo
  build <tarea> -f       Genera y corrige automáticamente si falla
  build <tarea> --model deepseek-reasoner
  fix                    Corrige el proyecto del directorio actual
  balance                Muestra el crédito disponible
  history                Muestra las experiencias acumuladas
  config                 Muestra la API key guardada
  config set-key         Guarda una nueva API key
  help                   Esta ayuda
  exit / quit / Ctrl+D   Salir
"""

_STYLE = Style.from_dict({
    "deep":    "#00cc44 bold",
    "arrow":   "#00cc44 bold",
    "project": "#888888 italic",
}) if _HAS_PROMPT_TOOLKIT else None

_COMPLETER = NestedCompleter.from_nested_dict({
    "build":   None,
    "fix":     None,
    "balance": None,
    "history": None,
    "config":  {"set-key": None},
    "help":    None,
    "exit":    None,
    "quit":    None,
}) if _HAS_PROMPT_TOOLKIT else None


def _detect_project() -> str:
    ctx_file = Path.cwd() / ".deep" / "context.json"
    if ctx_file.exists():
        try:
            ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
            return ctx.get("task", "")[:28]
        except Exception:
            pass
    return ""


def _prompt_text(project: str) -> "HTML | str":
    if not _HAS_PROMPT_TOOLKIT:
        prefix = f"[{project}] " if project else ""
        return f"{prefix}deep ❯ "
    if project:
        return HTML(f'<project>[{project}]</project> <deep>deep</deep><arrow> ❯ </arrow> ')
    return HTML('<deep>deep</deep><arrow> ❯ </arrow> ')


def _parse(line: str):
    try:
        parts = shlex.split(line.strip())
    except ValueError:
        parts = line.strip().split()
    if not parts:
        return None, []
    return parts[0].lower(), parts[1:]


def _handle(cmd: str, args: list, api_key: str):
    if cmd in ("exit", "quit", "q"):
        return False                       # señal de salida

    if cmd == "help":
        print(_HELP)

    elif cmd == "balance":
        run_balance(api_key)

    elif cmd == "history":
        run_history()

    elif cmd == "config":
        from core.config import prompt_and_save, show_config
        if args and args[0] == "set-key":
            prompt_and_save()
        else:
            show_config()

    elif cmd == "fix":
        run_fix_current(api_key, Path.cwd(), load_rules(Path.cwd() / ".deeprules"))

    elif cmd == "build":
        if not args:
            print("  Uso: build <descripción del proyecto>")
            return True
        model = "deepseek-chat"
        auto_fix = False
        task_parts = []
        i = 0
        while i < len(args):
            if args[i] in ("-f", "--auto-fix"):
                auto_fix = True
            elif args[i] == "--model" and i + 1 < len(args):
                model = args[i + 1]
                i += 1
            else:
                task_parts.append(args[i])
            i += 1
        task = " ".join(task_parts)
        if not task:
            print("  Uso: build <descripción del proyecto>")
            return True
        run_build(
            task=task, api_key=api_key,
            output_dir=str(Path.cwd()),
            model=model, root_is_output_dir=False,
            rules=load_rules(Path.cwd() / ".deeprules"),
            verbose=False, auto_fix=auto_fix,
        )

    else:
        print(f"  Comando desconocido: '{cmd}'. Escribí 'help'.")

    return True                            # continuar el loop


def run(api_key: str):
    print(_BANNER)
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _HAS_PROMPT_TOOLKIT:
        _run_rich(api_key)
    else:
        print("⚠️  prompt_toolkit no encontrado. Instalá con: pip install prompt_toolkit\n"
              "   Usando modo básico.\n")
        _run_basic(api_key)


def _run_rich(api_key: str):
    session = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=_COMPLETER,
        style=_STYLE,
        complete_while_typing=True,
    )
    while True:
        try:
            project = _detect_project()
            line = session.prompt(_prompt_text(project))
        except KeyboardInterrupt:
            continue
        except EOFError:
            print("\n👋 Hasta luego!")
            break

        cmd, args = _parse(line)
        if cmd is None:
            continue
        if not _handle(cmd, args, api_key):
            print("👋 Hasta luego!")
            break


def _run_basic(api_key: str):
    while True:
        try:
            project = _detect_project()
            line = input(_prompt_text(project))
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Hasta luego!")
            break
        cmd, args = _parse(line)
        if cmd is None:
            continue
        if not _handle(cmd, args, api_key):
            print("👋 Hasta luego!")
            break
