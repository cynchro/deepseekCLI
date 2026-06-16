import json
import os
import shlex
import sys
from pathlib import Path

try:
    import readline  # noqa: F401 — activa historial y edición de línea en input()
except ImportError:
    pass

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
import core.skills as skills_mod
from cli.commands import (run_build, run_balance, run_history, run_fix_current,
                          run_ask, run_skill, run_update, run_doctor, run_upgrade,
                          run_show, run_serve, run_scan)

_HISTORY_FILE = Path.home() / ".config" / "deep" / "history"

_BANNER = """\033[1m
╔══════════════════════════════════════════════════╗
║           deep — Ecosistema DeepSeek             ║
╚══════════════════════════════════════════════════╝\033[0m
  Comandos: build  update  ask  fix  show  doctor  upgrade  balance  history  reset  help  exit
"""

_HELP = """
  build <tarea>          Genera un proyecto completo
  build -t <archivo>     Carga la tarea desde un archivo de texto
  build <tarea> -f       Genera y corrige automáticamente si falla
  build <tarea> --model deepseek-reasoner
  update <cambio>        Modifica el proyecto del directorio actual
  scan                   Analiza un proyecto existente y arma su contexto
  scan -r                Re-analiza (refresca el contexto cacheado)
  ask <pregunta>         Hace una pregunta sin generar proyecto
  fix                    Corrige errores del proyecto actual
  show                   Muestra contexto y archivos del proyecto actual
  serve                  Inicia el servidor web para usar deep desde el celular
  serve --https          Activa HTTPS para instalar la app en el celular
  doctor                 Verifica que todo esté configurado correctamente
  upgrade                Actualiza deep CLI desde GitHub
  balance                Muestra el crédito disponible
  history                Muestra las experiencias acumuladas
  config                 Muestra la API key guardada
  config set-key         Guarda una nueva API key
  help                   Esta ayuda
  reset / new            Reinicia la conversación actual
  exit / quit / Ctrl+D   Salir
"""

_STYLE = Style.from_dict({
    "deep":    "#00cc44 bold",
    "arrow":   "#00cc44 bold",
    "project": "#888888 italic",
}) if _HAS_PROMPT_TOOLKIT else None

def _build_completer(skill_names: list):
    if not _HAS_PROMPT_TOOLKIT:
        return None
    base = {
        "build":   None, "update":  None, "ask":     None,
        "scan":    None, "fix":     None, "show":    None, "serve":   None,
        "doctor":  None, "upgrade": None, "balance": None,
        "history": None, "config":  {"set-key": None},
        "skill":   {"list": None, "new": None},
        "reset":   None, "new":     None,
        "help":    None, "exit":    None, "quit":    None,
    }
    for name in skill_names:
        base[name] = None
    return NestedCompleter.from_nested_dict(base)


def _detect_project() -> str:
    ctx_file = Path.cwd() / ".deep" / "context.json"
    if ctx_file.exists():
        try:
            ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
            return ctx.get("task", "")[:28]
        except Exception:
            pass
    return ""


def _auto_onboard(api_key: str) -> None:
    """Si la carpeta actual es un proyecto existente sin contexto, lo analiza una vez."""
    if (Path.cwd() / ".deep" / "context.json").exists():
        return  # ya onboardeado o generado por deep
    try:
        from core.project_scanner import scan
        pmap = scan(Path.cwd())
    except Exception:
        return
    if not pmap.get("subprojects"):
        return  # no parece un proyecto reconocible → no gastar una llamada
    print("\n🆕 Proyecto existente detectado sin contexto previo.")
    try:
        run_scan(api_key, Path.cwd())
    except Exception as e:
        print(f"⚠️  No se pudo analizar el proyecto: {e}")


def _prompt_text(project: str, in_chat: bool = False) -> "HTML | str":
    if in_chat:
        if not _HAS_PROMPT_TOOLKIT:
            return "chat ❯ "
        return HTML('<deep>chat</deep><arrow> ❯ </arrow> ')
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


def _handle(cmd: str, args: list, api_key: str, state: dict, loaded_skills: dict = None):
    if cmd in ("exit", "quit", "q"):
        return False                       # señal de salida

    if cmd == "help":
        print(_HELP)

    elif cmd == "balance":
        run_balance(api_key)

    elif cmd == "history":
        run_history()

    elif cmd in ("reset", "new"):
        state.clear()
        print("  Conversación reiniciada.")

    elif cmd == "ask":
        if not args:
            print("  Uso: ask <pregunta>")
        else:
            state["ask_history"] = run_ask(" ".join(args), api_key, history=None)
            state["in_conversation"] = True

    elif cmd == "update":
        if not args:
            print("  Uso: update <descripción del cambio>")
        else:
            run_update(" ".join(args), api_key, Path.cwd(),
                       rules=load_rules(Path.cwd() / ".deeprules"))

    elif cmd == "show":
        run_show(Path.cwd())

    elif cmd == "scan":
        run_scan(api_key, Path.cwd(), refresh="-r" in args or "--refresh" in args)

    elif cmd == "serve":
        use_https = "--https" in args
        port_args = [a for a in args if a.isdigit()]
        port = int(port_args[0]) if port_args else 8000
        run_serve(port=port, use_https=use_https)

    elif cmd == "doctor":
        run_doctor()

    elif cmd == "upgrade":
        run_upgrade()

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
            print("       build -t <archivo>  (carga tarea desde archivo)")
            return True
        model = "deepseek-chat"
        auto_fix = False
        task_file = None
        task_parts = []
        i = 0
        while i < len(args):
            if args[i] in ("-f", "--auto-fix"):
                auto_fix = True
            elif args[i] == "--model" and i + 1 < len(args):
                model = args[i + 1]
                i += 1
            elif args[i] in ("-t", "--task-file") and i + 1 < len(args):
                task_file = args[i + 1]
                i += 1
            else:
                task_parts.append(args[i])
            i += 1
        if task_file:
            tf = Path(task_file)
            if not tf.exists():
                print(f"  ❌ Archivo no encontrado: {tf}")
                return True
            task = tf.read_text(encoding="utf-8").strip()
            if not task:
                print(f"  ❌ El archivo está vacío: {tf}")
                return True
            print(f"  📄 Tarea cargada desde: {tf}")
        else:
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

    elif cmd == "skill":
        _handle_skill_meta(args, loaded_skills or {})

    elif loaded_skills and cmd in loaded_skills:
        skill = loaded_skills[cmd]
        if not args and not state.get("in_conversation"):
            print(f"  Uso: {cmd} <pregunta>")
        else:
            full_input = " ".join(args) if args else (cmd + " " + " ".join(args)).strip()
            if state.get("active_skill") != cmd:
                # Cambio de skill → nueva conversación con ese system prompt
                state["ask_history"] = None
                state["active_skill"] = cmd
            state["ask_history"] = run_skill(
                skill, full_input, api_key, history=state.get("ask_history")
            )
            state["in_conversation"] = True

    elif state.get("in_conversation"):
        full_input = (cmd + " " + " ".join(args)).strip()
        active = state.get("active_skill")
        if active and loaded_skills and active in loaded_skills:
            state["ask_history"] = run_skill(
                loaded_skills[active], full_input, api_key,
                history=state.get("ask_history"),
            )
        else:
            state["ask_history"] = run_ask(full_input, api_key, history=state.get("ask_history"))

    else:
        print(f"  Comando desconocido: '{cmd}'. Escribí 'help'.")

    return True                            # continuar el loop


def _handle_skill_meta(args: list, loaded_skills: dict):
    sub = args[0] if args else "list"

    if sub == "list":
        if not loaded_skills:
            print("  Sin skills instalados. Creá uno con: skill new <nombre>")
            return
        print(f"\n  📦 Skills disponibles ({len(loaded_skills)}):\n")
        for name, sk in loaded_skills.items():
            desc = sk.get("description", "")
            print(f"     {name:<16} {desc}")
        print()

    elif sub == "new":
        name = args[1] if len(args) > 1 else None
        if not name:
            try:
                name = input("  Nombre del skill: ").strip()
            except (EOFError, KeyboardInterrupt):
                return
        if not name:
            return
        try:
            desc = input("  Descripción breve: ").strip()
            print("  System prompt (terminá con una línea que solo diga FIN):")
            lines = []
            while True:
                line = input()
                if line.strip().upper() == "FIN":
                    break
                lines.append(line)
            system_prompt = "\n".join(lines).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelado.")
            return
        if not system_prompt:
            print("  El system prompt no puede estar vacío.")
            return
        try:
            raw = input("  ¿Local al proyecto? [s/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raw = "n"
        local = raw in ("s", "si", "sí", "y", "yes")
        path = skills_mod.create(name, desc, system_prompt, project_local=local)
        print(f"  ✅ Skill '{name}' guardado en {path}")
        loaded_skills.update(skills_mod.load(Path.cwd()))

    else:
        print(f"  Subcomando desconocido: skill {sub}  (list | new)")


def run(api_key: str, update_notice: str | None = None):
    print(_BANNER)
    if update_notice:
        print(update_notice)
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    _auto_onboard(api_key)

    if _HAS_PROMPT_TOOLKIT:
        _run_rich(api_key)
    else:
        print("⚠️  prompt_toolkit no encontrado. Instalá con: pip install prompt_toolkit\n"
              "   Usando modo básico.\n")
        _run_basic(api_key)


def _run_rich(api_key: str):
    loaded_skills = skills_mod.load(Path.cwd())
    session = PromptSession(
        history=FileHistory(str(_HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=_build_completer(list(loaded_skills)),
        style=_STYLE,
        complete_while_typing=True,
    )
    state: dict = {}
    while True:
        try:
            project = _detect_project()
            line = session.prompt(_prompt_text(project, state.get("in_conversation", False)))
        except KeyboardInterrupt:
            continue
        except EOFError:
            print("\n👋 Hasta luego!")
            break

        cmd, args = _parse(line)
        if cmd is None:
            continue
        if not _handle(cmd, args, api_key, state, loaded_skills):
            print("👋 Hasta luego!")
            break


def _run_basic(api_key: str):
    loaded_skills = skills_mod.load(Path.cwd())
    state: dict = {}
    while True:
        try:
            project = _detect_project()
            line = input(_prompt_text(project, state.get("in_conversation", False)))
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Hasta luego!")
            break
        cmd, args = _parse(line)
        if cmd is None:
            continue
        if not _handle(cmd, args, api_key, state, loaded_skills):
            print("👋 Hasta luego!")
            break
