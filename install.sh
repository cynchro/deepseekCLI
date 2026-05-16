#!/usr/bin/env bash
# Instala deep CLI sin tocar el Python del sistema.
# Crea un venv aislado en ~/.local/share/deepseekcli y un wrapper en ~/.local/bin/deep
#
# Uso:
#   bash install.sh                              → instala desde el directorio actual
#   bash install.sh https://github.com/tu/repo  → instala desde GitHub
#   curl -fsSL https://.../install.sh | bash     → instalación remota

set -euo pipefail

REPO_URL="${1:-}"
VENV_DIR="$HOME/.local/share/deepseekcli"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/deep"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${GREEN}▸${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✗${NC}  $*" >&2; exit 1; }
section() { echo -e "\n${CYAN}$*${NC}"; }

# ── Verificaciones ────────────────────────────────────────────────────────────

command -v python3 &>/dev/null || error "Python 3 no encontrado. Instala Python 3.9+ primero."

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
[[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 9 ]] \
    || error "Se requiere Python 3.9+. Versión actual: $PY_MAJOR.$PY_MINOR"

# ── Resolver fuente ───────────────────────────────────────────────────────────

section "  deep CLI — instalador"

if [[ -n "$REPO_URL" ]]; then
    # Clonar desde GitHub/GitLab
    command -v git &>/dev/null || error "git no encontrado. Instálalo con: sudo apt install git"
    TMP_DIR=$(mktemp -d)
    trap 'rm -rf "$TMP_DIR"' EXIT
    info "Clonando $REPO_URL ..."
    git clone --depth=1 "$REPO_URL" "$TMP_DIR/repo" -q
    INSTALL_SRC="$TMP_DIR/repo"
elif [[ -f "$(dirname "$0")/pyproject.toml" ]]; then
    # Instalar desde el directorio del script
    INSTALL_SRC="$(cd "$(dirname "$0")" && pwd)"
    info "Fuente: $INSTALL_SRC"
else
    error "No se encontró pyproject.toml. Pasa una URL de GitHub como primer argumento."
fi

# ── Crear / actualizar venv aislado ──────────────────────────────────────────

if [[ -d "$VENV_DIR" ]]; then
    info "Actualizando entorno existente en $VENV_DIR"
else
    info "Creando entorno virtual en $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

info "Instalando dependencias..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet "$INSTALL_SRC"

# ── Crear wrapper en ~/.local/bin/deep ───────────────────────────────────────

mkdir -p "$BIN_DIR"

cat > "$BIN_PATH" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/deep" "\$@"
EOF
chmod +x "$BIN_PATH"

# ── Verificar que ~/.local/bin esté en PATH ───────────────────────────────────

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR no está en tu PATH."
    echo ""
    echo "  Agrega esta línea a ~/.bashrc o ~/.zshrc:"
    echo ""
    echo '    export PATH="$HOME/.local/bin:$PATH"'
    echo ""
    echo "  Luego recarga la terminal con:  source ~/.bashrc"
fi

# ── Listo ─────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}✓ deep instalado en $BIN_PATH${NC}"
echo ""
echo "  Configura tu API key (una sola vez):"
echo ""
echo '    echo '\''export DEEPSEEK_API_KEY=tu_key_aqui'\'' >> ~/.bashrc'
echo '    source ~/.bashrc'
echo ""
echo "  Comandos:"
echo "    deep                    → REPL interactivo"
echo '    deep build "mi tarea"   → genera un proyecto'
echo "    deep balance            → muestra tu crédito"
echo ""
