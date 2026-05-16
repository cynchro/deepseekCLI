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
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


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
    p_build.add_argument("task", nargs="+", metavar="TAREA")
    p_build.add_argument("-o", "--output", metavar="DIR")
    p_build.add_argument("--model", default="deepseek-chat", metavar="MODELO")
    p_build.add_argument("-f", "--auto-fix", action="store_true",
                         help="Corregir automáticamente si la evaluación falla")
    p_build.add_argument("-v", "--verbose", action="store_true")

    def do_build(args):
        api_key = _require_api_key()
        output_dir = args.output or str(Path.cwd())
        rules = load_rules(Path.cwd() / ".deeprules", Path(output_dir) / ".deeprules")
        run_build(
            task=" ".join(args.task), api_key=api_key,
            output_dir=output_dir, model=args.model,
            root_is_output_dir=args.output is not None,
            rules=rules, verbose=args.verbose,
            auto_fix=getattr(args, "auto_fix", False),
        )

    p_build.set_defaults(func=do_build)

    # ── config ───────────────────────────────────────────────────────────────
    p_cfg = sub.add_parser("config", help="Muestra o modifica la configuración")
    p_cfg_sub = p_cfg.add_subparsers(dest="config_cmd", metavar="opción")
    p_cfg_sub.add_parser("set-key", help="Guarda una nueva API key")

    def do_config(args):
        from core.config import prompt_and_save, show_config
        if getattr(args, "config_cmd", None) == "set-key":
            prompt_and_save()
        else:
            show_config()

    p_cfg.set_defaults(func=do_config)

    args = parser.parse_args(argv)
    args.func(args)


def main():
    argv = sys.argv[1:]
    if argv:
        _legacy(argv)
    else:
        from cli.repl import run
        run(_require_api_key())


if __name__ == "__main__":
    main()
