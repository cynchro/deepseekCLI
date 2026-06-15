"""
Validación del proyecto en disco después de build/update.
Detecta problemas frecuentes del código generado y aplica correcciones seguras.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from core.writer import FileWriter

_IMPORT_RE = re.compile(r"""from\s+['"](\.\.?/[^'"]+)['"]""")
# require/include con ruta estática vía __DIR__ . '...'. Exige que la cadena sea el
# final del statement (opcional ')' y ';'), para no matchear concatenaciones
# dinámicas con variables (... . $class . '.php').
_PHP_INCLUDE_RE = re.compile(
    r"""(?:require|require_once|include|include_once)\s*\(?\s*"""
    r"""__DIR__\s*\.\s*['"]([^'"]+)['"]\s*\)?\s*;""",
    re.IGNORECASE,
)
_DOCKER_COPY_BAD = re.compile(
    r"^COPY\s+(?:(?!\./)\S+\s+){2,}\./\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_NPM_CI = re.compile(r"\bnpm\s+ci\b")


def analyze_project(project_dir: Path, response_text: Optional[str] = None) -> Dict:
    """Devuelve issues, warnings y metadatos. No modifica archivos."""
    project_dir = Path(project_dir)
    issues: List[str] = []
    warnings: List[str] = []

    if not project_dir.is_dir():
        return {"issues": ["Directorio de proyecto no existe"], "warnings": [], "ok": False}

    issues.extend(_check_ts_imports(project_dir))
    issues.extend(_check_docker_npm(project_dir))
    warnings.extend(_check_compose_version(project_dir))

    # Referencias PHP (require/include) a archivos que no existen. missing_refs
    # guarda las rutas-objetivo para que 'deep fix' las pueda regenerar.
    php_issues, missing_refs = _check_php_includes(project_dir)
    issues.extend(php_issues)

    if response_text:
        issues.extend(_check_response_coverage(project_dir, response_text))
    else:
        resp = project_dir / ".deep" / "RESPONSE.md"
        if resp.exists():
            try:
                issues.extend(_check_response_coverage(project_dir, resp.read_text(encoding="utf-8")))
            except OSError:
                pass

    if response_text and response_text.strip() and not _response_looks_complete(response_text):
        warnings.append("La respuesta del modelo puede estar truncada (sin cierre de bloque ```)")

    ok = len(issues) == 0
    return {"issues": issues, "warnings": warnings, "ok": ok,
            "missing_refs": missing_refs, "project_dir": str(project_dir)}


def apply_remediations(project_dir: Path, report: Optional[Dict] = None) -> List[str]:
    """Correcciones automáticas seguras. Devuelve mensajes de lo aplicado."""
    project_dir = Path(project_dir)
    report = report or analyze_project(project_dir)
    fixes: List[str] = []

    if _needs_lockfile(project_dir):
        if _run_npm_install(project_dir):
            fixes.append("Generado package-lock.json (npm install)")
        else:
            fixes.append("No se pudo ejecutar npm install (¿npm instalado?)")

    return fixes


def merge_into_heuristics(heuristics: Dict, report: Dict) -> Dict:
    """Añade issues del postcheck al dict de heurísticas existente."""
    extra = list(report.get("issues", []))
    if not extra:
        return heuristics
    combined = list(heuristics.get("heuristic_issues", [])) + extra
    heuristics = dict(heuristics)
    heuristics["heuristic_issues"] = combined
    heuristics["postcheck_ok"] = report.get("ok", False)
    heuristics["structural_ok"] = len(combined) == 0 and heuristics.get("files_count", 0) >= 2
    return heuristics


def format_report(report: Dict, fixes: Optional[List[str]] = None) -> str:
    lines: List[str] = []
    for w in report.get("warnings", []):
        lines.append(f"  ⚠️  {w}")
    for i in report.get("issues", []):
        lines.append(f"  ⚠️  {i}")
    for f in fixes or []:
        lines.append(f"  🔧 {f}")
    return "\n".join(lines)


# ── checks ───────────────────────────────────────────────────────────────────


def _check_ts_imports(project_dir: Path) -> List[str]:
    issues = []
    for ts_file in project_dir.rglob("*.ts"):
        if "node_modules" in ts_file.parts or ".deep" in ts_file.parts:
            continue
        try:
            text = ts_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for spec in _IMPORT_RE.findall(text):
            if not _resolve_import(ts_file, spec):
                rel = ts_file.relative_to(project_dir)
                issues.append(f"Import roto en {rel}: '{spec}' no existe")
    return issues


def _resolve_import(from_file: Path, spec: str) -> bool:
    base = (from_file.parent / spec).resolve()
    for candidate in (
        base.with_suffix(".ts"),
        base.with_suffix(".tsx"),
        base / "index.ts",
        base / "index.tsx",
        base,
    ):
        if candidate.is_file():
            return True
    return False


def _check_php_includes(project_dir: Path):
    """Detecta require/include a archivos inexistentes (ruta estática vía __DIR__).
    Devuelve (issues, missing_refs) donde missing_refs son rutas relativas al
    proyecto que deberían existir y no existen."""
    issues: List[str] = []
    missing_refs: List[str] = []
    seen = set()
    for php_file in project_dir.rglob("*.php"):
        if "vendor" in php_file.parts or ".deep" in php_file.parts:
            continue
        try:
            text = php_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for spec in _PHP_INCLUDE_RE.findall(text):
            target = (php_file.parent / spec.lstrip("/")).resolve()
            if target.is_file():
                continue
            try:
                rel = str(target.relative_to(project_dir.resolve()))
            except ValueError:
                # referencia fuera del proyecto: no la regeneramos, solo avisamos
                rel = None
            src_rel = php_file.relative_to(project_dir)
            issues.append(f"Referencia rota en {src_rel}: '{spec}' no existe")
            if rel and rel not in seen:
                seen.add(rel)
                missing_refs.append(rel)
    return issues, missing_refs


def _check_docker_npm(project_dir: Path) -> List[str]:
    issues = []
    has_lock = (project_dir / "package-lock.json").is_file()
    for dockerfile in list(project_dir.glob("Dockerfile*")) + list(project_dir.glob("**/Dockerfile*")):
        if "node_modules" in dockerfile.parts:
            continue
        try:
            content = dockerfile.read_text(encoding="utf-8")
        except OSError:
            continue
        if _NPM_CI.search(content) and not has_lock:
            rel = dockerfile.relative_to(project_dir)
            issues.append(
                f"{rel} usa `npm ci` pero falta package-lock.json en el proyecto"
            )
        if _DOCKER_COPY_BAD.search(content):
            rel = dockerfile.relative_to(project_dir)
            issues.append(
                f"{rel}: COPY con varias carpetas a `./` aplasta la estructura; usá `COPY dir ./dir` por carpeta"
            )
    return issues


def _check_compose_version(project_dir: Path) -> List[str]:
    warnings = []
    for compose in project_dir.glob("docker-compose*.yml"):
        try:
            if re.search(r"^\s*version\s*:", compose.read_text(encoding="utf-8"), re.MULTILINE):
                warnings.append(f"{compose.name}: clave `version` obsoleta en Compose v2")
        except OSError:
            pass
    return warnings


def _check_response_coverage(project_dir: Path, response_text: str) -> List[str]:
    issues = []
    blocks = FileWriter._extract_named_blocks(response_text)
    if not blocks:
        return issues
    expected = {p.lstrip("/") for p, _ in blocks if not p.endswith(".md")}
    on_disk = {
        str(f.relative_to(project_dir))
        for f in project_dir.rglob("*")
        if f.is_file() and ".deep" not in f.parts and f.suffix in (".ts", ".tsx", ".js", ".py", ".json")
    }
    missing = sorted(expected - on_disk)
    if missing:
        preview = ", ".join(missing[:8])
        suffix = f" (+{len(missing) - 8} más)" if len(missing) > 8 else ""
        issues.append(f"Archivos en la respuesta no escritos a disco: {preview}{suffix}")
    return issues


def _response_looks_complete(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return True
    if stripped.count("```") % 2 == 0:
        return True
    return stripped.endswith("```")


def _needs_lockfile(project_dir: Path) -> bool:
    if (project_dir / "package-lock.json").is_file():
        return False
    if not (project_dir / "package.json").is_file():
        return False
    for dockerfile in project_dir.rglob("Dockerfile*"):
        if "node_modules" in dockerfile.parts:
            continue
        try:
            if _NPM_CI.search(dockerfile.read_text(encoding="utf-8")):
                return True
        except OSError:
            pass
    return False


def _run_npm_install(project_dir: Path, timeout: int = 180) -> bool:
    npm = _find_npm()
    if not npm:
        return False
    try:
        r = subprocess.run(
            [npm, "install", "--package-lock-only"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode == 0 and (project_dir / "package-lock.json").is_file():
            return True
        r2 = subprocess.run(
            [npm, "install"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r2.returncode == 0 and (project_dir / "package-lock.json").is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _find_npm() -> Optional[str]:
    from shutil import which
    return which("npm")
