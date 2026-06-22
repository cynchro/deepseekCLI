"""Tool de shell: run_command (subprocess dentro del workspace, con permiso)."""
import subprocess

from core.tools.base import ToolContext, truncate

_MAX_TIMEOUT = 300


def run_command(ctx: ToolContext, command: str, timeout: int = 60) -> str:
    if not ctx.confirm(f"ejecutar: {command}"):
        return "CANCELADO por el usuario"
    ctx.on_event("shell", {"command": command})
    try:
        r = subprocess.run(
            command, shell=True, cwd=str(ctx.workspace),
            capture_output=True, text=True,
            timeout=min(int(timeout), _MAX_TIMEOUT),
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: timeout tras {timeout}s"
    except Exception as e:
        return f"ERROR ejecutando: {e}"
    parts = [f"exit={r.returncode}"]
    if r.stdout:
        parts.append(r.stdout.rstrip())
    if r.stderr:
        parts.append("[stderr]\n" + r.stderr.rstrip())
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
