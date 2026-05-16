"""
Comandos de alto nivel — usan core para la lógica y cli.display para mostrar resultados.
Son la única interfaz que tanto el REPL como el modo legacy necesitan importar.
"""
import json
from pathlib import Path
from typing import List, Optional

import core.balance as bal
from core.system import DeepSeekLearningSystem
from core.memory import _EXPERIENCES_FILE
from cli.display import show_balance, show_files, show_evaluation, show_history
from cli.spinner import Spinner


def run_build(task: str, api_key: str, output_dir: str,
              model: str = "deepseek-chat", root_is_output_dir: bool = False,
              rules: List[str] = None, verbose: bool = False,
              auto_fix: bool = False) -> Optional[dict]:

    print(f"\n🚀 Generando: {task}")
    print(f"📁 Destino:   {Path(output_dir).resolve()}")
    if rules:
        print(f"📏 Reglas:    {len(rules)} cargadas desde .deeprules")

    before = show_balance(api_key, label="Crédito antes del build")

    spinner = Spinner() if not verbose else None
    buffered_files = []

    def on_progress(msg):
        if spinner:
            spinner.notify(msg)
        else:
            print(f"  ▸ {msg}")

    def on_file(path):
        if spinner:
            buffered_files.append(path)
        else:
            print(f"   💾 {path}")

    system = DeepSeekLearningSystem(
        api_key, output_dir=output_dir, model=model,
        root_is_output_dir=root_is_output_dir,
        rules=rules or [], on_progress=on_progress, on_file=on_file,
    )

    if spinner:
        print()
        spinner.start()

    try:
        result = system.execute_and_learn(task)
    except KeyboardInterrupt:
        if spinner:
            spinner.stop()
        print("\n⚠️  Interrumpido.")
        return None
    except Exception as e:
        if spinner:
            spinner.stop()
        print(f"\n❌ Error: {e}")
        return None

    if spinner:
        spinner.stop()

    for path in buffered_files:
        try:
            display = "~/" + str(Path(path).relative_to(Path.home()))
        except ValueError:
            display = path
        print(f"   💾 {display}")

    tokens = system.client.get_stats().get("total_tokens_used", 0)
    show_balance(api_key, label="Crédito después del build", before=before, tokens=tokens)
    show_files(result.get("files_written", []))
    show_evaluation(result)

    if not result.get("success"):
        if auto_fix:
            result = _do_fix(system, task, result, verbose)
        else:
            try:
                answer = input("\n¿Corregir automáticamente? [s/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer in ("s", "si", "sí", "y", "yes"):
                result = _do_fix(system, task, result, verbose)

    return result


def run_fix_current(api_key: str, project_dir: Path, rules: List[str] = None) -> Optional[dict]:
    """Corrige el proyecto en project_dir usando su contexto guardado."""
    ctx_file = project_dir / ".deep" / "context.json"
    eval_file = project_dir / ".deep" / "evaluation.json"

    try:
        ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
    except Exception:
        print("❌ No se encontró contexto de proyecto en este directorio.")
        return None

    evaluation = {}
    if eval_file.exists():
        try:
            evaluation = json.loads(eval_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    task = ctx.get("task", "")
    model = ctx.get("model", "deepseek-chat")

    # Reconstruir result fake con lo que tenemos en disco
    code_files = [
        str(f) for f in project_dir.rglob("*")
        if f.is_file() and ".deep" not in f.parts and not f.name.startswith(".")
    ]
    fake_result = {
        "files_written": code_files,
        "outcome": json.dumps(evaluation),
        "plan": ctx.get("plan", ""),
        "success": evaluation.get("success", False),
    }

    spinner = Spinner()
    buffered_files = []

    def on_progress(msg):
        spinner.notify(msg)

    def on_file(path):
        buffered_files.append(path)

    system = DeepSeekLearningSystem(
        api_key, output_dir=str(project_dir), model=model,
        root_is_output_dir=True, rules=rules or [],
        on_progress=on_progress, on_file=on_file,
    )

    print()
    spinner.start()
    try:
        fix_result = system.review_and_fix(task, fake_result)
    except Exception as e:
        spinner.stop()
        print(f"\n❌ Error: {e}")
        return None
    spinner.stop()

    for path in buffered_files:
        try:
            display = "~/" + str(Path(path).relative_to(Path.home()))
        except ValueError:
            display = path
        print(f"   💾 {display}")

    fixed = fix_result.get("files_fixed", [])
    if fixed:
        print(f"\n🔧 {len(fixed)} archivo(s) corregido(s).")
    if fix_result.get("success"):
        print("✅ Corrección exitosa.")
    else:
        print("⚠️  Puede necesitar ajustes adicionales.")
    return fix_result


def run_balance(api_key: str):
    show_balance(api_key)


def run_history():
    experiences = []
    if _EXPERIENCES_FILE.exists():
        try:
            experiences = json.loads(
                _EXPERIENCES_FILE.read_text(encoding="utf-8")
            ).get("experiences", [])
        except Exception:
            pass
    show_history(experiences)


# ── privado ───────────────────────────────────────────────────────────────────

def _do_fix(system: DeepSeekLearningSystem, task: str, result: dict,
            verbose: bool) -> dict:
    spinner = Spinner() if not verbose else None
    buffered_files = []

    if spinner:
        orig_on_file = system._on_file
        def on_file_capture(path):
            buffered_files.append(path)
        system._on_file = on_file_capture
        print()
        spinner.start()
        orig_progress = system._on_progress
        system._on_progress = spinner.notify

    try:
        fix_result = system.review_and_fix(task, result)
    except Exception as e:
        if spinner:
            spinner.stop()
        print(f"\n❌ Error en corrección: {e}")
        return result
    finally:
        if spinner:
            spinner.stop()
            if "orig_on_file" in dir():
                system._on_file = orig_on_file
            if "orig_progress" in dir():
                system._on_progress = orig_progress

    for path in buffered_files:
        try:
            display = "~/" + str(Path(path).relative_to(Path.home()))
        except ValueError:
            display = path
        print(f"   💾 {display}")

    fixed = fix_result.get("files_fixed", [])
    if fixed:
        print(f"\n🔧 {len(fixed)} archivo(s) corregido(s).")
    if fix_result.get("success"):
        print("✅ Corrección exitosa.")
    else:
        print("⚠️  Algunos problemas pueden requerir revisión manual.")
    return fix_result
