"""
Verifica en PyPI si hay una versión nueva de deepseek-builder.
Corre en background y cachea el resultado 24 horas para no agregar latencia.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_PACKAGE_NAME = "deepseek-builder"
_PYPI_URL = "https://pypi.org/pypi/deepseek-builder/json"
_CACHE_FILE = Path.home() / ".config" / "deep" / "update_check.json"
_CACHE_TTL_HOURS = 24


def _installed_version() -> tuple[str | None, bool]:
    """Devuelve (version, via_pip). via_pip=False significa que corre desde un clon git."""
    try:
        from importlib.metadata import version
        return version(_PACKAGE_NAME), True
    except Exception:
        pass
    try:
        import re
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            return m.group(1), False
    except Exception:
        pass
    return None, False


def _is_git_repo() -> bool:
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=Path(__file__).parent.parent,
            capture_output=True, text=True, timeout=2,
        )
        return result.returncode == 0
    except Exception:
        return False


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict):
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _fetch_latest() -> str | None:
    try:
        import urllib.request
        with urllib.request.urlopen(_PYPI_URL, timeout=3) as resp:
            return json.loads(resp.read())["info"]["version"]
    except Exception:
        return None


def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


class _UpdateChecker:
    def __init__(self):
        self._notice: str | None = None
        self._ready = threading.Event()

    def _run(self, installed: str, via_pip: bool):
        cache = _load_cache()
        latest = cache.get("latest_version")
        last_check = cache.get("last_check")

        needs_fetch = True
        if latest and last_check:
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_check)).total_seconds()
                if elapsed < _CACHE_TTL_HOURS * 3600:
                    needs_fetch = False
            except Exception:
                pass

        if needs_fetch:
            fetched = _fetch_latest()
            if fetched:
                latest = fetched
                _save_cache({"last_check": datetime.now(timezone.utc).isoformat(), "latest_version": latest})

        if latest and _ver_tuple(latest) > _ver_tuple(installed):
            if via_pip:
                update_cmd = f"pip install --upgrade {_PACKAGE_NAME}"
            elif _is_git_repo():
                update_cmd = "git pull"
            else:
                update_cmd = f"pip install --upgrade {_PACKAGE_NAME}"
            self._notice = (
                f"\n  \033[33m⚡ Nueva versión disponible: \033[1m{latest}\033[0m\033[33m"
                f"  (tienes {installed})\033[0m\n"
                f"  \033[90mActualiza con: {update_cmd}\033[0m\n"
            )
        self._ready.set()

    def get(self, timeout: float = 1.5) -> str | None:
        self._ready.wait(timeout=timeout)
        return self._notice


def start() -> _UpdateChecker:
    """Lanza el chequeo en background y devuelve un objeto del que se puede leer el resultado."""
    checker = _UpdateChecker()
    installed, via_pip = _installed_version()
    if installed:
        t = threading.Thread(target=checker._run, args=(installed, via_pip), daemon=True)
        t.start()
    else:
        checker._ready.set()
    return checker
