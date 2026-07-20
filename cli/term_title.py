"""Título de la ventana de terminal (secuencia OSC 0): 'deep' en reposo, animado
mientras el agente trabaja. Sirve para ubicar la sesión al minimizar/cambiar de ventana."""
import itertools
import sys
import threading
import time

IDLE_TITLE = "deep"
_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def set_title(text: str):
    sys.stdout.write(f"\033]0;{text}\007")
    sys.stdout.flush()


class TitleAnimator:
    """Hilo daemon que anima el título mientras dura un turno del agente; al
    parar, restaura IDLE_TITLE."""

    def __init__(self, label: str = "deep"):
        self._label = label
        self._stop = False
        self._thread = None

    def start(self):
        self._stop = False
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=1)
        set_title(IDLE_TITLE)

    def _animate(self):
        for frame in itertools.cycle(_FRAMES):
            if self._stop:
                break
            set_title(f"{frame} {self._label}")
            time.sleep(0.08)
