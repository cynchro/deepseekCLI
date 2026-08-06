#!/usr/bin/env python3
"""
deep — CLI/REPL para generar proyectos con DeepSeek.

  deep                          → abre el REPL interactivo
  deep build "tarea"            → genera un proyecto y sale
  deep build "tarea" -f         → genera, corrige si falla, y sale
  deep balance                  → muestra el crédito y sale
  deep history                  → muestra experiencias acumuladas y sale
  deep config                   → muestra la configuración actual
  deep config set-key           → guarda una nueva API key

  deep --debug <comando>        → activa debug.log paso a paso en el dir actual
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32":
    os.system("")  # habilita secuencias ANSI en la consola de Windows 10+


def _require_api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY")
    if key:
        return key
    from core.config import load_api_key, prompt_and_save
    key = load_api_key()
    return key if key else prompt_and_save()


def _legacy(argv: list):
    """Modo legacy para scripting: deep build/balance/history/config + args."""
    import argparse
    from core.rules import load_rules
    from cli.commands import run_build, run_balance, run_history

    parser = argparse.ArgumentParser(prog="deep",
                                     description="Genera proyectos con DeepSeek")
    sub = parser.add_subparsers(dest="command", metavar="comando")
    sub.required = True

    sub.add_parser("help", help="Muestra ayuda").set_defaults(func=lambda _: print(__doc__))

    p_bal = sub.add_parser("balance", help="Muestra el crédito")
    p_bal.set_defaults(func=lambda a: run_balance(_require_api_key()))

    p_hist = sub.add_parser("history", help="Muestra experiencias acumuladas")
    p_hist.set_defaults(func=lambda a: run_history())

    p_build = sub.add_parser("build", help="Genera un proyecto completo")
    p_build.add_argument("task", nargs="*", metavar="TAREA")
    p_build.add_argument("-t", "--task-file", metavar="ARCHIVO",
                         help="Carga la descripción de la tarea desde un archivo de texto")
    p_build.add_argument("-o", "--output", metavar="DIR")
    p_build.add_argument("-n", "--name", default="", metavar="NOMBRE",
                         help="Nombre del directorio del proyecto")
    p_build.add_argument("--model", default="deepseek-chat", metavar="MODELO")
    p_build.add_argument("-f", "--auto-fix", action="store_true",
                         help="Corregir automáticamente si la evaluación falla")
    p_build.add_argument("-v", "--verbose", action="store_true")

    def do_build(args):
        api_key = _require_api_key()
        if args.task_file:
            task_path = Path(args.task_file)
            if not task_path.exists():
                print(f"❌ Archivo no encontrado: {task_path}")
                return
            task = task_path.read_text(encoding="utf-8").strip()
            if not task:
                print(f"❌ El archivo está vacío: {task_path}")
                return
            print(f"📄 Tarea cargada desde: {task_path}")
        elif args.task:
            task = " ".join(args.task)
        else:
            print("❌ Especificá una tarea o usá -t <archivo>")
            return
        output_dir = args.output or str(Path.cwd())
        rules = load_rules(Path.cwd() / ".deeprules", Path(output_dir) / ".deeprules")
        run_build(
            task=task, api_key=api_key,
            output_dir=output_dir, model=args.model,
            root_is_output_dir=args.output is not None,
            rules=rules, verbose=args.verbose,
            auto_fix=getattr(args, "auto_fix", False),
            project_name=args.name,
        )

    p_build.set_defaults(func=do_build)

    # ── agent ────────────────────────────────────────────────────────────────
    p_agent = sub.add_parser("agent", help="Agente con herramientas (loop estilo Claude Code)")
    p_agent.add_argument("task", nargs="+", metavar="TAREA")
    p_agent.add_argument("-w", "--workspace", default="", metavar="DIR")
    p_agent.add_argument("-y", "--auto", action="store_true",
                         help="No pedir permiso para escribir/ejecutar")
    p_agent.add_argument("--host", default="", metavar="USUARIO@SERVIDOR[:PUERTO]",
                         help="Operá sobre un workspace remoto vía SSH (clave/ssh-agent, "
                              "sin instalar deep ahí). -w es la ruta ABSOLUTA en la remota "
                              "(ej: --host user@servidor -w /home/user/proyecto); si se omite, "
                              "abre un picker interactivo para navegar hasta la carpeta.")

    def do_agent(args):
        from core.rules import load_rules
        from cli.agent_runner import run_agent
        if args.host:
            from core.ssh_workspace import RemoteBrowseCancelled, resolve_remote_workspace
            try:
                ws = resolve_remote_workspace(args.host, args.workspace or None)
            except RemoteBrowseCancelled:
                print("Cancelado.")
                sys.exit(1)
            except Exception as e:
                print(f"❌ {e}")
                sys.exit(1)
        else:
            ws = Path(args.workspace) if args.workspace else Path.cwd()
        run_agent(" ".join(args.task), _require_api_key(), workspace=ws,
                  rules=load_rules(ws / ".deeprules"), auto=args.auto)

    p_agent.set_defaults(func=do_agent)

    # ── autobuild ────────────────────────────────────────────────────────────
    p_auto = sub.add_parser(
        "autobuild",
        help="Relanza `deep agent` en loop hasta agotar un backlog externo "
             "(builds largos sin supervisión, sobrevive a cortes de sesión)")
    p_auto.add_argument("-w", "--workspace", default="", metavar="DIR")
    p_auto.add_argument("--prompt-file", default="prompt-autonomous.md", metavar="ARCHIVO",
                        help="Prompt de la primera iteración, relativo al workspace "
                             "salvo que sea absoluto (default: prompt-autonomous.md)")
    p_auto.add_argument("--resume-file", default="prompt-resume.md", metavar="ARCHIVO",
                        help="Prompt de las iteraciones siguientes (default: prompt-resume.md)")
    p_auto.add_argument("--done-file", default="", metavar="ARCHIVO",
                        help="Archivo a chequear tras cada iteración (ej. un backlog en "
                             "Markdown). Si deja de tener coincidencias de --done-pattern, "
                             "se considera terminado. Sin esto, solo corta por tope de "
                             "iteraciones o por el stop file.")
    p_auto.add_argument("--done-pattern", default=r"^-\s*\[\s*\]", metavar="REGEX",
                        help="Patrón que indica 'trabajo pendiente' en --done-file "
                             "(default: ítem de checklist Markdown sin marcar, '- [ ]')")
    p_auto.add_argument("--max-iterations", type=int, default=100, metavar="N")
    p_auto.add_argument("--sleep-between", type=float, default=15, metavar="SEGUNDOS")
    p_auto.add_argument("--max-stagnant", type=int, default=3, metavar="N",
                        help="Frena si N iteraciones seguidas no producen ningún commit nuevo")
    p_auto.add_argument("--iteration-timeout", type=float, default=3600, metavar="SEGUNDOS",
                        help="Mata una iteración de `deep agent` que no termine en este "
                             "tiempo (0 = sin límite)")

    def do_autobuild(args):
        _require_api_key()
        from cli.autobuild import run_autobuild

        def _resolve(base: Path, value: str) -> Path:
            p = Path(value)
            return p if p.is_absolute() else base / p

        ws = Path(args.workspace).resolve() if args.workspace else Path.cwd()
        result = run_autobuild(
            workspace=ws,
            prompt_file=_resolve(ws, args.prompt_file),
            resume_file=_resolve(ws, args.resume_file),
            done_file=_resolve(ws, args.done_file) if args.done_file else None,
            done_pattern=args.done_pattern,
            max_iterations=args.max_iterations,
            sleep_between=args.sleep_between,
            max_stagnant=args.max_stagnant,
            iteration_timeout=args.iteration_timeout,
            debug=bool(os.environ.get("DEEP_DEBUG")),
        )
        print(f"[autobuild] Terminado — motivo: {result.get('reason')} — "
              f"{result.get('iterations_run', 0)} iteraciones totales.")

    p_auto.set_defaults(func=do_autobuild)

    # ── remote ───────────────────────────────────────────────────────────────
    p_remote = sub.add_parser(
        "remote", help="REPL interactivo sobre un workspace remoto vía SSH")
    p_remote.add_argument("--host", required=True, metavar="USUARIO@SERVIDOR[:PUERTO]")
    p_remote.add_argument("-w", "--workspace", default="", metavar="DIR",
                          help="Ruta ABSOLUTA en la remota; si se omite, abre un picker "
                               "interactivo para navegar hasta la carpeta.")

    def do_remote(args):
        from core.ssh_workspace import RemoteBrowseCancelled, resolve_remote_workspace
        from cli.agent_repl import run as run_repl
        try:
            ws = resolve_remote_workspace(args.host, args.workspace or None)
        except RemoteBrowseCancelled:
            print("Cancelado.")
            sys.exit(1)
        except Exception as e:
            print(f"❌ {e}")
            sys.exit(1)
        run_repl(_require_api_key(), workspace=ws)

    p_remote.set_defaults(func=do_remote)

    # ── ask ──────────────────────────────────────────────────────────────────
    p_ask = sub.add_parser("ask", help="Hace una pregunta sin generar proyecto")
    p_ask.add_argument("question", nargs="+", metavar="PREGUNTA")
    p_ask.add_argument("--model", default="deepseek-chat", metavar="MODELO")

    def do_ask(args):
        from cli.commands import run_ask
        run_ask(" ".join(args.question), _require_api_key(), model=args.model)

    p_ask.set_defaults(func=do_ask)

    # ── update ───────────────────────────────────────────────────────────────
    p_upd = sub.add_parser("update", help="Modifica el proyecto del directorio actual")
    p_upd.add_argument("change", nargs="+", metavar="CAMBIO")
    p_upd.add_argument("--model", default="deepseek-chat", metavar="MODELO")

    def do_update(args):
        from core.rules import load_rules
        from cli.commands import run_update
        run_update(" ".join(args.change), _require_api_key(), Path.cwd(),
                   model=args.model, rules=load_rules(Path.cwd() / ".deeprules"))

    p_upd.set_defaults(func=do_update)

    # ── scan ─────────────────────────────────────────────────────────────────
    p_scan = sub.add_parser("scan", help="Analiza un proyecto existente y arma su contexto")
    p_scan.add_argument("--model", default="deepseek-chat", metavar="MODELO")
    p_scan.add_argument("-r", "--refresh", action="store_true",
                        help="Re-escanea aunque ya exista contexto cacheado")

    def do_scan(args):
        from cli.commands import run_scan
        run_scan(_require_api_key(), Path.cwd(), model=args.model, refresh=args.refresh)

    p_scan.set_defaults(func=do_scan)

    # ── claudejob ──────────────────────────────────────────────────────────────
    p_cj = sub.add_parser(
        "claudejob",
        help="Claude planifica (job.md) y DeepSeek construye/corrige")
    p_cj.add_argument("-j", "--job", metavar="ARCHIVO",
                      help="Ruta del job.md (por defecto .deep/job.md)")
    p_cj.add_argument("-o", "--output", metavar="DIR",
                      help="Directorio del proyecto (por defecto el actual)")
    p_cj.add_argument("--model", default="deepseek-chat", metavar="MODELO")
    p_cj.add_argument("--init", action="store_true",
                      help="Crea la plantilla job.md para que la complete Claude")
    p_cj.add_argument("--force", action="store_true",
                      help="Con --init, regenera el job.md aunque exista (guarda copia .bak)")
    p_cj.add_argument("--review", action="store_true",
                      help="Vuelca estado + formato para que Claude revise")
    p_cj.add_argument("--fix", metavar="REVIEW", dest="fix_file",
                      help="Aplica las correcciones de Claude desde un review.md")
    p_cj.add_argument("-f", "--auto-fix", action="store_true",
                      help="Corrige automáticamente los módulos que fallen el build")

    def do_claudejob(args):
        from core.rules import load_rules
        from cli.commands import run_claudejob
        project_dir = Path(args.output) if args.output else Path.cwd()
        run_claudejob(
            api_key=_require_api_key(), project_dir=project_dir,
            job_file=args.job, model=args.model,
            rules=load_rules(Path.cwd() / ".deeprules", project_dir / ".deeprules"),
            init=args.init, review=args.review, fix_file=args.fix_file,
            auto_fix=getattr(args, "auto_fix", False), force=args.force,
        )

    p_cj.set_defaults(func=do_claudejob)

    # ── doctor ───────────────────────────────────────────────────────────────
    p_doc = sub.add_parser("doctor", help="Verifica que todo esté configurado correctamente")

    def do_doctor(args):
        from cli.commands import run_doctor
        run_doctor()

    p_doc.set_defaults(func=do_doctor)

    # ── serve ────────────────────────────────────────────────────────────────
    p_srv = sub.add_parser("serve", help="Inicia el servidor web para usar deep desde el celular")
    p_srv.add_argument("--port", type=int, default=8000, metavar="PUERTO")
    p_srv.add_argument("--https", action="store_true", dest="use_https",
                       help="Activa HTTPS para instalar la app en el celular")
    p_srv.add_argument("--tunnel", action="store_true", dest="use_tunnel",
                       help="Crea un túnel HTTPS público (recomendado para instalar como PWA)")

    def do_serve(args):
        from cli.commands import run_serve
        run_serve(port=args.port, use_https=args.use_https, use_tunnel=args.use_tunnel)

    p_srv.set_defaults(func=do_serve)

    # ── upgrade ──────────────────────────────────────────────────────────────
    p_upg = sub.add_parser("upgrade", help="Actualiza deep CLI desde GitHub")

    def do_upgrade(args):
        from cli.commands import run_upgrade
        run_upgrade()

    p_upg.set_defaults(func=do_upgrade)

    # ── show ─────────────────────────────────────────────────────────────────
    p_show = sub.add_parser("show", help="Muestra el contexto del proyecto actual")

    def do_show(args):
        from cli.commands import run_show
        run_show(Path.cwd())

    p_show.set_defaults(func=do_show)

    # ── config ───────────────────────────────────────────────────────────────
    p_cfg = sub.add_parser("config", help="Muestra o modifica la configuración")
    p_cfg_sub = p_cfg.add_subparsers(dest="config_cmd", metavar="opción")
    p_cfg_sub.add_parser("set-key", help="Guarda una nueva API key")
    p_cfg_sub.add_parser("set-lang", help="Cambia el idioma de las respuestas")

    def do_config(args):
        from core.config import prompt_and_save, prompt_and_save_language, show_config
        cfg_cmd = getattr(args, "config_cmd", None)
        if cfg_cmd == "set-key":
            prompt_and_save()
        elif cfg_cmd == "set-lang":
            prompt_and_save_language()
        else:
            show_config()

    p_cfg.set_defaults(func=do_config)

    # ── browser ──────────────────────────────────────────────────────────────
    p_browser = sub.add_parser(
        "browser", help="Backend alternativo de navegador (extensión Chrome real)")
    p_browser_sub = p_browser.add_subparsers(dest="browser_cmd", metavar="opción")
    p_install = p_browser_sub.add_parser(
        "install-extension",
        help="Registra el native host y muestra cómo cargar la extensión")
    p_install.add_argument("--port", type=int, default=8000, metavar="PUERTO")

    def do_browser(args):
        from cli.commands import run_browser_install_extension
        if getattr(args, "browser_cmd", None) == "install-extension":
            run_browser_install_extension(port=args.port)
        else:
            p_browser.print_help()

    p_browser.set_defaults(func=do_browser)

    args = parser.parse_args(argv)
    args.func(args)


def main():
    argv = sys.argv[1:]

    from core.updater import start as _start_update_check
    _update = _start_update_check()

    if "--debug" in argv:
        argv = [a for a in argv if a != "--debug"]
        os.environ["DEEP_DEBUG"] = "1"
        import core.debug as _dbg
        _dbg.init()
        _dbg.log("INIT", f"deep  pid={os.getpid()}  args={sys.argv[1:]}")

    if argv:
        _legacy(argv)
        notice = _update.get(timeout=0.3)
        if notice:
            print(notice)
    else:
        # REPL agente-first (v2). El clásico queda en `cli.repl` como fallback.
        if os.getenv("DEEP_CLASSIC_REPL"):
            from cli.repl import run
        else:
            from cli.agent_repl import run
        run(_require_api_key(), update_notice=_update.get(timeout=1.5))


if __name__ == "__main__":
    main()
