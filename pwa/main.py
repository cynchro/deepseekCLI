import contextlib
import io
import logging
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Request
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

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("deep.pwa")

SYSTEM_PROMPT = (
    "Sos un asistente experto en programación y tecnología. "
    "Respondé en el mismo idioma de la pregunta. "
    "Usá markdown para formatear las respuestas cuando sea apropiado."
)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

sessions: dict = {}       # {sid: [messages]}
_session_ts: dict = {}    # {sid: last_access unix timestamp}
SESSION_TTL = 7200        # 2 horas


def _cleanup_sessions():
    now = time.time()
    expired = [sid for sid, t in _session_ts.items() if now - t > SESSION_TTL]
    for sid in expired:
        sessions.pop(sid, None)
        del _session_ts[sid]
    if expired:
        log.debug("Sesiones expiradas: %d", len(expired))


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.time()
    body = b""
    if request.method in ("POST", "DELETE", "PUT"):
        body = await request.body()
        # re-inject body so FastAPI can still read it
        async def receive():
            return {"type": "http.request", "body": body}
        request._receive = receive

    log.info("→ %s %s  body=%s", request.method, request.url.path,
             body.decode(errors="replace")[:300] if body else "-")

    response = await call_next(request)
    elapsed = (time.time() - t0) * 1000
    log.info("← %s %s  status=%d  %.0fms",
             request.method, request.url.path, response.status_code, elapsed)
    return response


def _check_auth(authorization: str | None):
    if APP_PASSWORD and authorization != f"Bearer {APP_PASSWORD}":
        log.warning("Auth failed: %s", authorization)
        raise HTTPException(status_code=401, detail="No autorizado")


def _get_or_create(session_id: str):
    _cleanup_sessions()
    now = time.time()
    if session_id and session_id in sessions:
        _session_ts[session_id] = now
        return session_id, sessions[session_id]
    sid = str(uuid.uuid4())
    sessions[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    _session_ts[sid] = now
    log.debug("Nueva sesión: %s  (activas: %d)", sid, len(sessions))
    return sid, sessions[sid]


# ── Modelos ────────────────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str
    session_id: str = ""

class RunRequest(BaseModel):
    command: str
    args: str = ""
    project_dir: str = ""
    project_name: str = ""

class DeleteProjectRequest(BaseModel):
    path: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    result = buf.getvalue().strip()
    log.debug("_capture(%s) → %d chars: %s", fn.__name__, len(result),
              result[:200].replace("\n", "↵"))
    return result


def _project_dir(requested: str) -> Path:
    p = Path(requested).expanduser() if requested else BUILD_DIR
    log.debug("project_dir: %s", p)
    return p


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health(authorization: str | None = Header(None)):
    _check_auth(authorization)
    return {"status": "ok"}


@app.post("/api/ask")
async def ask(req: MessageRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    sid, history = _get_or_create(req.session_id)
    log.info("ask: session=%s  msg=%s", sid[:8], req.message[:80])
    history.append({"role": "user", "content": req.message})
    client = DeepSeekClient(DEEPSEEK_API_KEY)
    try:
        t0 = time.time()
        raw = client.chat_with_context(history, temperature=0.7, max_tokens=3000)
        content = raw["choices"][0]["message"]["content"]
        history.append({"role": "assistant", "content": content})
        _session_ts[sid] = time.time()
        log.info("ask OK: %.0fms  resp=%d chars", (time.time()-t0)*1000, len(content))
        return {"session_id": sid, "response": content}
    except Exception as e:
        history.pop()
        log.error("ask ERROR: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/new")
async def new_conversation(authorization: str | None = Header(None)):
    _check_auth(authorization)
    sid = str(uuid.uuid4())
    sessions[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    log.info("nueva conversación: %s", sid[:8])
    return {"session_id": sid}


@app.get("/api/ls")
async def list_dir(path: str = "", authorization: str | None = Header(None)):
    _check_auth(authorization)
    target = Path(path).expanduser().resolve() if path else Path.home()
    log.info("ls: %s", target)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="No es un directorio")
    dirs = []
    try:
        for d in sorted(target.iterdir()):
            if d.is_dir() and not d.name.startswith('.'):
                has_project = (d / '.deep' / 'context.json').exists()
                dirs.append({"name": d.name, "path": str(d), "has_project": has_project})
    except PermissionError:
        pass
    parent = str(target.parent) if str(target) != str(target.parent) else None
    log.debug("ls → %d dirs", len(dirs))
    return {"current": str(target), "parent": parent, "dirs": dirs}


@app.get("/api/projects")
async def list_projects(authorization: str | None = Header(None)):
    _check_auth(authorization)
    if not BUILD_DIR.exists():
        return {"projects": []}
    projects = []
    import json as _json
    for item in sorted(BUILD_DIR.iterdir()):
        if not item.is_dir():
            continue
        ctx_file = item / ".deep" / "context.json"
        if not ctx_file.exists():
            continue
        try:
            ctx = _json.loads(ctx_file.read_text(encoding="utf-8"))
        except Exception:
            ctx = {}
        files = [
            f for f in item.rglob("*")
            if f.is_file() and ".deep" not in f.parts and not f.name.startswith(".")
        ]
        projects.append({
            "name": item.name,
            "path": str(item),
            "task": ctx.get("task", ""),
            "last_update": ctx.get("last_update", ""),
            "timestamp": ctx.get("timestamp", ""),
            "updated_at": ctx.get("updated_at", ""),
            "file_count": len(files),
        })
    log.info("projects → %d encontrados", len(projects))
    return {"projects": projects}


@app.delete("/api/projects")
async def delete_project(req: DeleteProjectRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    path = Path(req.path).resolve()
    try:
        path.relative_to(BUILD_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Ruta no permitida")
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    log.info("delete project: %s", path)
    shutil.rmtree(path)
    return {"ok": True}


@app.post("/api/run")
async def run_command(req: RunRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    cmd = req.command.lower().strip()
    log.info("run: cmd=%s  args=%s  project_dir=%s", cmd, req.args[:60] if req.args else "-", req.project_dir or "-")

    if cmd == "balance":
        try:
            data = bal.fetch(DEEPSEEK_API_KEY)
            infos = data.get("balance_infos", [])
            if not infos:
                return {"output": "⚠️ No se pudo obtener el balance."}
            lines = ["**Crédito disponible:**\n"]
            for info in infos:
                total    = info.get("total_balance", "?")
                currency = info.get("currency", "USD")
                granted  = info.get("granted_balance", 0)
                topped   = info.get("topped_up_balance", 0)
                lines.append(f"- **{total} {currency}** (bonificado: {granted} | recargado: {topped})")
            return {"output": "\n".join(lines)}
        except Exception as e:
            log.error("balance error: %s", e)
            return {"output": f"❌ Error: {e}"}

    if cmd == "history":
        from cli.commands import run_history
        return {"output": _capture(run_history)}

    if cmd == "doctor":
        from cli.commands import run_doctor
        return {"output": _capture(run_doctor)}

    if cmd == "show":
        from cli.commands import run_show
        project_dir = _project_dir(req.project_dir)
        log.info("show: dir=%s  existe=%s", project_dir, project_dir.exists())
        return {"output": _capture(run_show, project_dir)}

    if cmd == "build":
        if not req.args:
            return {"output": "❌ Uso: `build <descripción del proyecto>`"}
        from core.system import DeepSeekLearningSystem
        # Si hay workspace definido úsalo como base; si no, BUILD_DIR
        base_dir = Path(req.project_dir).expanduser() if req.project_dir else BUILD_DIR
        base_dir.mkdir(parents=True, exist_ok=True)
        log.info("build START: %s  base=%s", req.args, base_dir)
        t0 = time.time()
        written_files = []
        system = DeepSeekLearningSystem(
            DEEPSEEK_API_KEY,
            output_dir=str(base_dir),
            root_is_output_dir=False,
            rules=load_rules(base_dir / ".deeprules"),
            on_progress=lambda m: log.info("build progress: %s", m),
            on_file=lambda f: (written_files.append(f), log.debug("build file: %s", f)),
            project_name=req.project_name,
        )
        try:
            result = system.execute_and_learn(req.args)
        except Exception as e:
            log.error("build ERROR: %s", e, exc_info=True)
            return {"output": f"❌ Error: {e}"}

        written = result.get("files_written", [])
        success = result.get("success", False)
        log.info("build END: success=%s  files=%d  %.0fs", success, len(written), time.time()-t0)
        icon = "✅" if success else "⚠️"
        project_path = str(Path(written[0]).parent) if written else str(base_dir)
        file_list = "\n".join(f"- `{Path(f).name}`" for f in written[:20])
        # Devolver también el path del proyecto para que el frontend actualice el workspace
        return {
            "output": (
                f"{icon} **{'Proyecto generado' if success else 'Generado con advertencias'}**\n\n"
                f"📁 `{project_path}`\n\n"
                f"**Archivos ({len(written)}):**\n{file_list}"
            ),
            "project_path": project_path,
        }

    if cmd == "fix":
        import json as _json
        from core.system import DeepSeekLearningSystem
        project_dir = _project_dir(req.project_dir)
        log.info("fix START: dir=%s  existe=%s", project_dir, project_dir.exists())
        ctx_file = project_dir / ".deep" / "context.json"
        eval_file = project_dir / ".deep" / "evaluation.json"
        if not ctx_file.exists():
            return {"output": "❌ No hay proyecto en este directorio. Usá `build` primero."}
        try:
            ctx = _json.loads(ctx_file.read_text(encoding="utf-8"))
        except Exception as e:
            return {"output": f"❌ No se pudo leer el contexto: {e}"}
        task  = ctx.get("task", "")
        model = ctx.get("model", "deepseek-chat")
        log.info("fix: task=%s  model=%s", task[:80], model)
        evaluation = {}
        if eval_file.exists():
            try:
                evaluation = _json.loads(eval_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        code_files = [
            str(f) for f in project_dir.rglob("*")
            if f.is_file() and ".deep" not in f.parts and not f.name.startswith(".")
        ]
        fake_result = {
            "files_written": code_files,
            "outcome": _json.dumps(evaluation),
            "plan": ctx.get("plan", ""),
            "success": evaluation.get("success", False),
        }
        fixed_files = []
        system = DeepSeekLearningSystem(
            DEEPSEEK_API_KEY, output_dir=str(project_dir), model=model,
            root_is_output_dir=True, rules=[],
            on_progress=lambda m: log.info("fix progress: %s", m),
            on_file=lambda f: (fixed_files.append(f), log.debug("fix file: %s", f)),
        )
        t0 = time.time()
        try:
            fix_result = system.review_and_fix(task, fake_result)
        except Exception as e:
            log.error("fix ERROR: %s", e, exc_info=True)
            return {"output": f"❌ Error en fix: {e}"}
        fixed = fix_result.get("files_fixed", [])
        success = fix_result.get("success", False)
        log.info("fix END: %.0fs  fixed=%d  success=%s", time.time()-t0, len(fixed), success)
        icon = "✅" if success else "⚠️"
        lines = [f"{icon} **{'Corrección exitosa' if success else 'Corrección con advertencias'}**\n"]
        if fixed:
            lines.append(f"**{len(fixed)} archivo(s) corregido(s):**")
            lines += [f"- `{Path(f).name}`" for f in fixed[:20]]
        else:
            lines.append("No se encontraron archivos para corregir.")
        return {"output": "\n".join(lines)}

    if cmd == "update":
        if not req.args:
            return {"output": "❌ Uso: `update <descripción del cambio>`"}
        import json as _json
        from core.system import DeepSeekLearningSystem
        project_dir = _project_dir(req.project_dir)
        log.info("update START: dir=%s  args=%s", project_dir, req.args[:80])
        ctx_file = project_dir / ".deep" / "context.json"
        if not ctx_file.exists():
            return {"output": "❌ No hay proyecto en este directorio. Usá `build` primero."}
        try:
            ctx = _json.loads(ctx_file.read_text(encoding="utf-8"))
        except Exception as e:
            return {"output": f"❌ No se pudo leer el contexto: {e}"}
        task  = ctx.get("task", "proyecto")
        model = ctx.get("model", "deepseek-chat")
        log.info("update: task=%s  model=%s", task[:80], model)
        updated_files = []
        system = DeepSeekLearningSystem(
            DEEPSEEK_API_KEY, output_dir=str(project_dir), model=model,
            root_is_output_dir=True, rules=[],
            on_progress=lambda m: log.info("update progress: %s", m),
            on_file=lambda f: (updated_files.append(f), log.debug("update file: %s", f)),
        )
        t0 = time.time()
        try:
            result = system.execute_update(req.args, task)
        except Exception as e:
            log.error("update ERROR: %s", e, exc_info=True)
            return {"output": f"❌ Error en update: {e}"}
        files_updated = result.get("files_updated", [])
        success = result.get("success", False)
        log.info("update END: %.0fs  files=%d  success=%s", time.time()-t0, len(files_updated), success)
        icon = "✅" if success else "⚠️"
        lines = [f"{icon} **{'Actualización aplicada' if success else 'Actualización con advertencias'}**\n"]
        if files_updated:
            lines.append(f"**{len(files_updated)} archivo(s) modificado(s):**")
            lines += [f"- `{Path(f).name}`" for f in files_updated[:20]]
        return {"output": "\n".join(lines)}

    if cmd == "workspace":
        if not req.args:
            return {"output": "❌ Uso: `workspace /ruta/del/directorio`"}
        path = Path(req.args).expanduser().resolve()
        if not path.exists():
            try:
                path.mkdir(parents=True)
                return {"output": f"📁 Directorio creado y workspace establecido en:\n\n`{path}`"}
            except Exception as e:
                return {"output": f"❌ No se pudo crear el directorio: {e}"}
        if not path.is_dir():
            return {"output": f"❌ `{path}` no es un directorio."}
        return {"output": f"✅ Workspace establecido en:\n\n`{path}`"}

    log.warning("comando desconocido: %s", cmd)
    return {"output": f"❌ Comando desconocido: `{cmd}`"}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
