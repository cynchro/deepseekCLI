#!/usr/bin/env bash
# Desinstala deep CLI: borra el venv y el wrapper que creó install.sh.
#
# Uso:
#   bash uninstall.sh          → borra el programa, deja tu config/API key
#   bash uninstall.sh --purge  → además borra ~/.config/deep (API key, idioma, historial)

set -euo pipefail

VENV_DIR="$HOME/.local/share/deepseekcli"
BIN_PATH="$HOME/.local/bin/deep"
CONFIG_DIR="$HOME/.config/deep"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${GREEN}▸${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
section() { echo -e "\n${CYAN}$*${NC}"; }

section "  deep CLI — desinstalador"

PURGE=false
[[ "${1:-}" == "--purge" ]] && PURGE=true

removed_something=false

# ── Wrapper en ~/.local/bin/deep ──────────────────────────────────────────────

if [[ -f "$BIN_PATH" || -L "$BIN_PATH" ]]; then
    rm -f "$BIN_PATH"
    info "Borrado $BIN_PATH"
    removed_something=true
else
    warn "$BIN_PATH no existe (¿ya estaba desinstalado?)"
fi

# ── Entorno virtual aislado ────────────────────────────────────────────────────

if [[ -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_DIR"
    info "Borrado $VENV_DIR"
    removed_something=true
else
    warn "$VENV_DIR no existe"
fi

# ── Config (API key, idioma, historial) — opcional, con --purge ─────────────

if $PURGE; then
    if [[ -d "$CONFIG_DIR" ]]; then
        rm -rf "$CONFIG_DIR"
        info "Borrado $CONFIG_DIR (API key, idioma, historial)"
        removed_something=true
    fi
elif [[ -d "$CONFIG_DIR" ]]; then
    warn "Tu config sigue en $CONFIG_DIR (API key, idioma, historial)."
    echo "     Para borrarla también: bash uninstall.sh --purge"
fi

# ── Instalación alternativa vía PyPI (pip install deepseek-builder) ─────────

if command -v pip3 &>/dev/null && pip3 show deepseek-builder &>/dev/null; then
    warn "Además encontramos deepseek-builder instalado vía pip (fuera del venv aislado)."
    echo "     Para sacarlo: pip3 uninstall deepseek-builder"
fi

echo ""
if $removed_something; then
    echo -e "${GREEN}✓ deep desinstalado.${NC}"
else
    echo -e "${YELLOW}No se encontró nada para desinstalar.${NC}"
fi
echo ""
echo "  Nota sobre el PATH: si agregaste a mano la línea"
echo '    export PATH="$HOME/.local/bin:$PATH"'
echo "  a tu ~/.bashrc o ~/.zshrc durante la instalación, no la tocamos automáticamente:"
echo "  ese directorio (~/.local/bin) lo comparten muchas otras herramientas (pip install"
echo "  --user, etc.), así que no es seguro borrar la línea sin saber qué más depende de"
echo "  ella. Si estás seguro de que nada más la necesita, sacala vos manualmente."
echo ""
