"""Reanudación autónoma ENTRE procesos (`deep autobuild`).

Complementa el auto-resume de core/agent_loop.py (AgentLoop.max_auto_resume):
ese es intra-proceso e intra-turno, acotado a un tope chico (3) para cuando
se agota el presupuesto de pasos de UN turno. Este módulo es un nivel por
encima: relanza `deep agent` como PROCESO NUEVO cada vez que termina (por
cualquier motivo -- éxito, límite de pasos agotado tras sus propios
auto-resumes, crash, lo que sea), hasta que una condición externa de
"terminado" se cumpla. Pensado para builds de horas/días que tienen que
sobrevivir a que una sesión de `deep agent` se corte.

`deep agent` hoy sale casi siempre con returncode 0 pase lo que pase (ver
do_agent/run_turn en deep.py/cli/agent_runner.py -- no hacen sys.exit según
el resultado), así que el criterio de "listo" NO se basa en el exit code:
se basa en `done_file` (típicamente un backlog en Markdown) dejando de tener
coincidencias de `done_pattern`, en el tope de iteraciones, o en un archivo
de stop que el usuario puede crear desde otra terminal.
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

STATE_FILENAME = "autobuild_state.json"
STOP_FILENAME = "autobuild.stop"
LOG_DIRNAME = "autobuild_logs"

DEFAULT_DONE_PATTERN = r"^-\s*\[\s*\]"  # ítem de checklist Markdown sin marcar


def _deep_dir(workspace: Path) -> Path:
    return workspace / ".deep"


def state_path(workspace: Path) -> Path:
    return _deep_dir(workspace) / STATE_FILENAME


def stop_path(workspace: Path) -> Path:
    return _deep_dir(workspace) / STOP_FILENAME


def log_dir(workspace: Path) -> Path:
    return _deep_dir(workspace) / LOG_DIRNAME


def load_state(workspace: Path) -> dict:
    p = state_path(workspace)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("iterations_run", 0)
                data.setdefault("stagnant_count", 0)
                data.setdefault("last_commit", "")
                return data
        except Exception:
            pass
    return {"iterations_run": 0, "stagnant_count": 0, "last_commit": ""}


def save_state(workspace: Path, data: dict) -> None:
    p = state_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_done(done_file: Path | None, done_pattern: str) -> bool:
    """True si ya no queda trabajo pendiente. Sin done_file configurado,
    esta condición nunca corta el loop por sí sola (manda max_iterations o
    el stop file). Si done_file todavía no existe, se asume que falta
    trabajo -- no se considera "listo" por ausencia del archivo."""
    if done_file is None:
        return False
    if not done_file.exists():
        return False
    text = done_file.read_text(encoding="utf-8")
    return re.search(done_pattern, text, re.MULTILINE) is None


def ensure_git_repo(workspace: Path) -> None:
    if not (workspace / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(workspace), check=True)


def git_head(workspace: Path) -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(workspace),
                            capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def commit_pending_changes(workspace: Path, message: str) -> bool:
    """Red de seguridad: comitea lo que haya quedado sin comitear tras una
    iteración, por si el agente no lo hizo solo. Devuelve True si comiteó
    algo."""
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(workspace),
                             capture_output=True, text=True)
    if not status.stdout.strip():
        return False
    subprocess.run(["git", "add", "-A"], cwd=str(workspace), check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(workspace), check=False)
    return True


def run_one_iteration(workspace: Path, prompt_text: str, debug: bool,
                       log_file: Path, timeout: float | None) -> int:
    """Lanza `python -m deep [--debug] agent "<prompt_text>" -y -w <workspace>`
    como PROCESO NUEVO (subprocess.Popen), esperando a que termine. cwd es la
    raíz de este repo (mismo patrón que cli/daemon_client.py:ensure_daemon)
    para que `python -m deep` resuelva el módulo sin depender de que esté
    pip-instalado. Devuelve el returncode (ver docstring del módulo: no es
    confiable para decidir éxito/fracaso, solo informativo en el log)."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "deep"]
    if debug:
        cmd.append("--debug")
    cmd += ["agent", prompt_text, "-y", "-w", str(workspace)]
    with open(log_file, "a", encoding="utf-8") as log:
        log.write(f"\n=== deep autobuild — {datetime.now().isoformat()} ===\n")
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                 cwd=str(_REPO_ROOT))
        try:
            return proc.wait(timeout=timeout if timeout and timeout > 0 else None)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            log.write(f"\n[autobuild] iteración matada por timeout ({timeout}s)\n")
            return -1


def run_autobuild(workspace: Path, prompt_file: Path, resume_file: Path,
                   done_file: Path | None, done_pattern: str = DEFAULT_DONE_PATTERN,
                   max_iterations: int = 100, sleep_between: float = 15,
                   max_stagnant: int = 3, iteration_timeout: float | None = 3600,
                   debug: bool = False, on_event=print) -> dict:
    """Orquesta iteraciones de `deep agent` hasta: (a) done_file sin más
    coincidencias de done_pattern, (b) tope de max_iterations, (c) aparece
    el stop file (.deep/autobuild.stop, borrable con `touch` desde otra
    terminal), o (d) max_stagnant iteraciones seguidas sin ningún commit
    nuevo (señal de agente trabado -- corta para no quemar cuota al pedo).

    El estado (cuántas iteraciones van corridas) persiste en
    .deep/autobuild_state.json, así que si este mismo proceso se corta y se
    vuelve a invocar `deep autobuild` con el mismo workspace, retoma sin
    repetir la iteración 1 (usa resume_file en vez de prompt_file)."""
    ensure_git_repo(workspace)
    state = load_state(workspace)

    while True:
        sp = stop_path(workspace)
        if sp.exists():
            sp.unlink()
            on_event(f"[autobuild] Se encontró {sp}. Frenando de forma prolija.")
            return {"reason": "stopped", **state}

        if is_done(done_file, done_pattern):
            on_event("[autobuild] done_file sin más ítems pendientes. Construcción completa.")
            return {"reason": "done", **state}

        if state["iterations_run"] >= max_iterations:
            on_event(f"[autobuild] Se llegó al tope de {max_iterations} iteraciones.")
            return {"reason": "max_iterations", **state}

        active_prompt = prompt_file if state["iterations_run"] == 0 else resume_file
        if not active_prompt.exists():
            raise FileNotFoundError(f"No se encontró el prompt: {active_prompt}")
        prompt_text = active_prompt.read_text(encoding="utf-8")

        state["iterations_run"] += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile = log_dir(workspace) / f"run_{state['iterations_run']:04d}_{timestamp}.log"

        on_event(f"[autobuild] Iteración {state['iterations_run']} — usando "
                 f"{active_prompt.name} — {datetime.now().isoformat()}")

        before = git_head(workspace)
        returncode = run_one_iteration(workspace, prompt_text, debug, logfile, iteration_timeout)
        on_event(f"[autobuild] Sesión terminó (returncode={returncode}) — log: {logfile}")

        commit_pending_changes(workspace, f"autobuild checkpoint — iteración {state['iterations_run']}")
        after = git_head(workspace)

        state["stagnant_count"] = state["stagnant_count"] + 1 if (after and after == before) else 0
        state["last_commit"] = after
        save_state(workspace, state)

        if state["stagnant_count"] >= max_stagnant:
            on_event(f"[autobuild] {max_stagnant} iteraciones seguidas sin cambios en git — "
                     f"probable estancamiento. Frenando para no desperdiciar cuota. Revisá "
                     f"{logfile} antes de reintentar.")
            return {"reason": "stagnant", **state}

        on_event(f"[autobuild] Esperando {sleep_between}s antes de la próxima iteración...")
        time.sleep(sleep_between)
