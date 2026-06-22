import json
import os
import platform
import subprocess
import sys
from pathlib import Path

_CONFIG_FILE = Path.home() / ".config" / "deep" / "config.json"

_LANGUAGES = {
    "1": ("es", "Español"),
    "2": ("en", "English"),
    "3": ("pt", "Português"),
    "4": ("zh", "中文"),
    "5": ("fr", "Français"),
    "6": ("de", "Deutsch"),
}

_LANG_INSTRUCTIONS = {
    "es": "Responde siempre en español.",
    "en": "Always respond in English.",
    "pt": "Responda sempre em português.",
    "zh": "请始终用中文回复。",
    "fr": "Réponds toujours en français.",
    "de": "Antworte immer auf Deutsch.",
}


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


def load_language() -> str | None:
    """Returns stored language code, or None if never configured."""
    try:
        return json.loads(_CONFIG_FILE.read_text()).get("language") or None
    except Exception:
        return None


def save_language(lang: str) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    try:
        existing = json.loads(_CONFIG_FILE.read_text())
    except Exception:
        pass
    existing["language"] = lang
    _CONFIG_FILE.write_text(json.dumps(existing, indent=2))


def get_language_instruction() -> str:
    """Returns a sentence to inject in system prompts enforcing the saved language."""
    lang = load_language() or "es"
    return _LANG_INSTRUCTIONS.get(lang, _LANG_INSTRUCTIONS["es"])


def prompt_and_save_language() -> str:
    """Interactive language picker. Returns the chosen language code."""
    from core.i18n import t
    print(t("lang.picker.title"))
    for key, (code, name) in _LANGUAGES.items():
        print(f"   {key}. {name}")
    print()
    while True:
        try:
            choice = input(t("lang.picker.option")).strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print()
            return "es"
        if choice in _LANGUAGES:
            lang, name = _LANGUAGES[choice]
            save_language(lang)
            print(t("lang.saved", name=name))
            return lang
        print(t("lang.picker.invalid"))


def _add_to_shell(key: str) -> None:
    """Agrega DEEPSEEK_API_KEY al perfil del shell (Unix) o variables de entorno (Windows)."""
    if platform.system() == "Windows":
        _add_to_shell_windows(key)
    else:
        _add_to_shell_unix(key)


def _add_to_shell_windows(key: str) -> None:
    result = subprocess.run(
        ["setx", "DEEPSEEK_API_KEY", key],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("   ✅ Variable de entorno de usuario guardada en Windows")
        print("      Abrí una nueva terminal para que tenga efecto")
    else:
        print(f"   ⚠️  No se pudo guardar con setx: {result.stderr.strip()}")
        print(f"      Guardala manualmente: setx DEEPSEEK_API_KEY \"{key}\"")

    # También intenta escribir al perfil de PowerShell si existe
    ps_profile = Path.home() / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    ps_profile_legacy = Path.home() / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"
    for profile in (ps_profile, ps_profile_legacy):
        if profile.exists():
            content = profile.read_text(encoding="utf-8")
            line = f'$env:DEEPSEEK_API_KEY = "{key}"'
            if "DEEPSEEK_API_KEY" in content:
                lines = content.splitlines()
                new_lines = [line if "DEEPSEEK_API_KEY" in l else l for l in lines]
                profile.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            else:
                with profile.open("a", encoding="utf-8") as f:
                    f.write(f"\n{line}\n")
            print(f"   ✅ También agregada en {profile}")
            break


def _add_to_shell_unix(key: str) -> None:
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
            lines = content.splitlines()
            new_lines = [export_line if marker in l else l for l in lines]
            rc_file.write_text("\n".join(new_lines) + "\n")
        else:
            with rc_file.open("a") as f:
                f.write(f"\n{export_line}\n")
        print(f"   ✅ Exportada en ~/{rc_name}")
        print(f"      Recargá la terminal con: source ~/{rc_name}")
        return

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
    from core.i18n import t
    key = load_api_key()
    if key:
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        print(t("config.api_key", masked=masked))
        print(t("config.file", path=_CONFIG_FILE))
    else:
        print(t("config.nokey"))
        print(t("config.nokey.hint"))
    lang = load_language()
    lang_name = next((n for _, (c, n) in _LANGUAGES.items() if c == lang), lang or "Español")
    print(t("config.lang", name=lang_name, code=lang or "es"))
