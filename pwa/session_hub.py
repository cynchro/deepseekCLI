"""Registro de sesiones de agente compartido entre transportes (WebSocket, SSE
legacy). Cada SessionHub envuelve un AgentLoop + Permissions y permite que N
clientes se suscriban a sus eventos en vivo (fan-out) y respondan pedidos de
confirmación por round-trip, en vez de que cada cliente tenga su propio
AgentLoop aislado."""
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from cli.agent_runner import Permissions
from core import journal as _journal
from core.agent_loop import AgentLoop
from core.client import DeepSeekClient
from core.context import load_project_context
from core.rules import load_rules

CONFIRM_TIMEOUT = 120  # segundos; sin respuesta de nadie ⇒ deniega (seguro por default)


def _event_payload(kind: str, data: dict) -> dict:
    """Compacta/trunca el evento para el stream (no mandamos archivos enteros)."""
    d = dict(data or {})
    if "result" in d:
        first = (d["result"].splitlines() or [""])[0]
        d["result"] = first[:200]
    if "args" in d:
        d["args"] = {k: str(v)[:120] for k, v in (d["args"] or {}).items()}
    if "content" in d and kind == "user":
        d["content"] = d["content"][:200]
    return {"type": kind, **d}


class SessionHub:
    """Dueño de un AgentLoop que vive más allá de cualquier conexión
    individual. `subscribers` son callables `(payload: dict) -> None`
    invocados sincrónicamente desde el thread que corre el turno — cada
    transporte decide cómo reenviar eso (WS hace un hop a asyncio, SSE
    simplemente hace `queue.put`)."""

    def __init__(self, sid: str, workspace: str):
        self.id = sid
        self.workspace = workspace
        self.loop: AgentLoop = None
        self.permissions: Permissions = None
        self.created_at = time.time()
        self.last_active = time.time()
        self.subscribers: set[Callable[[dict], None]] = set()
        self.turn_lock = threading.Lock()
        self.busy = False
        self._pending_confirms: dict[str, tuple] = {}
        self._confirms_lock = threading.Lock()

    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self.subscribers.add(cb)

    def unsubscribe(self, cb: Callable[[dict], None]) -> None:
        self.subscribers.discard(cb)

    def broadcast(self, payload: dict) -> None:
        for cb in list(self.subscribers):
            try:
                cb(payload)
            except Exception:
                self.subscribers.discard(cb)

    def emit(self, kind: str, data: dict) -> None:
        """Sink de AgentLoop.on_event — se registra una sola vez al crear el
        hub, así ningún cliente nuevo puede pisarle el callback a otro."""
        self.last_active = time.time()
        self.broadcast(_event_payload(kind, data))

    def ask_confirm(self, desc: str, is_shell: bool, kind: str = "confirm") -> str:
        """Confirm round-trip: bloquea el thread del turno (llamado desde
        Permissions._prompt/confirm_plan) hasta que algún cliente conteste o se
        cumpla el timeout. Devuelve la respuesta cruda ("s"/"n"/"a"/"")."""
        request_id = str(uuid.uuid4())
        ev = threading.Event()
        slot = {"answer": ""}
        with self._confirms_lock:
            self._pending_confirms[request_id] = (ev, slot)
        self.broadcast({"type": "confirm_request", "request_id": request_id,
                         "desc": desc, "is_shell": is_shell, "kind": kind})
        got = ev.wait(timeout=CONFIRM_TIMEOUT)
        with self._confirms_lock:
            self._pending_confirms.pop(request_id, None)
        return slot["answer"] if got else "n"

    def resolve_confirm(self, request_id: str, answer: str) -> None:
        with self._confirms_lock:
            item = self._pending_confirms.get(request_id)
        if item:
            ev, slot = item
            slot["answer"] = answer
            ev.set()

    def get_stats(self) -> dict:
        return self.loop.client.get_stats()

    def finalize(self) -> None:
        """Resume la sesión con FLASH y la agrega a .deep/journal.md — corre
        acá porque `messages`/`client` viven en el daemon, no en el cliente
        que pide el cierre. Se traga errores en silencio, igual que el
        _finalize_session original del REPL local."""
        if not any(m.get("role") == "user" for m in self.loop.messages[1:]):
            return
        try:
            entry = _journal.summarize_session(self.loop.client, self.loop.messages)
            if entry:
                _journal.append_entry(Path(self.workspace), entry)
        except Exception:
            pass

    def try_start_turn(self) -> bool:
        return self.turn_lock.acquire(blocking=False)

    def finish_turn(self) -> None:
        self.busy = False
        self.last_active = time.time()
        self.turn_lock.release()

    def run_turn_async(self, text: str, on_done: Callable[[dict], None] = None) -> bool:
        """Arranca el turno en un thread si la sesión está libre. Devuelve
        False (y notifica "busy") si ya hay un turno en curso."""
        if not self.try_start_turn():
            self.broadcast({"type": "busy", "reason": "turn_in_progress"})
            return False
        self.busy = True

        def worker():
            try:
                res = self.loop.run(text)
                payload = {"type": "done", "session_id": self.id,
                           "success": res.get("success", False),
                           "content": res.get("content", ""),
                           "error": res.get("error", ""),
                           "steps": res.get("steps", 0),
                           "stats": res.get("stats", {})}
            except Exception as e:
                payload = {"type": "fatal", "error": str(e)}
            finally:
                self.finish_turn()
            self.broadcast(payload)
            if on_done:
                on_done(payload)

        threading.Thread(target=worker, daemon=True).start()
        return True


class SessionRegistry:
    def __init__(self, api_key: str, build_dir):
        self._api_key = api_key
        self._build_dir = build_dir
        self._sessions: dict[str, SessionHub] = {}
        self._lock = threading.Lock()

    def list(self) -> list[SessionHub]:
        with self._lock:
            return list(self._sessions.values())

    def get(self, session_id: str) -> SessionHub | None:
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create(self, session_id: str, project_dir, mode: str = "ask",
                       model: str = None) -> SessionHub:
        with self._lock:
            if session_id and session_id in self._sessions:
                hub = self._sessions[session_id]
                hub.last_active = time.time()
                return hub

            ws = project_dir
            ws.mkdir(parents=True, exist_ok=True)
            sid = session_id or str(uuid.uuid4())
            hub = SessionHub(sid, str(ws))

            perms = Permissions(
                mode=mode, ask=hub.ask_confirm,
                notify=lambda msg: hub.broadcast({"type": "info", "text": msg}),
                on_mode_change=lambda m: hub.broadcast({"type": "mode_changed", "mode": m}),
            )
            client = DeepSeekClient(self._api_key)
            kwargs = {"model": model} if model else {}
            hub.loop = AgentLoop(
                client, ws,
                rules=load_rules(ws / ".deeprules"),
                project_context=load_project_context(ws),
                on_event=hub.emit, confirm=perms, confirm_plan=perms.confirm_plan,
                mode=mode, get_mode=lambda: perms.mode, **kwargs,
            )
            hub.permissions = perms
            self._sessions[sid] = hub
            return hub
