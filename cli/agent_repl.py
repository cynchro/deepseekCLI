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
from core import journal as _journal
from core.rules import load_rules
from core.context import load_project_context, project_md_path, INIT_TASK
from core.tasks import load_tasks, has_open
from core.i18n import t, mode_help
from cli.agent_runner import make_agent, run_turn, MODES, _C
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


def _banner() -> str:
    return (
        f"{_C['bold']}{_C['green']}\n"
        "  深度求索\n"
        f"  {t('agent.banner.subtitle')}\n"
        f"  v{_version()}{_C['reset']}\n"
        f"  {t('agent.banner.tagline')}\n"
        f"  {t('agent.banner.commands')} {_C['dim']}/help /init /mode /model /lang /skills /cost /clear /exit{_C['reset']}\n"
    )


_SLASH = ["/help", "/init", "/tasks", "/recap", "/mode", "/model", "/lang", "/skills", "/skill",
          "/rules", "/cost", "/clear", "/new", "/balance", "/history", "/doctor", "/show",
          "/serve", "/upgrade", "/exit", "/quit"]


def _help() -> str:
    return t("agent.help", b=_C["bold"], r=_C["reset"], modes=" ".join(MODES))


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
            print(_help())
        elif cmd == "/init":
            run_turn(self._get_agent(), INIT_TASK)
        elif cmd == "/tasks":
            from core.tasks import render
            print("  " + render(load_tasks(self.cwd)).replace("\n", "\n  "))
        elif cmd == "/recap":
            recap = _journal.load_recap(self.cwd)
            print("  " + recap.replace("\n", "\n  ") if recap else t("journal.empty"))
        elif cmd == "/clear" or cmd == "/new":
            _finalize_session(self)        # cierra la bitácora de lo hecho antes de limpiar
            if self.agent:
                self.agent.reset()
            print(t("conversation.reset"))
        elif cmd == "/mode":
            self._mode(args)
        elif cmd == "/model":
            self._model(args)
        elif cmd == "/lang":
            from core.config import prompt_and_save_language
            prompt_and_save_language()
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
            print(t("agent.unknown.command", cmd=cmd))
        return True

    def _mode(self, args):
        if not args:
            cur = self.agent.permissions.mode if self.agent else self.prefs["mode"]
            print(t("agent.mode.current", b=_C["bold"], mode=cur, r=_C["reset"], desc=mode_help(cur)))
            print(t("agent.mode.list", modes=", ".join(f"{m} ({mode_help(m)})" for m in MODES)))
            return
        m = args[0].lower()
        if m not in MODES:
            print(t("agent.mode.invalid", modes=", ".join(MODES)))
            return
        self.prefs["mode"] = m
        if self.agent:
            self.agent.permissions.mode = m
        print(t("agent.mode.set", b=_C["bold"], mode=m, r=_C["reset"], desc=mode_help(m)))

    def _model(self, args):
        from core.models import MODEL_PRO, MODEL_FLASH
        mapping = {"pro": MODEL_PRO, "flash": MODEL_FLASH}
        if not args:
            cur = self.agent.model if self.agent else (self.prefs["model"] or MODEL_PRO)
            print(t("agent.model.current", model=cur))
            return
        key = args[0].lower()
        if key not in mapping:
            print(t("agent.model.options"))
            return
        self.prefs["model"] = mapping[key]
        if self.agent:
            self.agent.model = mapping[key]
        print(t("agent.model.set", model=mapping[key]))

    def _cost(self):
        if not self.agent:
            print(t("agent.cost.empty"))
            return
        st = self.agent.client.get_stats()
        cache = st.get("cache_hit_tokens", 0)
        print(t("agent.cost.summary", calls=st["successful_calls"],
                tokens=st["total_tokens_used"], cache=cache,
                cost=st["estimated_cost_usd"]))
        for m, v in st.get("by_model", {}).items():
            print(t("agent.cost.model", model=m, calls=v["calls"], tokens=v["tokens"],
                    cache=v.get("cache_hit_tokens", 0), cost=v["cost_usd"]))

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
            print(t("agent.rules.none"))

    def _skills(self):
        sk = skills_mod.load(self.cwd)
        if not sk:
            print(t("agent.skills.none"))
            return
        print(t("agent.skills.list", n=len(sk)))
        for name, s in sk.items():
            print(f"    {name:<16} {s.get('description', '')}")

    def _skill(self, args):
        if not args:
            print(t("agent.skill.usage"))
            return
        name = args[0]
        sk = skills_mod.load(self.cwd)
        if name not in sk:
            print(t("agent.skill.notfound", name=name))
            return
        task = " ".join(args[1:]).strip()
        if not task:
            print(t("agent.skill.usage.named", name=name))
            return
        prompt = (f"Aplicá las siguientes instrucciones de skill al resolver la tarea.\n"
                  f"--- skill: {name} ---\n{sk[name]['system_prompt']}\n--- fin skill ---\n\n"
                  f"Tarea: {task}")
        run_turn(self._get_agent(), prompt)


def _did_work(agent) -> bool:
    """True si la sesión tuvo trabajo real (al menos un turno de usuario)."""
    return bool(agent and any(m.get("role") == "user" for m in agent.messages[1:]))


def _finalize_session(repl: "_Repl") -> None:
    """Al cerrar (o /new), resume la sesión con FLASH y la agrega a .deep/journal.md.
    Nunca rompe la salida: cualquier error se traga en silencio."""
    if not _did_work(repl.agent):
        return
    print(t("journal.saving"))
    try:
        entry = _journal.summarize_session(repl.agent.client, repl.agent.messages)
        if entry:
            _journal.append_entry(repl.cwd, entry)
    except Exception:
        pass


def _recap_banner(repl: "_Repl") -> None:
    """Al abrir, muestra la última entrada de la bitácora + tareas abiertas."""
    recap = _journal.load_recap(repl.cwd)
    if not recap:
        return
    stamp, done, nxt = "", "", ""
    for line in recap.splitlines():
        s = line.strip()
        if s.startswith("## "):
            stamp = s[3:].strip()
        elif s.startswith("**Hecho:**"):
            done = s[len("**Hecho:**"):].strip()
        elif s.startswith("**Próximo paso:**"):
            nxt = s[len("**Próximo paso:**"):].strip()
    print(t("journal.last_session", b=_C["bold"], r=_C["reset"], stamp=stamp))
    if done:
        print(t("journal.done", text=done[:300]))
    if nxt:
        print(t("journal.next_step", text=nxt[:300]))
    n_open = sum(1 for x in load_tasks(repl.cwd).get("tasks", [])
                 if x.get("status") in ("pending", "in_progress"))
    if n_open:
        print(t("journal.open_tasks", n=n_open))
    print(t("journal.continue_hint", b=_C["bold"], r=_C["reset"]))


def _prompt_text(repl: "_Repl"):
    mode = repl.prefs["mode"] if repl.agent is None else repl.agent.permissions.mode
    tag = "" if mode == "ask" else f" ({mode})"
    if not _HAS_PT:
        return f"deep{tag} ❯ "
    return HTML(f'<deep>deep</deep><mode>{tag}</mode><arrow> ❯ </arrow> ')


def run(api_key: str, update_notice: str = None):
    from core.config import load_language, prompt_and_save_language
    if load_language() is None:
        prompt_and_save_language()

    print(_banner())
    if update_notice:
        print(update_notice)
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    repl = _Repl(api_key)
    _recap_banner(repl)

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
            print()
            _finalize_session(repl)
            print(t("goodbye"))
            break
        if not line:
            continue
        if line.startswith("/"):
            try:
                parts = shlex.split(line)
            except ValueError:
                parts = line.split()
            if not repl.slash(parts[0].lower(), parts[1:]):
                _finalize_session(repl)
                print(t("goodbye"))
                break
        else:
            run_turn(repl._get_agent(), line)
