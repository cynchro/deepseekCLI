"""Native host: relay puro stdio (Native Messaging) <-> WebSocket del daemon.

Lo lanza Chrome vía `chrome.runtime.connectNative` cuando arranca
`chrome_bridge/extension/background.js` — nunca se ejecuta a mano. No
interpreta el envelope de mensajes (id/type/method/...), solo lo reenvía tal
cual en ambas direcciones. Toda la lógica CDP vive en `background.js` (sabe
hablar con `chrome.debugger`) y en `core/tools/browser.py::_ExtensionDriver`
(arma los pedidos), del otro lado del WS.

Reglas no negociables del protocolo de Native Messaging de Chrome:
- Nunca escribir a stdout salvo el framing (4 bytes little-endian de longitud
  + JSON UTF-8) — cualquier log suelto ahí lo corrompe en silencio, sin
  ningún error visible del lado de Chrome.
- Todo log va a un archivo (nunca stderr/stdout): Chrome no garantiza que
  stderr quede accesible para debugging.
"""
import argparse
import json
import logging
import struct
import sys
import threading
from pathlib import Path

import websocket

from core.config import ensure_daemon_token

_LOG_FILE = Path.home() / ".config" / "deep" / "chrome_bridge" / "native_host.log"


def _setup_logging() -> None:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(_LOG_FILE), level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def read_message(stream) -> dict | None:
    """Lee un mensaje con framing de Native Messaging. `None` si Chrome cerró stdin."""
    raw_len = stream.read(4)
    if len(raw_len) < 4:
        return None
    (msg_len,) = struct.unpack("<I", raw_len)
    data = stream.read(msg_len)
    return json.loads(data.decode("utf-8"))


def write_message(stream, msg: dict) -> None:
    data = json.dumps(msg).encode("utf-8")
    stream.write(struct.pack("<I", len(data)))
    stream.write(data)
    stream.flush()


def _stdin_to_ws(ws, stdin_buf, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            msg = read_message(stdin_buf)
        except Exception:
            logging.exception("error leyendo stdin")
            break
        if msg is None:
            break
        try:
            ws.send(json.dumps(msg))
        except Exception:
            logging.exception("error mandando al WS")
            break
    stop.set()


def _ws_to_stdout(ws, stdout_buf, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            raw = ws.recv()
        except Exception:
            logging.exception("error leyendo del WS")
            break
        if not raw:
            break
        try:
            msg = json.loads(raw)
        except Exception:
            logging.exception("mensaje no-JSON del daemon, descartado")
            continue
        try:
            write_message(stdout_buf, msg)
        except Exception:
            logging.exception("error escribiendo a stdout")
            break
    stop.set()


def main(port: int) -> None:
    _setup_logging()
    logging.info("native host arrancando, puerto=%s", port)
    token = ensure_daemon_token()
    url = f"ws://127.0.0.1:{port}/ws/browser-bridge"
    try:
        ws = websocket.create_connection(url, timeout=10)
    except Exception:
        logging.exception("no se pudo conectar a %s (¿está corriendo `deep serve`?)", url)
        return
    # El timeout de arriba es solo para el handshake de conexión — dejarlo
    # puesto también le aplicaría a ws.recv() en el loop de abajo, matando la
    # conexión cada vez que pasan 10s sin mensajes nuevos del daemon (una
    # sesión de navegador real puede estar minutos sin que el agente llame a
    # ninguna tool).
    ws.settimeout(None)
    ws.send(json.dumps({"type": "auth", "token": token}))

    stop = threading.Event()
    t_in = threading.Thread(
        target=_stdin_to_ws, args=(ws, sys.stdin.buffer, stop), daemon=True)
    t_out = threading.Thread(
        target=_ws_to_stdout, args=(ws, sys.stdout.buffer, stop), daemon=True)
    t_in.start()
    t_out.start()
    t_in.join()
    t_out.join()
    try:
        ws.close()
    except Exception:
        pass
    logging.info("native host terminando")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    # Chrome pasa argumentos extra (origin, ID de extensión) al lanzar el
    # native host — se ignoran, no forman parte de nuestro protocolo.
    args, _unknown = parser.parse_known_args()
    main(args.port)
