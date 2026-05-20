"""
Logger de debug para deep.

Activación:
  deep --debug build "tarea"   → escribe debug.log en el directorio actual
  DEEP_DEBUG=1 deep build ...  → misma activación vía env var

El logger es un singleton; las funciones son no-op cuando no está activo.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_logger = None


class DebugLogger:
    def __init__(self, log_path: str = "debug.log"):
        self.log_path = Path(log_path)
        self._start = time.time()
        ts = datetime.now().isoformat(timespec="milliseconds")
        self._write_raw(f"\n{'='*72}\n")
        self._write_raw(f"SESSION  {ts}  pid={os.getpid()}\n")
        self._write_raw(f"{'='*72}\n")

    def _write_raw(self, text: str):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(text)

    def _ts(self) -> str:
        elapsed = time.time() - self._start
        clock = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        return f"{clock}  +{elapsed:7.2f}s"

    def log(self, tag: str, msg: str):
        self._write_raw(f"[{self._ts()}] [{tag:<16}] {msg}\n")

    def log_block(self, tag: str, label: str, content: str):
        self._write_raw(f"[{self._ts()}] [{tag:<16}] ── {label} ────────────────────────\n")
        for line in content.splitlines():
            self._write_raw(f"  {line}\n")
        self._write_raw(f"  {'─'*60}\n")

    def log_json(self, tag: str, label: str, data: Any):
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            text = str(data)
        self.log_block(tag, label, text)


# ── API pública ───────────────────────────────────────────────────────────────

def is_active() -> bool:
    return _logger is not None


def init(log_path: str = "debug.log") -> DebugLogger:
    global _logger
    _logger = DebugLogger(log_path)
    return _logger


def init_if_env():
    """Inicializa si DEEP_DEBUG está seteada (usada por módulos de core)."""
    if os.getenv("DEEP_DEBUG") and not is_active():
        init()


def log(tag: str, msg: str):
    if _logger:
        _logger.log(tag, msg)


def log_block(tag: str, label: str, content: str):
    if _logger:
        _logger.log_block(tag, label, content)


def log_json(tag: str, label: str, data: Any):
    if _logger:
        _logger.log_json(tag, label, data)
