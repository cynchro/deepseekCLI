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
    from prompt_toolkit.application import Application, get_app
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, WordCompleter
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style
    from cli.paste import paste_key_bindings, expand_pastes, reset_pastes
    _HAS_PT = True
except ImportError:
    _HAS_PT = False

    def expand_pastes(text: str) -> str:
        return text

    def reset_pastes() -> None:
        pass

import core.skills as skills_mod
from core import journal as _journal
from core.rules import load_rules
from core.context import load_project_context, project_md_path, INIT_TASK
from core.tasks import load_tasks, has_open
from core.i18n import t, mode_help
from cli.agent_runner import make_agent, run_turn, MODES, _C, _printer, _print_stats, _input_ask
from cli.daemon_client import DaemonSession, DaemonError, ensure_daemon, list_sessions
from cli.commands import (run_balance, run_history, run_doctor, run_show,
                          run_serve, run_upgrade, run_scan)
from cli.term_title import set_title, IDLE_TITLE, TitleAnimator

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
        f"  {t('agent.banner.commands')} {_C['dim']}/help /init /scan /mode /model /lang /skills /cost /clear /sessions /attach /remote /disconnect /exit{_C['reset']}\n"
    )


_SLASH = ["/help", "/init", "/scan", "/tasks", "/recap", "/mode", "/model", "/lang", "/skills", "/skill",
          "/rules", "/cost", "/clear", "/new", "/sessions", "/attach", "/remote", "/disconnect", "/logout",
          "/balance", "/history", "/doctor", "/show", "/serve", "/upgrade", "/exit", "/quit"]

if _HAS_PT:
    class _SlashCompleter(Completer):
        """WordCompleter normal matchea la palabra vacía con todo (por eso
        aparecía la lista completa de comandos apenas arrancabas una palabra
        nueva, incluso escribiendo una tarea en texto plano). Solo sugiere
        si la línea es un slash command."""
        def __init__(self, words):
            # WORD=True: el patrón de "palabra" por default de prompt_toolkit
            # no incluye "/", así que sin esto "/mo" no filtraba a /mode /model.
            self._inner = WordCompleter(words, sentence=False, match_middle=False, WORD=True)

        def get_completions(self, document, complete_event):
            if not document.text.startswith("/"):
                return
            yield from self._inner.get_completions(document, complete_event)

    def _tab_accepts_suggestion_bindings() -> KeyBindings:
        """Tab por default solo dispara el completer de slash-commands, que no
        sugiere nada en texto plano. El usuario espera que Tab también acepte
        el autosuggest gris (AutoSuggestFromHistory), como Right/Ctrl-F ya
        hacen por default en prompt_toolkit."""
        kb = KeyBindings()

        @Condition
        def _suggestion_available():
            buf = get_app().current_buffer
            return (
                buf.suggestion is not None
                and len(buf.suggestion.text) > 0
                and buf.document.is_cursor_at_the_end
            )

        @kb.add("tab", filter=_suggestion_available)
        def _(event):
            buf = event.current_buffer
            if buf.suggestion:
                buf.insert_text(buf.suggestion.text)

        return kb

    _PICKER_STYLE = Style.from_dict({"selected": "reverse", "hint": "#00cc44 bold"})

    def _pick_mode(current: str):
        """Selector interactivo de modo: ↑↓ para moverse, Enter para elegir, Esc/Ctrl-C
        para cancelar sin cambiar nada. Devuelve el modo elegido, o None si se cancela."""
        state = {"idx": MODES.index(current) if current in MODES else 0}
        result = {"mode": None}

        def get_text():
            lines = [("", "\n  Elegí un modo ("), ("class:hint", "↑↓ Enter"),
                     ("", ", "), ("class:hint", "Esc"), ("", " cancela):\n\n")]
            for i, m in enumerate(MODES):
                is_sel = i == state["idx"]
                marker = "❯ " if is_sel else "  "
                style = "class:selected" if is_sel else ""
                lines.append((style, f"  {marker}{m:<6}{mode_help(m)}\n"))
            lines.append(("", "\n"))
            return lines

        kb = KeyBindings()

        @kb.add("up")
        def _up(event):
            state["idx"] = (state["idx"] - 1) % len(MODES)
            event.app.invalidate()

        @kb.add("down")
        def _down(event):
            state["idx"] = (state["idx"] + 1) % len(MODES)
            event.app.invalidate()

        @kb.add("enter")
        def _enter(event):
            result["mode"] = MODES[state["idx"]]
            event.app.exit()

        @kb.add("escape")
        @kb.add("c-c")
        def _cancel(event):
            event.app.exit()

        control = FormattedTextControl(get_text, focusable=True)
        app = Application(
            layout=Layout(Window(content=control, always_hide_cursor=True)),
            key_bindings=kb, style=_PICKER_STYLE, full_screen=False,
        )
        app.run()
        return result["mode"]


def _help() -> str:
    return t("agent.help", b=_C["bold"], r=_C["reset"], modes=" ".join(MODES))


class _Repl:
    def __init__(self, api_key: str, workspace=None):
        self.api_key = api_key
        if workspace is None:
            self.cwd = Path.cwd()
        elif hasattr(workspace, "run_command"):
            self.cwd = workspace  # SSHPath ya construido (workspace remoto)
        else:
            self.cwd = Path(workspace)
        self.is_remote = hasattr(self.cwd, "run_command")
        self.prefs = {"mode": "ask", "model": None}
        self.agent = None      # AgentLoop local: solo se usa sobre workspace SSH (is_remote)
        self.daemon = None     # DaemonSession: workspace local, corre en `deep serve`

    def _get_agent(self):
        if self.agent is None:
            self.agent = make_agent(
                self.api_key, self.cwd,
                rules=load_rules(self.cwd / ".deeprules"),
                mode=self.prefs["mode"], model=self.prefs["model"],
            )
        return self.agent

    def _get_daemon(self) -> DaemonSession:
        """Conecta (lazy, en el primer turno real) a un daemon local,
        arrancándolo en background si hace falta. Ver cli/daemon_client.py."""
        if self.daemon is None:
            base_url, token = ensure_daemon()
            daemon = DaemonSession(base_url, token)
            daemon.attach(project_dir=str(self.cwd),
                          mode=self.prefs["mode"], model=self.prefs["model"])
            self.daemon = daemon
        return self.daemon

    def _reconnect_daemon(self) -> DaemonSession:
        """Reabre la conexión WS reatacheando a la MISMA sesión (mismo
        session_id): el AgentLoop y su historial viven server-side, así que
        una conexión caída (turno largo, hipo de red) no pierde la
        conversación, solo el socket."""
        old_session_id = self.daemon.session_id if self.daemon else ""
        if self.daemon is not None:
            self.daemon.close()
        base_url, token = ensure_daemon()
        daemon = DaemonSession(base_url, token)
        daemon.attach(session_id=old_session_id, project_dir=str(self.cwd),
                      mode=self.prefs["mode"], model=self.prefs["model"])
        self.daemon = daemon
        return daemon

    def _run_task(self, text: str) -> None:
        """Punto único de entrada para mandar un turno de usuario, sea /init,
        /skill o texto plano: sobre SSH corre el AgentLoop local de siempre;
        si no, va al daemon (mismo esquema de eventos, mismo _printer)."""
        if self.is_remote:
            run_turn(self._get_agent(), text)
        else:
            self._send_turn(text)

    def _run_turn_with_reconnect(self, daemon: DaemonSession, text: str):
        """Manda el turno; si la conexión se cortó a mitad de camino (turno
        largo, red), reatachea a la misma sesión del daemon y reintenta UNA
        vez. Devuelve None (ya habiendo impreso el error) si no se pudo.

        Si al reatachear la sesión sigue `busy` (el turno anterior seguía
        corriendo server-side, no se sabe si nuestro mensaje llegó a
        completarse), NO reenviamos el texto: solo escuchamos su resultado
        con wait_turn. Reenviarlo duplicaría el trabajo y quemaría tokens
        de nuevo si el turno original ya había terminado."""
        try:
            return daemon.run_turn(text, on_event=_printer, ask_confirm=_input_ask)
        except DaemonError:
            print(f"\n  {_C['yellow']}⚠ se cortó la conexión con el daemon, "
                  f"reconectando...{_C['reset']}")
            try:
                daemon = self._reconnect_daemon()
            except DaemonError as e:
                print(f"\n{_C['red']}❌ no se pudo reconectar: {e}{_C['reset']}\n")
                self.daemon = None
                return None
            try:
                if daemon.busy:
                    return daemon.wait_turn(on_event=_printer, ask_confirm=_input_ask)
                return daemon.run_turn(text, on_event=_printer, ask_confirm=_input_ask)
            except DaemonError as e:
                print(f"\n{_C['red']}❌ {e}{_C['reset']}\n")
                return None

    def _send_turn(self, text: str) -> None:
        try:
            daemon = self._get_daemon()
        except DaemonError as e:
            print(f"\n{_C['red']}❌ {e}{_C['reset']}\n")
            return
        title = TitleAnimator()
        title.start()
        try:
            result = self._run_turn_with_reconnect(daemon, text)
        finally:
            title.stop()
        if result is None:
            return
        if result.get("busy"):
            print(f"  {_C['yellow']}⏳ esta sesión ya tiene un turno en curso "
                  f"(otro cliente atacheado){_C['reset']}")
            return
        if result.get("success"):
            content = (result.get("content") or "").strip()
            if content:
                print(f"\n{content}\n")
        else:
            print(f"\n{_C['red']}❌ {result.get('error')}{_C['reset']}\n")
        _print_stats(result.get("stats", {}), result.get("steps", 0))

    def _current_mode(self) -> str:
        if self.agent:
            return self.agent.permissions.mode
        if self.daemon:
            return self.daemon.mode
        return self.prefs["mode"]

    def _current_model(self, default: str) -> str:
        if self.agent:
            return self.agent.model
        if self.daemon:
            return self.daemon.model or default
        return self.prefs["model"] or default

    # ── slash commands ───────────────────────────────────────────────────────
    def slash(self, cmd: str, args: list) -> bool:
        if cmd in ("/exit", "/quit"):
            if self.is_remote:
                self.cwd.close()  # sin esto el hilo de paramiko no es daemon y el proceso queda colgado
            if self.daemon:
                self.daemon.close()
            return False
        elif cmd == "/help":
            print(_help())
        elif cmd == "/init":
            self._run_task(INIT_TASK)
        elif cmd == "/scan":
            if self.is_remote:
                print("  /scan no está soportado todavía en un workspace remoto.")
            else:
                run_scan(self.api_key, self.cwd,
                         refresh=("-r" in args or "--refresh" in args))
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
            elif self.daemon:
                self.daemon.reset()
            print(t("conversation.reset"))
        elif cmd == "/sessions":
            self._sessions_list()
        elif cmd == "/attach":
            self._attach_cmd(args)
        elif cmd == "/remote":
            self._remote()
        elif cmd == "/disconnect" or cmd == "/logout":
            self._disconnect()
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
            if self.is_remote:
                print("  /show no está soportado todavía en un workspace remoto.")
            else:
                run_show(self.cwd)
        elif cmd == "/serve":
            run_serve(port=int(next((a for a in args if a.isdigit()), "8000")),
                      use_https="--https" in args)
        elif cmd == "/upgrade":
            run_upgrade()
        else:
            print(t("agent.unknown.command", cmd=cmd))
        return True

    def _remote(self):
        """Conecta la sesión actual a un workspace remoto vía SSH, paso a paso
        (host, después la carpeta con el mismo picker de `deep remote --host`),
        sin tener que recordar la sintaxis completa del comando. Cierra la
        bitácora de la sesión anterior antes de cambiar de workspace, igual que
        /clear, y fuerza que se arme un agente nuevo apuntando a la remota."""
        try:
            host_spec = input(t("agent.remote.host_prompt")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not host_spec:
            print(t("agent.remote.cancelled"))
            return
        try:
            from core.ssh_workspace import RemoteBrowseCancelled, resolve_remote_workspace
            ws = resolve_remote_workspace(host_spec, None)
        except RemoteBrowseCancelled:
            print(t("agent.remote.cancelled"))
            return
        except Exception as e:
            print(t("agent.remote.error", error=e))
            return
        _finalize_session(self)
        if self.daemon:
            self.daemon.close()
            self.daemon = None
        self.cwd = ws
        self.is_remote = True
        self.agent = None
        print(t("agent.remote.connected", host=ws.host_spec, path=ws))

    def _disconnect(self):
        """Cierra la conexión SSH y vuelve a trabajar en el directorio local
        (inverso de /remote). Cierra la bitácora de la sesión remota antes de
        soltarla, igual que /clear y /remote."""
        if not self.is_remote:
            print(t("agent.remote.not_connected"))
            return
        _finalize_session(self)
        self.cwd.close()
        self.cwd = Path.cwd()
        self.is_remote = False
        self.agent = None
        print(t("agent.remote.disconnected", path=self.cwd))

    def _mode(self, args):
        if not args:
            cur = self._current_mode()
            if not _HAS_PT:
                print(t("agent.mode.current", b=_C["bold"], mode=cur, r=_C["reset"], desc=mode_help(cur)))
                print(t("agent.mode.list", modes=", ".join(f"{m} ({mode_help(m)})" for m in MODES)))
                return
            chosen = _pick_mode(cur)
            if chosen is None or chosen == cur:
                return
            args = [chosen]
        m = args[0].lower()
        if m not in MODES:
            print(t("agent.mode.invalid", modes=", ".join(MODES)))
            return
        self.prefs["mode"] = m
        if self.agent:
            self.agent.permissions.set_mode(m)
        elif self.daemon:
            self.daemon.set_mode(m)
        print(t("agent.mode.set", b=_C["bold"], mode=m, r=_C["reset"], desc=mode_help(m)))

    def _model(self, args):
        from core.models import MODEL_PRO, MODEL_FLASH
        mapping = {"pro": MODEL_PRO, "flash": MODEL_FLASH}
        if not args:
            print(t("agent.model.current", model=self._current_model(MODEL_PRO)))
            return
        key = args[0].lower()
        if key not in mapping:
            print(t("agent.model.options"))
            return
        self.prefs["model"] = mapping[key]
        if self.agent:
            self.agent.model = mapping[key]
        elif self.daemon:
            self.daemon.set_model(mapping[key])
        print(t("agent.model.set", model=mapping[key]))

    def _cost(self):
        if self.agent:
            st = self.agent.client.get_stats()
        elif self.daemon:
            st = self.daemon.get_stats()
        else:
            st = None
        if not st:
            print(t("agent.cost.empty"))
            return
        cache = st.get("cache_hit_tokens", 0)
        print(t("agent.cost.summary", calls=st["successful_calls"],
                tokens=st["total_tokens_used"], cache=cache,
                cost=st["estimated_cost_usd"]))
        by_model = st.get("by_model", {})
        for m, v in by_model.items():
            print(t("agent.cost.model", model=m, calls=v["calls"], tokens=v["tokens"],
                    cache=v.get("cache_hit_tokens", 0), cost=v["cost_usd"]))
        from core.models import MODEL_PRO, MODEL_FLASH
        pro_cost = by_model.get(MODEL_PRO, {}).get("cost_usd", 0.0)
        flash_cost = by_model.get(MODEL_FLASH, {}).get("cost_usd", 0.0)
        total = pro_cost + flash_cost
        if total > 0:
            print(t("agent.cost.split", pro_pct=round(pro_cost / total * 100),
                    flash_pct=round(flash_cost / total * 100)))

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
        self._run_task(prompt)

    def _sessions_list(self):
        if self.is_remote:
            print("  /sessions no está soportado en un workspace remoto (SSH).")
            return
        try:
            base_url, token = ensure_daemon()
            sessions = list_sessions(base_url, token)
        except Exception as e:
            print(f"  ❌ {e}")
            return
        if not sessions:
            print("  No hay sesiones activas en el daemon.")
            return
        for s in sessions:
            marker = "→" if self.daemon and s["id"] == self.daemon.session_id else " "
            busy = "  (ocupada)" if s["busy"] else ""
            print(f"  {marker} {s['id'][:8]}  {s['workspace']}  modo={s['mode']}{busy}")

    def _attach_cmd(self, args):
        if self.is_remote:
            print("  /attach no está soportado en un workspace remoto (SSH).")
            return
        if not args:
            print("  Uso: /attach <id>  (ver /sessions)")
            return
        sid = args[0]
        try:
            base_url, token = ensure_daemon()
            new_daemon = DaemonSession(base_url, token)
            new_daemon.attach(session_id=sid)
        except Exception as e:
            print(f"  ❌ {e}")
            return
        if self.daemon:
            self.daemon.close()
        self.daemon = new_daemon
        print(f"  ✓ Atacheado a la sesión {sid[:8]} "
              f"({self.daemon.workspace}, modo={self.daemon.mode})")


def _did_work(agent) -> bool:
    """True si la sesión tuvo trabajo real (al menos un turno de usuario)."""
    return bool(agent and any(m.get("role") == "user" for m in agent.messages[1:]))


def _finalize_session(repl: "_Repl") -> None:
    """Al cerrar (o /new), resume la sesión con FLASH y la agrega a .deep/journal.md.
    Nunca rompe la salida: cualquier error se traga en silencio. Si la sesión
    vive en el daemon, el resumen corre server-side (ahí están client/messages),
    ver SessionHub.finalize en pwa/session_hub.py."""
    if repl.daemon is not None:
        if repl.daemon.did_work:
            print(t("journal.saving"))
            try:
                repl.daemon.finalize()
            except Exception:
                pass
        return
    if not _did_work(repl.agent):
        return
    print(t("journal.saving"))
    try:
        entry = _journal.summarize_session(repl.agent.client, repl.agent.messages)
        if entry:
            _journal.append_entry(repl.cwd, entry)
    except Exception:
        pass


def _auto_onboard(repl: "_Repl") -> None:
    """Si la carpeta actual es un proyecto existente sin contexto cacheado, lo
    DETECTA (barato, solo filesystem) y sugiere `/scan`. NO dispara la llamada
    LLM en el arranque: el análisis caro corre solo si el usuario tipea `/scan`.
    No avisa si ya hay `.deep/context.json` ni si no parece un proyecto."""
    if (repl.cwd / ".deep" / "context.json").exists():
        return  # ya onboardeado o generado por deep
    try:
        from core.project_scanner import scan
        pmap = scan(repl.cwd)
    except Exception:
        return
    if not pmap.get("subprojects"):
        return  # no parece un proyecto reconocible → ni el hint
    print(t("onboard.hint"))


def _recap_banner(repl: "_Repl") -> None:
    """Al abrir, muestra la última entrada de la bitácora + tareas abiertas.

    Las tareas se muestran AUNQUE no haya bitácora: journal.md solo se escribe al
    cerrar prolijamente (_finalize_session, con una llamada a FLASH), así que un
    cierre abrupto (kill -9, OOM) nunca llega a escribirla. .deep/tasks.json en
    cambio se guarda en cada write_tasks/update_task —una escritura simple y
    síncrona—, así que sigue siendo la fuente de verdad de qué falta aunque la
    sesión anterior se haya cortado de golpe."""
    recap = _journal.load_recap(repl.cwd)
    n_open = sum(1 for x in load_tasks(repl.cwd).get("tasks", [])
                 if x.get("status") in ("pending", "in_progress"))
    if not recap and not n_open:
        return
    if recap:
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
    elif n_open:
        print(t("journal.abrupt_end"))
    if n_open:
        print(t("journal.open_tasks", n=n_open))
    print(t("journal.continue_hint", b=_C["bold"], r=_C["reset"]))


def _prompt_text(repl: "_Repl"):
    mode = repl._current_mode()
    tag = "" if mode == "ask" else f" ({mode})"
    if not _HAS_PT:
        return f"deep{tag} ❯ "
    return HTML(f'<deep>deep</deep><mode>{tag}</mode><arrow> ❯ </arrow> ')


def run(api_key: str, update_notice: str = None, workspace=None):
    from core.config import load_language, prompt_and_save_language
    if load_language() is None:
        prompt_and_save_language()

    print(_banner())
    if update_notice:
        print(update_notice)
    set_title(IDLE_TITLE)
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    repl = _Repl(api_key, workspace)
    if repl.is_remote:
        # /scan depende del scanner legacy (no adaptado a rutas remotas): el
        # auto-onboard solo sirve para sugerirlo, así que no aplica acá.
        print(f"  📡 conectado a {repl.cwd.host_spec}:{repl.cwd}\n")
    else:
        _auto_onboard(repl)
    _recap_banner(repl)

    if _HAS_PT:
        style = Style.from_dict({"deep": "#00cc44 bold", "arrow": "#00cc44 bold",
                                 "mode": "#cc8800"})
        session = PromptSession(
            history=FileHistory(str(_HISTORY_FILE)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=_SlashCompleter(_SLASH),
            key_bindings=merge_key_bindings([paste_key_bindings(), _tab_accepts_suggestion_bindings()]),
            style=style, complete_while_typing=True,
        )
        read = lambda: session.prompt(_prompt_text(repl))
    else:
        read = lambda: input(_prompt_text(repl))

    while True:
        reset_pastes()
        try:
            line = expand_pastes(read()).strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            print()
            _finalize_session(repl)
            if repl.is_remote:
                repl.cwd.close()
            if repl.daemon:
                repl.daemon.close()
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
            repl._run_task(line)
