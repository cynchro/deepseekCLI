# install.ps1 — Instalador de deep CLI para Windows
# Uso:
#   .\install.ps1                          # instala desde el directorio actual
#   .\install.ps1 https://github.com/...  # instala desde una URL de GitHub
#   irm https://.../install.ps1 | iex     # instalación remota (PowerShell 5+)

$ErrorActionPreference = "Stop"

$VenvDir   = "$HOME\.local\share\deepseekcli"
$ScriptsDir = "$VenvDir\Scripts"
$RepoUrl   = "git+https://github.com/cynchro/deepseekCLI.git"

function Write-Step($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  ✔ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  ✖ $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  deep CLI — instalador para Windows" -ForegroundColor Cyan
Write-Host "  ────────────────────────────────────"
Write-Host ""

# ── 1. Verificar Python 3.9+ ──────────────────────────────────────────────────
Write-Step "Verificando Python..."
try {
    $pyver = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw }
    $parts = ($pyver -replace "Python ", "").Split(".")
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 9)) {
        Write-Fail "Se requiere Python 3.9+. Versión encontrada: $pyver"
    }
    Write-Ok $pyver
} catch {
    Write-Fail "Python no encontrado. Instalalo desde https://python.org (marcá 'Add to PATH')"
}

# ── 2. Crear entorno virtual ──────────────────────────────────────────────────
Write-Step "Creando entorno virtual en $VenvDir..."
if (Test-Path $VenvDir) {
    Write-Warn "Ya existe un entorno en $VenvDir, actualizando..."
} else {
    python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "No se pudo crear el entorno virtual" }
}
Write-Ok "Entorno listo"

# ── 3. Actualizar pip ─────────────────────────────────────────────────────────
Write-Step "Actualizando pip..."
& "$ScriptsDir\python.exe" -m pip install --quiet --upgrade pip

# ── 4. Instalar deep ──────────────────────────────────────────────────────────
if ($args[0]) {
    $source = $args[0]
    Write-Step "Instalando desde $source..."
} elseif (Test-Path "pyproject.toml") {
    $source = "."
    Write-Step "Instalando desde directorio actual..."
} else {
    $source = $RepoUrl
    Write-Step "Descargando desde GitHub..."
}

& "$ScriptsDir\pip.exe" install --quiet --force-reinstall $source
if ($LASTEXITCODE -ne 0) { Write-Fail "Error durante la instalación" }
Write-Ok "deep instalado"

# ── 5. Agregar Scripts al PATH de usuario ─────────────────────────────────────
Write-Step "Configurando PATH..."
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -like "*$ScriptsDir*") {
    Write-Ok "$ScriptsDir ya está en PATH"
} else {
    [System.Environment]::SetEnvironmentVariable("PATH", "$ScriptsDir;$userPath", "User")
    Write-Ok "$ScriptsDir agregado al PATH de usuario"
}

# ── 6. Verificar que deep.exe existe ─────────────────────────────────────────
if (-not (Test-Path "$ScriptsDir\deep.exe")) {
    Write-Warn "deep.exe no encontrado en Scripts. Puede necesitar reiniciar la terminal."
}

# ── Listo ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ✔ Instalación completa." -ForegroundColor Green
Write-Host ""
Write-Host "  Próximos pasos:"
Write-Host "  1. Abrí una nueva terminal (para que el PATH tenga efecto)"
Write-Host "  2. Ejecutá: deep"
Write-Host "  3. La primera vez te pedirá tu API key de DeepSeek"
Write-Host "     Obtené una en: https://platform.deepseek.com/api_keys"
Write-Host ""
Write-Host "  O configurá la variable de entorno antes de abrir la terminal:"
Write-Host '  $env:DEEPSEEK_API_KEY = "sk-..."' -ForegroundColor DarkGray
Write-Host ""
