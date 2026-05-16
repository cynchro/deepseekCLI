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
import core.balance as bal

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
APP_PASSWORD = os.environ.get("DEEP_APP_PASSWORD", "")

SYSTEM_PROMPT = (
    "Sos un asistente experto en programación y tecnología. "
    "Respondé en el mismo idioma de la pregunta. "
    "Usá markdown para formatear las respuestas cuando sea apropiado."
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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


class MessageRequest(BaseModel):
    message: str
    session_id: str = ""


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


@app.get("/api/balance")
async def balance(authorization: str | None = Header(None)):
    _check_auth(authorization)
    try:
        return bal.fetch(DEEPSEEK_API_KEY)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
