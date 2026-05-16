import itertools
import sys
import threading
import time


class Spinner:
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    TOTAL_PHASES = 8
    PHASE_MAP = {
        "FASE 1": (1, "Planificando arquitectura   "),
        "FASE 2": (2, "Generando código            "),
        "FASE 3": (3, "Escribiendo archivos        "),
        "FASE 4": (4, "Evaluando calidad           "),
        "FASE 5": (5, "Analizando experiencia      "),
        "FASE 6": (6, "Reflexionando               "),
        "FASE 7": (7, "Metacognición               "),
        "FASE 8": (8, "Detectando patrones         "),
        "REVISIÓN":    (6, "Revisando problemas        "),
        "RE-EVALUANDO": (8, "Re-evaluando               "),
    }

    def __init__(self):
        self._phase_num = 0
        self._phase_name = "Conectando con DeepSeek     "
        self._buffered_files: list = []
        self._stop = False
        self._thread = None
        self._start_time = None
        self._lock = threading.Lock()

    def start(self):
        self._start_time = time.time()
        self._stop = False
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def notify(self, message: str):
        for key, (num, name) in self.PHASE_MAP.items():
            if key in message:
                with self._lock:
                    self._phase_num = num
                    self._phase_name = name
                return
        if "💾" in message or message.startswith("/"):
            with self._lock:
                self._buffered_files.append(message.strip())

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=1)
        sys.stdout.write("\r" + " " * 72 + "\r")
        sys.stdout.flush()

    def flush_files(self):
        for line in self._buffered_files:
            print(f"   💾 {line}")

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop:
                break
            with self._lock:
                num, name = self._phase_num, self._phase_name
            elapsed = int(time.time() - self._start_time)
            pct = int(num / self.TOTAL_PHASES * 100)
            bar = self._bar(pct)
            sys.stdout.write(f"\r  {frame}  {bar}  {pct:3d}%  {name}  {elapsed}s")
            sys.stdout.flush()
            time.sleep(0.08)

    @staticmethod
    def _bar(pct: int, width: int = 20) -> str:
        filled = int(width * pct / 100)
        return f"[{'█' * filled}{'░' * (width - filled)}]"
