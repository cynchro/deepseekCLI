"""Runner de consola para el agent loop: imprime la actividad de tools,
maneja permisos interactivos y muestra telemetría de tokens/costo por modelo."""
from pathlib import Path

from core.client import DeepSeekClient
from core.agent_loop import AgentLoop
from core.context import load_project_context
from cli.term_title import TitleAnimator

MODES = ("ask", "auto", "plan", "yolo")
_MODE_HELP = {
    "ask":  "pide permiso para escribir y ejecutar (default)",
    "auto": "acepta ediciones de archivos; pregunta para shell",
    "plan": "solo lectura: investiga y propone un plan para aprobar antes de ejecutar",
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
    if name in ("search_code", "explore"):
        return str(args.get("query", ""))[:70]
    if name == "glob":
        return str(args.get("pattern", ""))
    if name == "run_command":
        return str(args.get("command", ""))
    return ", ".join(f"{k}={v}" for k, v in (args or {}).items())[:80]


def _printer(kind: str, data: dict):
    if kind == "thinking":
        print(f"\n{_C['dim']}{data['text']}{_C['reset']}")
    elif kind == "tool_call":
        print(f"  {_C['cyan']}⚙ {data['name']}{_C['reset']} "
              f"{_C['dim']}{_fmt_args(data['name'], data['args'])}{_C['reset']}")
    elif kind == "build":
        print(f"    {_C['dim']}↳ {data['action']} con flash…{_C['reset']}")
    elif kind == "tasks":
        from core.tasks import render
        body = render(data["data"]).replace("\n", "\n  ")
        print(f"  {_C['cyan']}📋 plan{_C['reset']}\n  {_C['dim']}{body}{_C['reset']}")
    elif kind == "plan_proposed":
        body = data.get("plan", "").replace("\n", "\n  ")
        print(f"\n  {_C['cyan']}📋 plan propuesto{_C['reset']}\n  {_C['dim']}{body}{_C['reset']}\n")
    elif kind == "search_code":
        print(f"  {_C['cyan']}🔎 search_code{_C['reset']} {_C['dim']}{data.get('query','')[:70]}"
              f" ({data.get('chunks',0)} chunks){_C['reset']}")
    elif kind == "file_diff":
        for ln in data.get("diff", "").splitlines():
            if ln.startswith("+") and not ln.startswith("+++"):
                print(f"    {_C['green']}{ln}{_C['reset']}")
            elif ln.startswith("-") and not ln.startswith("---"):
                print(f"    {_C['red']}{ln}{_C['reset']}")
            else:
                print(f"    {_C['dim']}{ln}{_C['reset']}")
    elif kind == "verify":
        print(f"  {_C['cyan']}✓ verificando: {_C['reset']}{_C['dim']}{data.get('command','')}{_C['reset']}")
    elif kind == "verify_result":
        ok = data.get("exit") == 0
        col = _C["green"] if ok else _C["red"]
        print(f"    {col}↳ verificación {'OK' if ok else 'FALLÓ'} (exit={data.get('exit')}){_C['reset']}")
    elif kind == "verify_reinject":
        print(f"  {_C['yellow']}↻ tests en rojo — el agente sigue para arreglarlo{_C['reset']}")
    elif kind == "plan_reinject":
        print(f"  {_C['yellow']}↻ te propuso texto en vez de un plan formal — "
              f"le pido que use exit_plan_mode{_C['reset']}")
    elif kind == "explore_start":
        print(f"  {_C['cyan']}🔍 explorando (flash):{_C['reset']} "
              f"{_C['dim']}{data.get('question','')[:80]}{_C['reset']}")
    elif kind == "explore_done":
        icon = "✓" if data.get("success") else "⚠"
        print(f"  {_C['cyan']}🔍 {icon} investigación lista{_C['reset']}")
    elif kind == "auto_resume":
        print(f"  {_C['yellow']}↻ límite de pasos alcanzado, quedan tareas — sigo solo "
              f"({data.get('attempt')}/{data.get('max')}){_C['reset']}")
    elif kind == "parallel_start":
        print(f"  {_C['green']}⫸ {data.get('count')} sub-agentes en paralelo{_C['reset']}")
    elif kind == "parallel_done":
        print(f"  {_C['green']}⫷ sub-agentes en paralelo listos{_C['reset']}")
    elif kind == "subagent_start":
        print(f"  {_C['green']}↪ sub-agente:{_C['reset']} {data.get('task','')[:80]}")
    elif kind == "subagent_done":
        files = data.get("files") or []
        icon = "↩" if data.get("success") else "↩ ⚠"
        extra = f" ({len(files)} archivos)" if files else ""
        print(f"  {_C['green']}{icon} sub-agente listo{extra}{_C['reset']}")
    elif kind == "compact":
        print(f"  {_C['dim']}🗜  contexto compactado (~{data.get('tokens_before',0)}→"
              f"{data.get('tokens_after',0)} tok){_C['reset']}")
    elif kind == "shell_wait":
        print(f"\r    {_C['dim']}⏳ {data.get('elapsed')}s transcurridos, sigue corriendo...{_C['reset']}   ",
              end="", flush=True)
    elif kind == "tool_result":
        first = (data["result"].splitlines() or [""])[0]
        color = _C["red"] if first.startswith("ERROR") else _C["dim"]
        print(f"\r{' ' * 72}\r    {color}↳ {first[:100]}{_C['reset']}")
    elif kind == "info":
        # Solo lo emite el daemon (ej. Permissions._notify vía WS) — la
        # sesión local imprime directo con print(), sin pasar por acá.
        print(data.get("text", ""))


def _input_ask(desc: str, is_shell: bool, kind: str = "confirm") -> str:
    """Callback `ask` default de Permissions: pide confirmación por stdin/stdout.
    Es función de módulo (no método) para poder reusarla tal cual como
    `ask_confirm` del cliente del daemon (cli/daemon_client.py), que responde
    confirm_request sin tener una instancia de Permissions local.

    `kind="plan"` es la aprobación de exit_plan_mode: prompt distinto, sin la
    opción "a" (no aplica a aprobar un plan)."""
    try:
        if kind == "plan":
            return input(
                f"  {_C['yellow']}¿Aprobás {desc} y pasás a modo ejecución?{_C['reset']} [s/N] "
            ).strip().lower()
        return input(
            f"  {_C['yellow']}¿Permitir {desc}?{_C['reset']} [s/N/{_C['bold']}a{_C['reset']}] "
            f"{_C['dim']}(a = no preguntar más esta sesión){_C['reset']} "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


class Permissions:
    """Gate de permisos con modo mutable. Clasifica la acción por el texto del
    pedido (las tools llaman ctx.confirm('ejecutar: ...') para shell).

    En el prompt interactivo se puede responder 'a' para no volver a preguntar en
    toda la sesión: eso cambia el modo a 'auto' (escrituras automáticas, el shell
    sigue preguntando) o a 'yolo' si la acción era un comando de shell."""

    def __init__(self, mode: str = "ask", interactive: bool = True, ask=None, notify=None,
                 on_mode_change=None):
        """ask(desc, is_shell, kind="confirm") -> str y notify(msg) son pluggables para
        poder responder confirmaciones por un transporte distinto a stdin/stdout (ej.
        round-trip por WebSocket desde el daemon). Por default se comportan igual que
        antes (input()/print() locales). on_mode_change(new_mode) es opcional: lo usa
        el daemon para hacer broadcast del cambio de modo a otros clientes atacheados."""
        self.mode = mode if mode in MODES else "ask"
        self._pre_plan_mode = None    # modo al que volver cuando se apruebe un plan
        self.interactive = interactive
        self._ask = ask or _input_ask
        self._notify = notify or print
        self._on_mode_change = on_mode_change

    def set_mode(self, new_mode: str) -> None:
        """Punto único para cambiar de modo: recuerda el modo previo al ENTRAR a
        'plan' (para volver ahí cuando se apruebe un plan) y notifica el cambio si
        hay callback configurado. Reemplaza asignar `.mode` directo."""
        new_mode = new_mode if new_mode in MODES else "ask"
        if new_mode == self.mode:
            return
        if new_mode == "plan":
            self._pre_plan_mode = self.mode
        self.mode = new_mode
        if self._on_mode_change:
            self._on_mode_change(new_mode)

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
        ans = self._ask(desc, is_shell)
        if ans in ("a", "always", "todo", "t"):
            self.set_mode("yolo" if is_shell else "auto")
            que = "todo, incluido el shell" if is_shell else "las escrituras/ediciones"
            self._notify(f"  {_C['green']}✓ No vuelvo a preguntar por {que} esta sesión "
                         f"(modo {self.mode}). Volvé a 'ask' con /mode ask.{_C['reset']}")
            return True
        return ans in ("s", "si", "sí", "y", "yes")

    def confirm_plan(self, plan: str) -> bool:
        """Aprobación de exit_plan_mode: a diferencia de __call__, SIEMPRE pregunta
        (bypassa el gate de modo — en modo 'plan' __call__ se auto-denegaría antes de
        preguntar nada). Si se aprueba, vuelve al modo previo a entrar en 'plan'."""
        if not self.interactive:
            return False
        ans = self._ask("el plan propuesto arriba", False, kind="plan")
        approved = ans in ("s", "si", "sí", "y", "yes")
        if approved:
            target = self._pre_plan_mode or "ask"
            self._pre_plan_mode = None
            self.set_mode(target)
            self._notify(f"  {_C['green']}✓ Plan aprobado — paso a modo {target}.{_C['reset']}")
        return approved


def make_agent(api_key: str, workspace=None, rules=None, auto: bool = False,
               mode: str = None, model=None) -> AgentLoop:
    if workspace is None:
        workspace = Path.cwd()
    elif not hasattr(workspace, "run_command"):
        # str/Path local; un SSHPath ya construido (backend remoto) se usa tal cual.
        workspace = Path(workspace)
    client = DeepSeekClient(api_key)
    perms = Permissions(mode="yolo" if auto else (mode or "ask"))
    kwargs = {"model": model} if model else {}
    loop = AgentLoop(
        client, workspace, rules=rules,
        project_context=load_project_context(workspace),
        on_event=_printer, confirm=perms, confirm_plan=perms.confirm_plan,
        mode=perms.mode, get_mode=lambda: perms.mode, **kwargs,
    )
    loop.permissions = perms          # para que el REPL pueda cambiar el modo
    return loop


def run_turn(loop: AgentLoop, task: str) -> dict:
    title = TitleAnimator()
    title.start()
    try:
        result = loop.run(task)
    finally:
        title.stop()
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
