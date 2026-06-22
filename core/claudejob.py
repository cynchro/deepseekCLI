"""
claudejob — capa de orquestación donde Claude (u otro arquitecto externo) planifica
y DeepSeek construye + corrige.

Este módulo es PURO: solo parsea el archivo de job, valida, genera plantillas y
maneja el estado por módulo en disco. No hace llamadas a la API ni toca el core.
La orquestación (que reusa DeepSeekLearningSystem) vive en cli/commands.py.

Contrato de archivos:
  .deep/job.md                      → spec inmutable que escribe el arquitecto (Claude)
  .deep/claudejob/state/<mod>.json  → estado de cada módulo construido por DeepSeek
  review.md                         → correcciones efímeras que escribe Claude (se consumen)
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# ── Parsing ──────────────────────────────────────────────────────────────────

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3 = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE)

# Convención del template: `- archivo <ruta>: <detalle>`.
_FILE_BULLET = re.compile(r"^archivo\s+(\S+?)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
# Fallback: cualquier token con pinta de ruta+extensión (la extensión arranca con
# letra para no confundir versiones tipo "3.0.0").
_PATH_TOKEN = re.compile(r"[\w./-]+\.[A-Za-z][A-Za-z0-9]{0,7}")


def _split_by(pattern: re.Pattern, text: str) -> List[Dict]:
    """Parte el texto en bloques {name, body} según un patrón de heading."""
    blocks: List[Dict] = []
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append({"name": m.group(1).strip(), "body": text[start:end].strip()})
    return blocks


def _sections(text: str) -> Dict[str, str]:
    """Mapea cada sección `## NOMBRE` a su cuerpo. Tolerante a mayúsculas/acentos del nombre."""
    return {b["name"].upper(): b["body"] for b in _split_by(_H2, text)}


def _bullets(body: str) -> List[str]:
    return [m.group(1).strip() for m in _BULLET.finditer(body)]


def _title(text: str) -> str:
    m = _H1.search(text)
    if not m:
        return "job"
    raw = m.group(1).strip()
    # admite "# JOB: Mi proyecto" o "# Mi proyecto"
    return re.sub(r"^job\s*:\s*", "", raw, flags=re.IGNORECASE).strip() or "job"


def parse_job(text: str) -> Dict:
    """Parsea un job.md. Devuelve title, plan, rules, modules y una lista de errors.

    Parser tolerante: los nombres de sección se comparan en mayúsculas, así que
    `## TASKS`, `## Tasks` y `## tasks` son equivalentes. Si algo falta, se reporta
    en `errors` en vez de explotar."""
    secs = _sections(text)
    tasks_body = secs.get("TASKS", "")
    modules = _split_by(_H3, tasks_body)

    errors: List[str] = []
    if "TASKS" not in secs:
        errors.append("Falta la sección `## TASKS` con los módulos a construir.")
    elif not modules:
        errors.append("La sección `## TASKS` no tiene módulos. Agregá uno o más `### <nombre>`.")
    if "PLAN" not in secs:
        errors.append("Falta la sección `## PLAN` con la arquitectura general.")

    return {
        "title": _title(text),
        "plan": secs.get("PLAN", ""),
        "rules": _bullets(secs.get("RULES", "")),
        "modules": modules,
        "errors": errors,
    }


def parse_corrections(text: str) -> Dict:
    """Parsea un review.md. Las correcciones van bajo `## CORRECTIONS`, un `### <módulo>`
    por cada uno. Devuelve modules (lista de {name, body, items}) y errors."""
    secs = _sections(text)
    body = secs.get("CORRECTIONS", "")
    modules = _split_by(_H3, body)
    for mod in modules:
        mod["items"] = _bullets(mod["body"])

    errors: List[str] = []
    if "CORRECTIONS" not in secs:
        errors.append("Falta la sección `## CORRECTIONS`. Claude debe escribir las correcciones ahí.")
    elif not modules:
        errors.append("`## CORRECTIONS` no tiene módulos (`### <nombre>`). Nada que corregir.")
    return {"modules": modules, "errors": errors}


def module_files(module: Dict) -> List[Dict]:
    """Extrae los archivos que el arquitecto especificó en un módulo del job.md,
    para construir un plan ESTRUCTURADO sin que DeepSeek vuelva a planificar.

    Convención preferida (la del template): bullets `archivo <ruta>: <detalle>`.
    Si un bullet no la sigue, se intenta detectar un token con pinta de ruta.
    Devuelve [{path, description}] sin duplicados; vacío si no hay archivos
    reconocibles (en ese caso el caller cae al plan de texto sembrado)."""
    files: List[Dict] = []
    seen = set()
    for bullet in _bullets(module.get("body", "")):
        m = _FILE_BULLET.match(bullet)
        if m:
            path, desc = m.group(1), (m.group(2).strip() or bullet)
        else:
            tok = _PATH_TOKEN.search(bullet)
            if not tok:
                continue
            path, desc = tok.group(0), bullet
        path = path.strip().lstrip("/").replace("\\", "/")
        if not path or path in seen or ".." in path.split("/"):
            continue
        seen.add(path)
        files.append({"path": path, "description": desc})
    return files


# ── Plantilla ────────────────────────────────────────────────────────────────

JOB_TEMPLATE = """# JOB: {title}

## PLAN
<!-- Arquitectura general del proyecto. Lo escribe el arquitecto (Claude).
     DeepSeek usa esto como plan y NO vuelve a planificar. -->

## RULES
<!-- Restricciones que DeepSeek respeta en cada módulo. Las de abajo reducen la
     invención; agregá las tuyas (stack, convenciones, etc.). -->
- No agregar dependencias que no estén indicadas en el PLAN o en el módulo.
- No crear archivos que no estén mencionados en TASKS.
- Si falta información para implementar algo, dejar un TODO explícito — NO inventar.
- Respetar exactamente las rutas y firmas de funciones que indique cada módulo.

## TASKS
<!-- Un `### <módulo>` por cada pieza a construir. DeepSeek construye uno por uno.
     Cuanto más concreto (rutas de archivo, firmas, dependencias, esquemas),
     menos margen de invención. -->
### modulo-ejemplo
- archivo ejemplo/main.py: función run() -> None
- subtarea concreta con su detalle
"""


def job_template(title: str = "mi-proyecto") -> str:
    return JOB_TEMPLATE.format(title=title)


# ── Estado por módulo ────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-") or "modulo"


def state_dir(project_dir: Path) -> Path:
    return Path(project_dir) / ".deep" / "claudejob" / "state"


def save_module_state(project_dir: Path, module: str, result: Dict) -> Path:
    """Guarda el resultado del build de un módulo para permitir builds incrementales."""
    d = state_dir(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_slug(module)}.json"
    payload = {
        "module": module,
        "success": bool(result.get("success")),
        "files_written": result.get("files_written", []),
        "outcome": result.get("outcome", ""),
        "timestamp": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_module_state(project_dir: Path, module: str) -> Optional[Dict]:
    path = state_dir(project_dir) / f"{_slug(module)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_all_states(project_dir: Path) -> List[Dict]:
    d = state_dir(project_dir)
    if not d.is_dir():
        return []
    states = []
    for f in sorted(d.glob("*.json")):
        try:
            states.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return states


# ── Render del review (lo que el usuario pasa a Claude) ──────────────────────

def _relative_code_files(paths: List[str], project_dir: Path) -> List[str]:
    """Normaliza rutas a relativas, descartando metadatos de .deep y RESPONSE.md."""
    out = []
    for p in paths:
        try:
            rel = Path(p).resolve().relative_to(Path(project_dir).resolve())
        except (ValueError, OSError):
            rel = Path(p)
        if ".deep" in rel.parts or rel.name == "RESPONSE.md":
            continue
        out.append(str(rel))
    return sorted(set(out))


# Directorios/artefactos que no son código generado y solo agregan ruido al review.
_IGNORED_DIRS = {".deep", ".git", "__pycache__", "node_modules", ".venv", "venv",
                 "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea"}
_IGNORED_SUFFIXES = (".pyc", ".pyo", ".log")


def _files_on_disk(project_dir: Path) -> List[str]:
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        return []
    files = []
    for p in project_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(project_dir)
        if _IGNORED_DIRS.intersection(rel.parts) or rel.suffix in _IGNORED_SUFFIXES:
            continue
        files.append(str(rel))
    return sorted(files)


def render_review(project_dir: Path, job: Dict) -> str:
    """Genera el texto que el usuario pipea a Claude para que revise el proyecto.
    Muestra, por módulo, lo PEDIDO (TASKS) frente a los archivos que DeepSeek
    construyó, más el inventario completo en disco — para detectar invención
    (archivos o dependencias que nadie pidió). Claude lee los archivos directamente."""
    project_dir = Path(project_dir)
    states = {s["module"]: s for s in load_all_states(project_dir)}
    on_disk = _files_on_disk(project_dir)
    tracked = set()
    for st in states.values():
        tracked.update(_relative_code_files(st.get("files_written", []), project_dir))
    untracked = [f for f in on_disk if f not in tracked]

    lines = [
        f"# REVIEW REQUEST: {job.get('title', 'job')}",
        "",
        "Sos el arquitecto. Revisá el proyecto construido por DeepSeek en este directorio",
        "(podés leer los archivos directamente). Buscá:",
        "- problemas de ARQUITECTURA y diseño (no de sintaxis, de eso se encarga DeepSeek);",
        "- INVENCIÓN: archivos, dependencias o comportamiento que NO pediste en TASKS.",
        "",
        "Devolvé SOLO un bloque con este formato, un `### <módulo>` por cada módulo a corregir:",
        "",
        "```markdown",
        "## CORRECTIONS",
        "### <nombre-del-módulo>",
        "- qué está mal y cómo debería quedar",
        "```",
        "",
        "Si un módulo está bien, no lo incluyas.",
        "",
        "## MÓDULOS — pedido vs. construido",
    ]
    if not job.get("modules"):
        lines.append("(el job no tiene módulos)")
    for mod in job.get("modules", []):
        st = states.get(mod["name"])
        lines.append(f"### {mod['name']}")
        lines.append("**Pedido (TASKS):**")
        lines.append(mod["body"] or "(sin detalle)")
        if st:
            flag = "ok" if st.get("success") else "revisar"
            built = _relative_code_files(st.get("files_written", []), project_dir)
            lines.append(f"**Construido por DeepSeek — {flag}:**")
            lines.extend(f"- {f}" for f in built) if built else lines.append("- (ningún archivo)")
        else:
            lines.append("_(módulo todavía no construido)_")
        lines.append("")

    lines.append("## ARCHIVOS EN DISCO (inventario completo)")
    lines.extend(f"- {f}" for f in on_disk) if on_disk else lines.append("(vacío)")
    if untracked:
        lines.append("")
        lines.append("## ⚠️ ARCHIVOS NO ATRIBUIDOS A NINGÚN MÓDULO")
        lines.append("(aparecieron en disco pero ningún módulo los registró — revisá si son invención)")
        lines.extend(f"- {f}" for f in untracked)
    return "\n".join(lines)
