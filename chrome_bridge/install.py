"""Registro del native host de `chrome_bridge/` en los navegadores Chromium
instalados. Ver `doc/arquitectura.md` / plan de la extensión para el contexto
completo — acá solo la mecánica de instalación.

EXTENSION_ID está fijado por el campo "key" de `extension/manifest.json`
(generado una sola vez al construir la extensión, no por cada developer —
Chrome deriva el ID determinísticamente de esa clave pública incluso al
"Cargar descomprimida"). Si algún día se regenera esa key, hay que actualizar
este valor en el mismo commit.
"""
import json
import platform
import stat
import sys
from pathlib import Path

EXTENSION_ID = "hgjekbbfnfopnhdgjgmmlncejahjbmcp"
HOST_NAME = "com.deepseekcli.browser_bridge"

_DEEP_CONFIG_DIR = Path.home() / ".config" / "deep" / "chrome_bridge"

# Directorios de configuración por navegador (Linux). Cada uno recibe su
# propio NativeMessagingHosts/<HOST_NAME>.json si el directorio del navegador
# existe (o sea, si ese navegador está instalado).
_BROWSER_DIRS = {
    "chrome": Path.home() / ".config" / "google-chrome",
    "chromium": Path.home() / ".config" / "chromium",
    "opera": Path.home() / ".config" / "opera",
    "edge": Path.home() / ".config" / "microsoft-edge",
    "vivaldi": Path.home() / ".config" / "vivaldi",
    "brave": Path.home() / ".config" / "BraveSoftware" / "Brave-Browser",
}


def detected_browsers() -> list[Path]:
    """Directorios base de navegadores Chromium instalados en esta máquina.

    Solo Linux por ahora — Windows/Mac registran Native Messaging Hosts en
    ubicaciones distintas (registro de Windows / ~/Library en Mac); se deja
    explícitamente sin soportar en vez de fallar en silencio."""
    if platform.system() != "Linux":
        return []
    return [d for d in _BROWSER_DIRS.values() if d.is_dir()]


def _write_launcher(port: int) -> Path:
    """Escribe el script que Chrome ejecuta como native host. Native
    Messaging exige un ejecutable real en "path" del manifest NMH (no sirve
    poner "python script.py" directo), y el puerto va embebido acá en vez de
    en una env var porque Chrome no garantiza heredar el entorno del shell
    del usuario al lanzar el proceso.

    El `cd` al repo (en vez de confiar solo en que `chrome_bridge` esté
    instalado como paquete) es a propósito: Chrome lanza este script con SU
    propio cwd, no el del usuario, y `pip install -e .` no siempre corrió en
    el intérprete que apunta `sys.executable` — con el `cd`, `python -m`
    agrega el repo a sys.path igual, instalado o no."""
    _DEEP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    launcher = _DEEP_CONFIG_DIR / "native_host_launcher.sh"
    repo_root = Path(__file__).resolve().parent.parent
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        f'cd "{repo_root}"\n'
        f'exec "{sys.executable}" -m chrome_bridge.native_host --port {port}\n'
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return launcher


def install(port: int = 8000) -> list[Path]:
    """Escribe el manifest de Native Messaging Host en cada navegador
    detectado. Devuelve las rutas escritas (vacío si no se detectó ningún
    navegador soportado)."""
    launcher = _write_launcher(port)
    manifest = {
        "name": HOST_NAME,
        "description": "deepseekcli Chrome Browser Bridge Native Host",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }
    written = []
    for browser_dir in detected_browsers():
        nmh_dir = browser_dir / "NativeMessagingHosts"
        nmh_dir.mkdir(parents=True, exist_ok=True)
        target = nmh_dir / f"{HOST_NAME}.json"
        target.write_text(json.dumps(manifest, indent=2))
        written.append(target)
    return written
