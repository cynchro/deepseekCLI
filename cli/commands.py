"""
Comandos de alto nivel — usan core para la lógica y cli.display para mostrar resultados.
Son la única interfaz que tanto el REPL como el modo legacy necesitan importar.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
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
              auto_fix: bool = False, project_name: str = "") -> Optional[dict]:

    if not project_name and not root_is_output_dir:
        from core.writer import FileWriter
        suggestion = FileWriter._auto_name(task)
        try:
            answer = input(f"\n📁 Nombre del proyecto [{suggestion}]: ").strip()
            project_name = answer if answer else suggestion
        except (EOFError, KeyboardInterrupt):
            project_name = suggestion

    print(f"\n🚀 Generando: {task}")
    print(f"📁 Proyecto:  {project_name}")
    print(f"📂 Destino:   {Path(output_dir).resolve()}")
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
        project_name=project_name,
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


def run_ask(question: str, api_key: str, model: str = "deepseek-chat",
            history: list = None, system_prompt: str = None,
            temperature: float = 0.7, max_tokens: int = 3000) -> list:
    """Envía una pregunta manteniendo el historial de la conversación.
    Devuelve el historial actualizado para pasarlo en la próxima llamada."""
    from core.client import DeepSeekClient
    client = DeepSeekClient(api_key, model=model)

    default_system = system_prompt or (
        "Sos un asistente experto en programación y tecnología. "
        "Respondé en el mismo idioma de la pregunta."
    )
    messages = list(history) if history else [
        {"role": "system", "content": default_system}
    ]
    messages.append({"role": "user", "content": question})

    messages, compacted = client.compact_history(messages)
    if compacted:
        print("\n⚡ Compactando conversación…")

    spinner = Spinner()
    print()
    spinner.start()

    content = None
    try:
        raw = client.chat_with_context(messages, temperature=temperature, max_tokens=max_tokens)
        spinner.stop()
        content = raw["choices"][0]["message"]["content"]
    except Exception:
        spinner.stop()
        result = client.chat(
            question,
            system_prompt=messages[0]["content"],
            temperature=temperature, max_tokens=max_tokens,
        )
        if result.get("success"):
            content = result["content"]

    print()
    if content:
        print(content)
        messages.append({"role": "assistant", "content": content})
    else:
        print("❌ No se obtuvo respuesta.")
    print()
    return messages


def run_update(change: str, api_key: str, project_dir: Path,
               model: str = "deepseek-chat", rules: List[str] = None) -> None:
    ctx_file = project_dir / ".deep" / "context.json"
    if not ctx_file.exists():
        print("❌ No hay proyecto en este directorio. Usá 'build' primero.")
        return
    try:
        ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
    except Exception:
        print("❌ No se pudo leer el contexto del proyecto.")
        return

    task = ctx.get("task", "proyecto")
    original_model = ctx.get("model", model)
    print(f"\n🔧 Aplicando cambio: {change}")
    print(f"📁 Proyecto: {project_dir.resolve()}")

    spinner = Spinner()
    updated_files = []

    system = DeepSeekLearningSystem(
        api_key, output_dir=str(project_dir), model=original_model,
        root_is_output_dir=True, rules=rules or [],
        on_progress=spinner.notify, on_file=updated_files.append,
    )
    print()
    spinner.start()
    try:
        result = system.execute_update(change, task)
    except KeyboardInterrupt:
        spinner.stop()
        print("\n⚠️  Interrumpido.")
        return
    except Exception as e:
        spinner.stop()
        print(f"\n❌ Error: {e}")
        return
    spinner.stop()

    for path in updated_files:
        try:
            display = "~/" + str(Path(path).relative_to(Path.home()))
        except ValueError:
            display = path
        print(f"   ✏️  {display}")

    n = len(result.get("files_updated", []))
    if result.get("success"):
        print(f"\n✅ {n} archivo(s) actualizado(s).")
    else:
        print(f"\n❌ Error: {result.get('error', 'desconocido')}")


def run_doctor() -> None:
    print("\n  deep doctor — diagnóstico\n")

    is_windows = platform.system() == "Windows"

    major, minor = sys.version_info.major, sys.version_info.minor
    ok = major >= 3 and minor >= 9
    print(f"  {'✅' if ok else '❌'} Python {major}.{minor}")

    from core.config import load_api_key as _load_key
    key = os.environ.get("DEEPSEEK_API_KEY") or _load_key()
    print(f"  {'✅' if key else '❌'} API key {'configurada' if key else 'no encontrada  →  deep config set-key'}")

    if key:
        try:
            data = bal.fetch(key)
            if data and "error" not in str(data).lower():
                print("  ✅ Conexión con DeepSeek API OK")
            else:
                print("  ❌ API key inválida o sin crédito")
        except Exception as e:
            print(f"  ❌ Sin conexión: {e}")

    try:
        import requests
        print(f"  ✅ requests {requests.__version__}")
    except ImportError:
        print("  ⚠️  requests no instalado (fallback a curl)")

    try:
        import prompt_toolkit
        print(f"  ✅ prompt_toolkit {prompt_toolkit.__version__} (REPL mejorado activo)")
    except ImportError:
        print("  ⚠️  prompt_toolkit no instalado (REPL básico)  →  pip install prompt_toolkit")

    if is_windows:
        deep_path = shutil.which("deep")
        print(f"  {'✅' if deep_path else '⚠️ '} Comando 'deep' {'en ' + deep_path if deep_path else 'no encontrado en PATH'}")
        venv = Path.home() / ".local" / "share" / "deepseekcli"
        venv_ok = (venv / "Scripts" / "pip.exe").exists()
    else:
        local_bin = str(Path.home() / ".local" / "bin")
        in_path = local_bin in os.environ.get("PATH", "").split(":")
        print(f"  {'✅' if in_path else '⚠️ '} ~/.local/bin {'en PATH' if in_path else 'no está en PATH'}")
        venv = Path.home() / ".local" / "share" / "deepseekcli"
        venv_ok = (venv / "bin" / "pip").exists()

    print(f"  {'✅' if venv_ok else '⚠️ '} venv {'en' if venv_ok else 'no encontrado en'} {venv}")

    print()


def run_serve(port: int = 8000, use_https: bool = False) -> None:
    import socket
    import tempfile
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    try:
        import pwa as _pwa_pkg
        pwa_dir = Path(_pwa_pkg.__file__).parent
    except ImportError:
        pwa_dir = Path(__file__).parent.parent / "pwa"

    if not pwa_dir.exists() or not (pwa_dir / "main.py").exists():
        print("❌ No se encontró el servidor web. Actualizá con: deep upgrade")
        return

    # IPs disponibles
    ts_ip = None
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True)
        if r.returncode == 0:
            ts_ip = r.stdout.strip()
    except FileNotFoundError:
        pass

    local_ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # ── HTTPS ─────────────────────────────────────────────────────────────────
    ssl_args = []
    env = os.environ.copy()

    if use_https:
        try:
            import trustme
        except ImportError:
            print("❌ Para HTTPS instalá: pip install trustme")
            return

        tmpdir = tempfile.mkdtemp(prefix="deep-ssl-")
        ca = trustme.CA()

        hostnames = ["localhost", "127.0.0.1"]
        if ts_ip:
            hostnames.append(ts_ip)
        if local_ip:
            hostnames.append(local_ip)

        server_cert = ca.issue_cert(*hostnames)
        keyfile  = os.path.join(tmpdir, "server.key")
        certfile = os.path.join(tmpdir, "server.crt")
        ca_path  = os.path.join(tmpdir, "ca.crt")

        server_cert.private_key_pem.write_to_path(keyfile)
        server_cert.cert_chain_pems[0].write_to_path(certfile)
        ca.cert_pem.write_to_path(ca_path)

        ssl_args = ["--ssl-keyfile", keyfile, "--ssl-certfile", certfile]
        protocol = "https"

        # Mini servidor HTTP en puerto+1 solo para descargar el certificado CA
        ca_port = port + 1

        class _CACertHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = Path(ca_path).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-x509-ca-cert")
                self.send_header("Content-Disposition", "attachment; filename=deep-ca.crt")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass

        ca_server = HTTPServer(("0.0.0.0", ca_port), _CACertHandler)
        threading.Thread(target=ca_server.serve_forever, daemon=True).start()

        display_ip = ts_ip or local_ip or "localhost"
        print(f"\n  🔐 HTTPS activado\n")
        print(f"  Paso 1 — Instalá el certificado CA en tu celular (una sola vez):")
        print(f"     http://{display_ip}:{ca_port}    ← abrí esta URL en el celular")
        print(f"     Android : Ajustes → Seguridad → Instalar certificado")
        print(f"     iOS     : Ajustes → General → VPN y administración → Confiar\n")
        print(f"  Paso 2 — Abrí la app y tocá ⬇ para instalarla:\n")
    else:
        protocol = "http"

    # ── URLs ──────────────────────────────────────────────────────────────────
    print(f"  🚀 Servidor deep iniciando en puerto {port}\n")
    if ts_ip:
        print(f"  📱 Desde tu celular (Tailscale):")
        print(f"     {protocol}://{ts_ip}:{port}\n")
    if local_ip:
        print(f"  🖥️  Red local:")
        print(f"     {protocol}://{local_ip}:{port}\n")
    if not use_https:
        print(f"  💡 Para instalar como app: deep serve --https\n")
    print("  Ctrl+C para detener\n")

    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "main:app",
             "--host", "0.0.0.0", "--port", str(port)] + ssl_args,
            cwd=str(pwa_dir),
            env=env,
        )
    except KeyboardInterrupt:
        print("\n  Servidor detenido.")
    except Exception as e:
        print(f"❌ Error al iniciar el servidor: {e}")
        print("   Instalá uvicorn con: pip install uvicorn")


def run_upgrade() -> None:
    venv_base = Path.home() / ".local" / "share" / "deepseekcli"
    if platform.system() == "Windows":
        venv_pip = venv_base / "Scripts" / "pip.exe"
        reinstall_hint = "   Reinstalá con: .\\install.ps1"
    else:
        venv_pip = venv_base / "bin" / "pip"
        reinstall_hint = "   Reinstalá con: bash <(curl -fsSL https://raw.githubusercontent.com/cynchro/deepseekCLI/main/install.sh)"

    if not venv_pip.exists():
        print(f"❌ Instalación no encontrada en {venv_base}")
        print(reinstall_hint)
        return
    print("🔄 Actualizando deep CLI desde GitHub...")
    result = subprocess.run(
        [str(venv_pip), "install", "--force-reinstall", "--no-cache-dir",
         "git+https://github.com/cynchro/deepseekCLI.git"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("✅ deep actualizado. Abrí una nueva terminal para usar la versión nueva.")
    else:
        print(f"❌ Error al actualizar:\n{result.stderr[:400]}")


def run_show(project_dir: Path) -> None:
    ctx_file = project_dir / ".deep" / "context.json"
    eval_file = project_dir / ".deep" / "evaluation.json"

    if not ctx_file.exists():
        print("❌ No hay proyecto en este directorio.")
        print("   Generá uno con: deep build \"descripción\"")
        return
    try:
        ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
    except Exception:
        print("❌ No se pudo leer el contexto del proyecto.")
        return

    print(f"\n  📁 {project_dir.resolve()}")
    print(f"  📋 Tarea  : {ctx.get('task', '—')}")
    print(f"  🤖 Modelo : {ctx.get('model', '—')}")
    ts = ctx.get("timestamp", "")
    if ts:
        print(f"  🕐 Creado : {ts[:16].replace('T', ' ')}")
    if ctx.get("last_update"):
        print(f"  🔧 Update : {ctx['last_update']}")

    plan = ctx.get("plan", "")
    if plan:
        print("\n  📐 Plan:\n")
        for line in plan[:600].split("\n"):
            if line.strip():
                print(f"     {line}")

    files = sorted(
        f for f in project_dir.rglob("*")
        if f.is_file() and ".deep" not in f.parts and not f.name.startswith(".")
    )
    print(f"\n  📄 Archivos ({len(files)}):")
    for f in files:
        print(f"     {f.relative_to(project_dir)}")

    if eval_file.exists():
        try:
            ev = json.loads(eval_file.read_text(encoding="utf-8"))
            success = ev.get("success", False)
            score = ev.get("overall_score", "?")
            print(f"\n  {'✅' if success else '❌'} Evaluación: score {score}/10")
            for issue in ev.get("issues", [])[:3]:
                print(f"     ⚠️  {issue}")
        except Exception:
            pass
    print()


def run_skill(skill: dict, question: str, api_key: str, history: list = None) -> list:
    """Ejecuta un skill: run_ask con el system_prompt y parámetros del skill."""
    return run_ask(
        question, api_key,
        history=history,
        system_prompt=skill["system_prompt"],
        temperature=skill.get("temperature", 0.7),
        max_tokens=skill.get("max_tokens", 3000),
    )


# ── privado ───────────────────────────────────────────────────────────────────

def _do_fix(system: DeepSeekLearningSystem, task: str, result: dict,
            verbose: bool) -> dict:
    spinner = Spinner() if not verbose else None
    buffered_files = []
    orig_on_file = None
    orig_progress = None

    if spinner:
        orig_on_file = system._on_file
        orig_progress = system._on_progress
        system._on_file = buffered_files.append
        system._on_progress = spinner.notify
        print()
        spinner.start()

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
            if orig_on_file is not None:
                system._on_file = orig_on_file
            if orig_progress is not None:
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
