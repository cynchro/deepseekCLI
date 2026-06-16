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
                          run_show, run_serve, run_navigator)

_HISTORY_FILE = Path.home() / ".config" / "deep" / "history"


def _chat_history_path() -> Path:
    deep_dir = Path.cwd() / ".deep"
    if deep_dir.exists():
        return deep_dir / "chat_history.json"
    return Path.home() / ".config" / "deep" / "chat_history.json"


def _load_chat_history() -> dict:
    path = _chat_history_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_chat_history(state: dict) -> None:
    path = _chat_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "messages": state.get("ask_history") or [],
            "active_skill": state.get("active_skill"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _clear_chat_history() -> None:
    path = _chat_history_path()
    if path.exists():
        path.unlink()


def _banner() -> str:
    try:
        from importlib.metadata import version
        ver = version("deepseek-builder")
    except Exception:
        try:
            import re
            pyproject = Path(__file__).parent.parent / "pyproject.toml"
            m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
            ver = m.group(1) if m else "?"
        except Exception:
            ver = "?"
    return (
        "\033[1m\n"
        "╔══════════════════════════════════════════════════╗\n"
        "║           deep — Ecosistema DeepSeek             ║\n"
        f"║                    v{ver:<28}║\n"
        "╚══════════════════════════════════════════════════╝\033[0m\n"
        "  Comandos: build  update  navigator  ask  fix  show  doctor  upgrade  balance  history  reset  help  exit\n"
    )

_HELP = """
  build <tarea>          Genera un proyecto completo (manifiesto: archivo por archivo)
  build -t <archivo>     Carga la tarea desde un archivo de texto
  build <tarea> -f       Genera y corrige automáticamente si falla
  build <tarea> --single-shot  Genera todo en una respuesta (legacy, proyectos chicos)
  build <tarea> --model deepseek-reasoner
  update <cambio>        Modifica el proyecto del directorio actual
  navigator              Un LLM navigator planifica (job.md), DeepSeek construye
  navigator --init       Crea la plantilla job.md para completar con el navigator
  navigator --init --force  Regenera la plantilla aunque exista (guarda .bak)
  navigator --review     Vuelca estado para que el navigator revise el proyecto
  navigator --fix <md>   Aplica las correcciones que escribió el navigator
  ask <pregunta>         Hace una pregunta sin generar proyecto
  fix                    Corrige errores del proyecto actual
  show                   Muestra contexto y archivos del proyecto actual
  serve                  Inicia el servidor web para usar deep desde el celular
  serve --https          Activa HTTPS para instalar la app en el celular
  doctor                 Verifica que todo esté configurado correctamente
  upgrade                Actualiza deep CLI desde GitHub
  balance                Muestra el crédito disponible
  history                Muestra las experiencias acumuladas
  config                 Muestra la configuración guardada
  config set-key         Guarda una nueva API key
  config set-lang        Cambia el idioma de las respuestas
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
        "fix":     None, "show":    None, "serve":   None,
        "doctor":  None, "upgrade": None, "balance": None,
        "history": None, "config":  {"set-key": None, "set-lang": None},
        "navigator": {"--init": None, "--review": None, "--fix": None},
        "claudejob": {"--init": None, "--review": None, "--fix": None},
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
        _clear_chat_history()
        state.clear()
        print("  Conversación reiniciada.")

    elif cmd == "ask":
        if not args:
            print("  Uso: ask <pregunta>")
        else:
            state["ask_history"] = run_ask(" ".join(args), api_key, history=None)
            state["in_conversation"] = True
            _save_chat_history(state)

    elif cmd == "update":
        if not args:
            print("  Uso: update <descripción del cambio>")
        else:
            run_update(" ".join(args), api_key, Path.cwd(),
                       rules=load_rules(Path.cwd() / ".deeprules"))

    elif cmd == "show":
        run_show(Path.cwd())

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
        from core.config import prompt_and_save, prompt_and_save_language, show_config
        if args and args[0] == "set-key":
            prompt_and_save()
        elif args and args[0] == "set-lang":
            prompt_and_save_language()
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
        single_shot = False
        task_file = None
        task_parts = []
        i = 0
        while i < len(args):
            if args[i] in ("-f", "--auto-fix"):
                auto_fix = True
            elif args[i] == "--single-shot":
                single_shot = True
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
            manifest=not single_shot,
        )

    elif cmd in ("navigator", "claudejob"):
        if cmd == "claudejob":
            print("⚠️  'claudejob' quedó deprecado; usá 'navigator'. El alias seguirá funcionando por ahora.")
        init = "--init" in args
        review = "--review" in args
        auto_fix = "-f" in args or "--auto-fix" in args
        force = "--force" in args
        fix_file = None
        job_file = None
        review_module = None
        for i, a in enumerate(args):
            if a == "--fix" and i + 1 < len(args):
                fix_file = args[i + 1]
            elif a in ("-j", "--job") and i + 1 < len(args):
                job_file = args[i + 1]
            elif a == "--module" and i + 1 < len(args):
                review_module = args[i + 1]
        run_navigator(
            api_key=api_key, project_dir=Path.cwd(), job_file=job_file,
            rules=load_rules(Path.cwd() / ".deeprules"),
            init=init, review=review, fix_file=fix_file, auto_fix=auto_fix,
            force=force, review_module=review_module,
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
            _save_chat_history(state)

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
        _save_chat_history(state)

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
    print(_banner())
    if update_notice:
        print(update_notice)
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    from core.config import load_language, prompt_and_save_language
    if load_language() is None:
        prompt_and_save_language()

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
    saved = _load_chat_history()
    if saved.get("messages"):
        state["ask_history"] = saved["messages"]
        state["in_conversation"] = True
        if saved.get("active_skill"):
            state["active_skill"] = saved["active_skill"]
        n = sum(1 for m in saved["messages"] if m.get("role") == "user")
        print(f"  💬 Conversación anterior restaurada ({n} {'mensaje' if n == 1 else 'mensajes'}). Escribí 'reset' para limpiarla.\n")
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
    saved = _load_chat_history()
    if saved.get("messages"):
        state["ask_history"] = saved["messages"]
        state["in_conversation"] = True
        if saved.get("active_skill"):
            state["active_skill"] = saved["active_skill"]
        n = sum(1 for m in saved["messages"] if m.get("role") == "user")
        print(f"  💬 Conversación anterior restaurada ({n} {'mensaje' if n == 1 else 'mensajes'}). Escribí 'reset' para limpiarla.\n")
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
