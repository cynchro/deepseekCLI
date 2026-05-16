import json
import sys
from pathlib import Path

_CONFIG_FILE = Path.home() / ".config" / "deep" / "config.json"


def load_api_key() -> str | None:
    try:
        return json.loads(_CONFIG_FILE.read_text()).get("api_key") or None
    except Exception:
        return None


def save_api_key(key: str) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    try:
        existing = json.loads(_CONFIG_FILE.read_text())
    except Exception:
        pass
    existing["api_key"] = key
    _CONFIG_FILE.write_text(json.dumps(existing, indent=2))
    _CONFIG_FILE.chmod(0o600)


def prompt_and_save() -> str:
    print("\n🔑 No se encontró DEEPSEEK_API_KEY.")
    print("   Obtené tu key en: https://platform.deepseek.com/api_keys")
    print()
    while True:
        try:
            key = input("   Ingresá tu API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n❌ Cancelado.")
            sys.exit(1)
        if key:
            break
        print("   La key no puede estar vacía.")
    if not key.startswith("sk-"):
        print("   ⚠️  La key no empieza con 'sk-'. Guardando igual, pero verificá que sea correcta.")
    save_api_key(key)
    print(f"   ✅ Guardada en {_CONFIG_FILE}")
    print()
    return key


def show_config() -> None:
    key = load_api_key()
    if key:
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        print(f"  API key : {masked}")
        print(f"  Archivo : {_CONFIG_FILE}")
    else:
        print("  No hay API key guardada.")
        print(f"  Usá 'deep config set-key' para guardar una.")
