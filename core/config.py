import json
import os
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


def _add_to_shell(key: str) -> None:
    """Agrega DEEPSEEK_API_KEY al archivo de perfil del shell del usuario."""
    shell = Path(os.environ.get("SHELL", "")).name
    if shell == "zsh":
        candidates = [".zshrc", ".bashrc"]
    else:
        candidates = [".bashrc", ".zshrc"]

    export_line = f'export DEEPSEEK_API_KEY="{key}"'
    marker = "DEEPSEEK_API_KEY"

    for rc_name in candidates:
        rc_file = Path.home() / rc_name
        if not rc_file.exists():
            continue
        content = rc_file.read_text()
        if marker in content:
            # Reemplazar la línea existente
            lines = content.splitlines()
            new_lines = [export_line if marker in l else l for l in lines]
            rc_file.write_text("\n".join(new_lines) + "\n")
        else:
            with rc_file.open("a") as f:
                f.write(f"\n{export_line}\n")
        print(f"   ✅ Exportada en ~/{rc_name}")
        print(f"      Recargá la terminal con: source ~/{rc_name}")
        return

    # Si no existe ningún rc, usar .bashrc y crearlo
    rc_file = Path.home() / ".bashrc"
    with rc_file.open("a") as f:
        f.write(f"\n{export_line}\n")
    print(f"   ✅ Exportada en ~/.bashrc")
    print(f"      Recargá la terminal con: source ~/.bashrc")


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
    _add_to_shell(key)
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
