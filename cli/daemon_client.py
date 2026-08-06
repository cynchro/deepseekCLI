"""Cliente del daemon (`deep serve`) para el REPL local: arranca el daemon en
background si no está corriendo y expone una sesión WS síncrona para que la
terminal sea un cliente más — igual que la PWA — en vez de dueña del
AgentLoop. Solo se usa para workspaces LOCALES: sobre SSH (--host / /remote)
el REPL sigue ejecutando el AgentLoop en el propio proceso, sin pasar por acá."""
import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import websocket

from core.config import ensure_daemon_token

_LOG_FILE = Path.home() / ".config" / "deep" / "serve.log"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_HEALTH_TIMEOUT = 2
_START_TIMEOUT = 10
_RECV_RETRIES = 50  # para respuestas puntuales (stats/finalized) que pueden
                    # venir intercaladas con broadcasts de otros clientes


class DaemonError(Exception):
    pass


def ensure_daemon(port: int = 8000) -> tuple[str, str]:
    """Devuelve (base_url, token) de un daemon local, arrancándolo en
    background si hace falta (nohup-style, sobrevive a que cierres esta
    terminal). No resuelve colisión de puerto con un proceso ajeno a deep:
    si falla, el log tiene el detalle."""
    token = ensure_daemon_token()
    base_url = f"http://127.0.0.1:{port}"
    if _is_alive(base_url, token):
        return base_url, token

    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOG_FILE, "a") as log:
        subprocess.Popen(
            [sys.executable, "-m", "deep", "serve", "--port", str(port)],
            stdout=log, stderr=log, cwd=str(_REPO_ROOT), start_new_session=True,
        )

    deadline = time.time() + _START_TIMEOUT
    while time.time() < deadline:
        if _is_alive(base_url, token):
            return base_url, token
        time.sleep(0.3)
    raise DaemonError(
        f"No se pudo levantar el daemon local en {base_url}. "
        f"Mirá {_LOG_FILE} o corré `deep serve` a mano.")


def _is_alive(base_url: str, token: str) -> bool:
    try:
        r = requests.get(f"{base_url}/api/health",
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=_HEALTH_TIMEOUT)
        return r.status_code == 200
    except requests.RequestException:
        return False


def list_sessions(base_url: str, token: str) -> list:
    r = requests.get(f"{base_url}/api/sessions",
                      headers={"Authorization": f"Bearer {token}"}, timeout=5)
    r.raise_for_status()
    return r.json().get("sessions", [])


class DaemonSession:
    """Sesión WS síncrona sobre una sesión del daemon: attach, turnos con
    confirm round-trip, mode/model/reset/finalize/stats. `ws_factory` es
    pluggable para poder testear con un transporte fake, sin abrir un socket
    real (misma firma que websocket.create_connection: url -> objeto con
    send/recv/close)."""

    def __init__(self, base_url: str, token: str, ws_factory=None):
        ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        factory = ws_factory or websocket.create_connection
        try:
            self._ws = factory(f"{ws_url}/ws/session")
        except (OSError, websocket.WebSocketException) as e:
            raise DaemonError(f"no se pudo conectar al daemon: {e}") from e
        self._send({"type": "auth", "token": token})
        self.session_id = None
        self.workspace = None
        self.mode = "ask"
        self.model = None
        self.busy = False
        self.did_work = False  # True apenas se manda un turno, para _finalize_session

    def _send(self, payload: dict) -> None:
        try:
            self._ws.send(json.dumps(payload))
        except (OSError, websocket.WebSocketException) as e:
            raise DaemonError(f"se perdió la conexión con el daemon: {e}") from e

    def _recv(self) -> dict:
        try:
            return json.loads(self._ws.recv())
        except (OSError, websocket.WebSocketException, json.JSONDecodeError) as e:
            raise DaemonError(f"se perdió la conexión con el daemon: {e}") from e

    def attach(self, session_id: str = "", project_dir: str = "",
               mode: str = "ask", model: str = None) -> dict:
        self._send({"type": "attach", "session_id": session_id,
                    "project_dir": project_dir, "mode": mode, "model": model})
        msg = self._recv()
        self.session_id = msg["session_id"]
        self.workspace = msg["workspace"]
        self.mode = msg["mode"]
        self.model = msg["model"]
        self.busy = msg["busy"]
        return msg

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._send({"type": "set_mode", "mode": mode})

    def set_model(self, model: str) -> None:
        self.model = model
        self._send({"type": "set_model", "model": model})

    def reset(self) -> None:
        self._send({"type": "reset"})

    def finalize(self) -> None:
        self._send({"type": "finalize"})
        for _ in range(_RECV_RETRIES):
            if self._recv().get("type") == "finalized":
                return

    def get_stats(self) -> dict:
        self._send({"type": "get_stats"})
        for _ in range(_RECV_RETRIES):
            msg = self._recv()
            if msg.get("type") == "stats":
                msg.pop("type", None)
                return msg
        return {}

    def run_turn(self, text: str, on_event, ask_confirm) -> dict:
        """Manda un turno y consume eventos hasta done/fatal/busy. Cada
        evento intermedio se reenvía a on_event(kind, data) — mismo esquema
        que AgentLoop.on_event, así el REPL reusa _printer tal cual. Los
        confirm_request se responden con ask_confirm(desc, is_shell, kind) -> str
        ("s"/"n"/"a")."""
        self.did_work = True
        self._send({"type": "message", "text": text})
        return self._consume_turn(on_event, ask_confirm)

    def wait_turn(self, on_event, ask_confirm) -> dict:
        """Como run_turn, pero sin mandar texto nuevo: escucha los eventos de
        un turno que YA estaba corriendo server-side (reconexión a mitad de
        un turno largo). Evita reenviar el mismo pedido y duplicar el
        trabajo — usar cuando `self.busy` sigue True después de un attach."""
        return self._consume_turn(on_event, ask_confirm)

    def _consume_turn(self, on_event, ask_confirm) -> dict:
        while True:
            msg = self._recv()
            kind = msg.pop("type", "")
            if kind == "confirm_request":
                answer = ask_confirm(msg.get("desc", ""), msg.get("is_shell", False),
                                      msg.get("kind", "confirm"))
                self._send({"type": "confirm_response",
                            "request_id": msg.get("request_id", ""), "answer": answer})
                continue
            if kind == "mode_changed":
                self.mode = msg.get("mode", self.mode)
                continue
            if kind == "model_changed":
                self.model = msg.get("model", self.model)
                continue
            if kind == "busy":
                return {"busy": True, **msg}
            if kind in ("done", "fatal"):
                return msg
            on_event(kind, msg)

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass
