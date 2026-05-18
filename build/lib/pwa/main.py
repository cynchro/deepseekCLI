import contextlib
import io
import os
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.client import DeepSeekClient
from core.rules import load_rules
import core.balance as bal

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
APP_PASSWORD     = os.environ.get("DEEP_APP_PASSWORD", "")
BUILD_DIR        = Path(os.environ.get("DEEP_BUILD_DIR", Path.home() / "deep-projects"))

SYSTEM_PROMPT = (
    "Sos un asistente experto en programación y tecnología. "
    "Respondé en el mismo idioma de la pregunta. "
    "Usá markdown para formatear las respuestas cuando sea apropiado."
)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

sessions: dict = {}


def _check_auth(authorization: str | None):
    if APP_PASSWORD and authorization != f"Bearer {APP_PASSWORD}":
        raise HTTPException(status_code=401, detail="No autorizado")


def _get_or_create(session_id: str):
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]
    sid = str(uuid.uuid4())
    sessions[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return sid, sessions[sid]


# ── Modelos ────────────────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str
    session_id: str = ""

class RunRequest(BaseModel):
    command: str        # build | update | fix | show | history | balance | doctor
    args: str = ""      # tarea o cambio (para build/update)
    project_dir: str = ""  # directorio del proyecto (opcional)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _capture(fn, *args, **kwargs) -> str:
    """Ejecuta fn capturando su stdout y devolviéndolo como string."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue().strip()


def _project_dir(requested: str) -> Path:
    if requested:
        return Path(requested).expanduser()
    return BUILD_DIR


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health(authorization: str | None = Header(None)):
    _check_auth(authorization)
    return {"status": "ok"}


@app.post("/api/ask")
async def ask(req: MessageRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    sid, history = _get_or_create(req.session_id)
    history.append({"role": "user", "content": req.message})
    client = DeepSeekClient(DEEPSEEK_API_KEY)
    try:
        raw = client.chat_with_context(history, temperature=0.7, max_tokens=3000)
        content = raw["choices"][0]["message"]["content"]
        history.append({"role": "assistant", "content": content})
        return {"session_id": sid, "response": content}
    except Exception as e:
        history.pop()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/new")
async def new_conversation(authorization: str | None = Header(None)):
    _check_auth(authorization)
    sid = str(uuid.uuid4())
    sessions[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return {"session_id": sid}


@app.post("/api/run")
async def run_command(req: RunRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    cmd = req.command.lower().strip()

    # ── balance ───────────────────────────────────────────────────────────────
    if cmd == "balance":
        try:
            data = bal.fetch(DEEPSEEK_API_KEY)
            total    = data.get("balance", {}).get("total_balance", "?")
            currency = data.get("balance", {}).get("currency", "USD")
            return {"output": f"**Crédito disponible:** {total} {currency}"}
        except Exception as e:
            return {"output": f"❌ Error: {e}"}

    # ── history ───────────────────────────────────────────────────────────────
    if cmd == "history":
        from cli.commands import run_history
        return {"output": _capture(run_history)}

    # ── doctor ────────────────────────────────────────────────────────────────
    if cmd == "doctor":
        from cli.commands import run_doctor
        return {"output": _capture(run_doctor)}

    # ── show ──────────────────────────────────────────────────────────────────
    if cmd == "show":
        from cli.commands import run_show
        project_dir = _project_dir(req.project_dir)
        return {"output": _capture(run_show, project_dir)}

    # ── build ─────────────────────────────────────────────────────────────────
    if cmd == "build":
        if not req.args:
            return {"output": "❌ Uso: `build <descripción del proyecto>`"}
        from core.system import DeepSeekLearningSystem
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        lines, files = [], []
        system = DeepSeekLearningSystem(
            DEEPSEEK_API_KEY,
            output_dir=str(BUILD_DIR),
            root_is_output_dir=False,
            rules=load_rules(BUILD_DIR / ".deeprules"),
            on_progress=lambda m: lines.append(f"⚙️ {m}"),
            on_file=lambda f: files.append(f),
        )
        try:
            result = system.execute_and_learn(req.args)
        except Exception as e:
            return {"output": f"❌ Error: {e}"}

        written = result.get("files_written", [])
        success = result.get("success", False)
        icon = "✅" if success else "⚠️"
        project_path = str(Path(written[0]).parent) if written else str(BUILD_DIR)
        file_list = "\n".join(f"- `{Path(f).name}`" for f in written[:20])
        return {"output": (
            f"{icon} **{'Proyecto generado' if success else 'Generado con advertencias'}**\n\n"
            f"📁 `{project_path}`\n\n"
            f"**Archivos ({len(written)}):**\n{file_list}"
        )}

    # ── fix ───────────────────────────────────────────────────────────────────
    if cmd == "fix":
        from cli.commands import run_fix_current
        project_dir = _project_dir(req.project_dir)
        output = _capture(run_fix_current, DEEPSEEK_API_KEY, project_dir)
        return {"output": output or "✅ Corrección completada."}

    # ── update ────────────────────────────────────────────────────────────────
    if cmd == "update":
        if not req.args:
            return {"output": "❌ Uso: `update <descripción del cambio>`"}
        from cli.commands import run_update
        project_dir = _project_dir(req.project_dir)
        output = _capture(run_update, req.args, DEEPSEEK_API_KEY, project_dir)
        return {"output": output or "✅ Actualización completada."}

    return {"output": f"❌ Comando desconocido: `{cmd}`"}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
