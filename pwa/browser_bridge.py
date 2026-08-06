"""Puente en memoria entre el WS de la extensión de Chrome (`/ws/browser-bridge`,
un solo native host conectado por vez) y `core/tools/browser.py::_ExtensionDriver`,
que corre en el thread del turno del agente (`SessionHub.run_turn_async`, ver
`pwa/session_hub.py:148`).

Mismo patrón que `SessionHub._pending_confirms`/`ask_confirm`/`resolve_confirm`
(dict id -> (Event, slot), ver `pwa/session_hub.py:52,74-96`) combinado con el
`asyncio.run_coroutine_threadsafe` que ya usa `ws_session.subscriber` en
`pwa/main.py` para cruzar de thread a event loop — acá en la dirección inversa:
el daemon pregunta (`call`) y la extensión contesta (`on_message`)."""
import asyncio
import threading
import uuid

_CALL_TIMEOUT = 15  # seg; CDP normalmente responde en <1s


class BrowserBridge:
    def __init__(self):
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._lock = threading.Lock()

    def is_connected(self) -> bool:
        return self._ws is not None

    async def on_connect(self, websocket, loop: asyncio.AbstractEventLoop) -> None:
        if self._ws is not None:
            # Una sola extensión conectada por vez en Fase 1 (ver plan): la
            # conexión nueva reemplaza a la vieja en vez de rechazarse.
            try:
                await self._ws.close(code=4409)
            except Exception:
                pass
        self._ws = websocket
        self._loop = loop

    async def on_disconnect(self) -> None:
        self._ws = None
        self._loop = None
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _req_id, (ev, slot) in pending:
            slot["error"] = "la extensión de Chrome se desconectó"
            ev.set()

    async def on_message(self, payload: dict) -> None:
        req_id = payload.get("id")
        if req_id is None:
            return
        with self._lock:
            item = self._pending.pop(req_id, None)
        if item is None:
            return
        ev, slot = item
        if payload.get("type") == "cdp_error":
            slot["error"] = payload.get("error") or "error desconocido de la extensión"
        else:
            slot["result"] = payload.get("result")
        ev.set()

    def call(self, method: str, params: dict = None) -> dict:
        """Bloqueante — llamado desde el thread del turno del agente, nunca
        desde el event loop de uvicorn."""
        if self._ws is None or self._loop is None:
            raise RuntimeError(
                "no hay extensión de Chrome conectada (ver `deep browser install-extension`)"
            )
        req_id = str(uuid.uuid4())
        ev = threading.Event()
        slot: dict = {}
        with self._lock:
            self._pending[req_id] = (ev, slot)
        msg = {"id": req_id, "type": "cdp_call", "method": method, "params": params or {}}
        asyncio.run_coroutine_threadsafe(self._ws.send_json(msg), self._loop)
        got = ev.wait(timeout=_CALL_TIMEOUT)
        with self._lock:
            self._pending.pop(req_id, None)
        if not got:
            raise TimeoutError(f"la extensión no respondió a {method} a tiempo")
        if "error" in slot:
            raise RuntimeError(slot["error"])
        return slot.get("result") or {}


BRIDGE = BrowserBridge()
