"""REPL agente-first de deep v2 (estilo Claude Code).

Texto natural  → va al agente (loop con tools, PRO orquesta / FLASH construye).
/comando       → slash command (config, skills, modos, legacy passthrough).
"""
import shlex
from pathlib import Path

try:
    import readline  # noqa: F401
except ImportError:
    pass

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    _HAS_PT = True
except ImportError:
    _HAS_PT = False

import core.skills as skills_mod
from core.rules import load_rules
from core.context import load_project_context, project_md_path, INIT_TASK
from cli.agent_runner import make_agent, run_turn, MODES, _MODE_HELP, _C
from cli.commands import (run_balance, run_history, run_doctor, run_show,
                          run_serve, run_upgrade)

_HISTORY_FILE = Path.home() / ".config" / "deep" / "history"


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("deepseek-builder")
    except Exception:
        try:
            import re
            pyproject = Path(__file__).parent.parent / "pyproject.toml"
            m = re.search(r'^version\s*=\s*"([^"]+)"',
                          pyproject.read_text(encoding="utf-8"), re.MULTILINE)
            return m.group(1) if m else "?"
        except Exception:
            return "?"


_BANNER = f"""{_C['bold']}{_C['green']}
  深度求索
  deep · agente DeepSeek
  v{_version()}{_C['reset']}
  Escribí lo que querés hacer en lenguaje natural.
  Comandos: {_C['dim']}/help /init /mode /model /skills /cost /clear /exit{_C['reset']}
"""

_SLASH = ["/help", "/init", "/tasks", "/mode", "/model", "/skills", "/skill", "/rules",
          "/cost", "/clear", "/new", "/balance", "/history", "/doctor", "/show",
          "/serve", "/upgrade", "/exit", "/quit"]

_HELP = f"""
  {_C['bold']}Uso{_C['reset']}: escribí la tarea en lenguaje natural y el agente la resuelve con sus tools.

  {_C['bold']}Slash commands{_C['reset']}
    /init            Explora el proyecto y escribe/actualiza DEEP.md
    /tasks           Muestra el plan de tareas persistente (.deep/tasks.json)
    /mode [m]        Permisos: {' '.join(MODES)}  (sin arg muestra el actual)
    /model [pro|flash]  Modelo orquestador del loop (default: pro)
    /skills          Lista los skills disponibles
    /skill <n> <t>   Corre una tarea aplicando el skill <n>
    /rules           Muestra DEEP.md y .deeprules cargados
    /cost            Tokens y costo estimado por modelo de esta sesión
    /clear /new      Reinicia la conversación del agente
    /balance /history /doctor /show /serve /upgrade   Comandos legacy
    /help            Esta ayuda
    /exit /quit      Salir
"""


class _Repl:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cwd = Path.cwd()
        self.prefs = {"mode": "ask", "model": None}
        self.agent = None

    def _get_agent(self):
        if self.agent is None:
            self.agent = make_agent(
                self.api_key, self.cwd,
                rules=load_rules(self.cwd / ".deeprules"),
                mode=self.prefs["mode"], model=self.prefs["model"],
            )
        return self.agent

    # ── slash commands ───────────────────────────────────────────────────────
    def slash(self, cmd: str, args: list) -> bool:
        if cmd in ("/exit", "/quit"):
            return False
        elif cmd == "/help":
            print(_HELP)
        elif cmd == "/init":
            run_turn(self._get_agent(), INIT_TASK)
        elif cmd == "/tasks":
            from core.tasks import load_tasks, render
            print("  " + render(load_tasks(self.cwd)).replace("\n", "\n  "))
        elif cmd == "/clear" or cmd == "/new":
            if self.agent:
                self.agent.reset()
            print("  Conversación reiniciada.")
        elif cmd == "/mode":
            self._mode(args)
        elif cmd == "/model":
            self._model(args)
        elif cmd == "/cost":
            self._cost()
        elif cmd == "/rules":
            self._rules()
        elif cmd == "/skills":
            self._skills()
        elif cmd == "/skill":
            self._skill(args)
        elif cmd == "/balance":
            run_balance(self.api_key)
        elif cmd == "/history":
            run_history()
        elif cmd == "/doctor":
            run_doctor()
        elif cmd == "/show":
            run_show(self.cwd)
        elif cmd == "/serve":
            run_serve(port=int(next((a for a in args if a.isdigit()), "8000")),
                      use_https="--https" in args)
        elif cmd == "/upgrade":
            run_upgrade()
        else:
            print(f"  Comando desconocido: {cmd}. Probá /help")
        return True

    def _mode(self, args):
        if not args:
            cur = self.agent.permissions.mode if self.agent else self.prefs["mode"]
            print(f"  Modo actual: {_C['bold']}{cur}{_C['reset']} — {_MODE_HELP[cur]}")
            print("  Modos: " + ", ".join(f"{m} ({_MODE_HELP[m]})" for m in MODES))
            return
        m = args[0].lower()
        if m not in MODES:
            print(f"  Modo inválido. Opciones: {', '.join(MODES)}")
            return
        self.prefs["mode"] = m
        if self.agent:
            self.agent.permissions.mode = m
        print(f"  Modo → {_C['bold']}{m}{_C['reset']} ({_MODE_HELP[m]})")

    def _model(self, args):
        from core.models import MODEL_PRO, MODEL_FLASH
        mapping = {"pro": MODEL_PRO, "flash": MODEL_FLASH}
        if not args:
            cur = self.agent.model if self.agent else (self.prefs["model"] or MODEL_PRO)
            print(f"  Modelo orquestador: {cur}")
            return
        key = args[0].lower()
        if key not in mapping:
            print("  Opciones: pro | flash")
            return
        self.prefs["model"] = mapping[key]
        if self.agent:
            self.agent.model = mapping[key]
        print(f"  Modelo orquestador → {mapping[key]}")

    def _cost(self):
        if not self.agent:
            print("  Sin actividad todavía.")
            return
        st = self.agent.client.get_stats()
        cache = st.get("cache_hit_tokens", 0)
        print(f"  Llamadas: {st['successful_calls']}  ·  tokens: {st['total_tokens_used']}"
              f"  ·  cache hits: {cache}  ·  costo estimado: ${st['estimated_cost_usd']:.4f}")
        for m, v in st.get("by_model", {}).items():
            print(f"    {m}: {v['calls']} llamadas · {v['tokens']} tok"
                  f" · {v.get('cache_hit_tokens', 0)} cacheados · ${v['cost_usd']:.4f}")

    def _rules(self):
        rules = load_rules(self.cwd / ".deeprules")
        ctx = load_project_context(self.cwd)
        if rules:
            print("  .deeprules:")
            for r in rules:
                print(f"    - {r}")
        if ctx:
            print(f"\n{ctx[:1500]}")
        if not rules and not ctx:
            print(f"  Sin DEEP.md ni .deeprules. Creá uno con /init.")

    def _skills(self):
        sk = skills_mod.load(self.cwd)
        if not sk:
            print("  Sin skills. Creá uno con: skill new (modo legacy) o agregá un .skill")
            return
        print(f"  Skills ({len(sk)}):")
        for name, s in sk.items():
            print(f"    {name:<16} {s.get('description', '')}")

    def _skill(self, args):
        if not args:
            print("  Uso: /skill <nombre> <tarea>")
            return
        name = args[0]
        sk = skills_mod.load(self.cwd)
        if name not in sk:
            print(f"  Skill '{name}' no encontrado. Ver /skills")
            return
        task = " ".join(args[1:]).strip()
        if not task:
            print(f"  Uso: /skill {name} <tarea>")
            return
        prompt = (f"Aplicá las siguientes instrucciones de skill al resolver la tarea.\n"
                  f"--- skill: {name} ---\n{sk[name]['system_prompt']}\n--- fin skill ---\n\n"
                  f"Tarea: {task}")
        run_turn(self._get_agent(), prompt)


def _prompt_text(repl: "_Repl"):
    mode = repl.prefs["mode"] if repl.agent is None else repl.agent.permissions.mode
    tag = "" if mode == "ask" else f" ({mode})"
    if not _HAS_PT:
        return f"deep{tag} ❯ "
    return HTML(f'<deep>deep</deep><mode>{tag}</mode><arrow> ❯ </arrow> ')


def run(api_key: str, update_notice: str = None):
    print(_BANNER)
    if update_notice:
        print(update_notice)
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    repl = _Repl(api_key)

    if _HAS_PT:
        style = Style.from_dict({"deep": "#00cc44 bold", "arrow": "#00cc44 bold",
                                 "mode": "#cc8800"})
        session = PromptSession(
            history=FileHistory(str(_HISTORY_FILE)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=WordCompleter(_SLASH, sentence=False, match_middle=False),
            style=style, complete_while_typing=True,
        )
        read = lambda: session.prompt(_prompt_text(repl))
    else:
        read = lambda: input(_prompt_text(repl))

    while True:
        try:
            line = read().strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            print("\n👋 Hasta luego!")
            break
        if not line:
            continue
        if line.startswith("/"):
            try:
                parts = shlex.split(line)
            except ValueError:
                parts = line.split()
            if not repl.slash(parts[0].lower(), parts[1:]):
                print("👋 Hasta luego!")
                break
        else:
            run_turn(repl._get_agent(), line)
