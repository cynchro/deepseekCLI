"""Tool de shell: run_command (subprocess local o exec remoto, con permiso)."""
import subprocess
import time

from core.tools.base import ToolContext, truncate

_MAX_TIMEOUT = 300
_HEARTBEAT_INTERVAL = 15  # avisa cada tanto que el comando sigue corriendo


def execute(workspace, command: str, timeout: int, on_wait=None):
    """Corre `command` sobre `workspace`, local o remoto según su tipo (usado
    tanto por la tool run_command como por AgentLoop._auto_verify, para no
    duplicar la lógica de heartbeat/timeout en dos lugares).

    Devuelve (exit_code, stdout, stderr). Si exit_code es None, el comando ni
    siquiera llegó a correr o se cortó por timeout — en ese caso `stderr` ya
    trae el mensaje de error completo, listo para mostrar tal cual."""
    cap = min(int(timeout), _MAX_TIMEOUT)
    if hasattr(workspace, "run_command"):
        # SSHPath (u otro backend remoto): la ejecución vive en el objeto workspace.
        return workspace.run_command(command, timeout=cap, on_wait=on_wait)
    return _run_local(str(workspace), command, cap, on_wait)


def _run_local(cwd: str, command: str, cap: int, on_wait=None):
    t0 = time.time()
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except Exception as e:
        return None, "", f"ERROR ejecutando: {e}"

    while True:
        try:
            stdout, stderr = proc.communicate(timeout=_HEARTBEAT_INTERVAL)
            break
        except subprocess.TimeoutExpired:
            elapsed = int(time.time() - t0)
            if elapsed >= cap:
                proc.kill()
                # Si el proceso dejó hijos que retienen el pipe (típico en Windows),
                # no nos quedamos colgados esperando a que cierren: acotamos también
                # esta lectura final.
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                return None, "", f"ERROR: timeout tras {cap}s (proceso terminado a la fuerza)"
            if on_wait:
                on_wait(elapsed)
    return proc.returncode, stdout, stderr


def run_command(ctx: ToolContext, command: str, timeout: int = 60) -> str:
    if not ctx.confirm(f"ejecutar: {command}"):
        return "CANCELADO por el usuario"
    ctx.on_event("shell", {"command": command})

    def on_wait(elapsed):
        ctx.on_event("shell_wait", {"command": command, "elapsed": elapsed})

    exit_code, stdout, stderr = execute(ctx.workspace, command, timeout, on_wait)
    if exit_code is None:
        return stderr

    parts = [f"exit={exit_code}"]
    if stdout:
        parts.append(stdout.rstrip())
    if stderr:
        parts.append("[stderr]\n" + stderr.rstrip())
    return truncate("\n".join(parts))


TOOLS = {
    "run_command": {
        "impl": run_command,
        "schema": {
            "name": "run_command",
            "description": "Ejecuta un comando de shell dentro del workspace y devuelve exit code + salida. Usalo para correr tests, instalar deps, git, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando de shell a ejecutar"},
                    "timeout": {"type": "integer", "description": "Timeout en segundos (máx 300)"},
                },
                "required": ["command"],
            },
        },
    },
}
