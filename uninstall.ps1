# uninstall.ps1 — Desinstalador de deep CLI para Windows
# Uso:
#   .\uninstall.ps1           # borra el programa, deja tu config/API key
#   .\uninstall.ps1 -Purge    # además borra la config (API key, idioma, historial)

param(
    [switch]$Purge
)

$ErrorActionPreference = "Stop"

$VenvDir    = "$HOME\.local\share\deepseekcli"
$ScriptsDir = "$VenvDir\Scripts"
$ConfigDir  = "$HOME\.config\deep"

function Write-Step($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  ✔ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  deep CLI — desinstalador para Windows" -ForegroundColor Cyan
Write-Host "  ──────────────────────────────────────"
Write-Host ""

$removedSomething = $false

# ── 1. Borrar el entorno virtual ──────────────────────────────────────────────
if (Test-Path $VenvDir) {
    Remove-Item -Recurse -Force $VenvDir
    Write-Ok "Borrado $VenvDir"
    $removedSomething = $true
} else {
    Write-Warn "$VenvDir no existe"
}

# ── 2. Sacar Scripts del PATH de usuario (install.ps1 lo agrega directo) ─────
Write-Step "Limpiando PATH..."
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -and $userPath -like "*$ScriptsDir*") {
    $parts = $userPath -split ";" | Where-Object { $_ -and ($_ -ne $ScriptsDir) }
    $newPath = ($parts -join ";")
    [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Ok "$ScriptsDir sacado del PATH de usuario"
    $removedSomething = $true
} else {
    Write-Warn "$ScriptsDir no estaba en el PATH de usuario"
}

# ── 3. Config (API key, idioma, historial) — opcional, con -Purge ───────────
if ($Purge) {
    if (Test-Path $ConfigDir) {
        Remove-Item -Recurse -Force $ConfigDir
        Write-Ok "Borrado $ConfigDir (API key, idioma, historial)"
        $removedSomething = $true
    }
} elseif (Test-Path $ConfigDir) {
    Write-Warn "Tu config sigue en $ConfigDir (API key, idioma, historial)."
    Write-Host "     Para borrarla también: .\uninstall.ps1 -Purge"
}

Write-Host ""
if ($removedSomething) {
    Write-Host "  ✔ deep desinstalado. Abrí una terminal nueva para que el PATH actualizado tenga efecto." -ForegroundColor Green
} else {
    Write-Host "  No se encontró nada para desinstalar." -ForegroundColor Yellow
}
Write-Host ""
