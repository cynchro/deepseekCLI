"""
navigator — capa de orquestación donde un LLM navigator externo (Claude, ChatGPT,
Gemini, etc.) planifica y DeepSeek construye + corrige.

Este módulo es PURO: solo parsea el archivo de job, valida, genera plantillas y
maneja el estado por módulo en disco. No hace llamadas a la API ni toca el core.
La orquestación (que reusa DeepSeekLearningSystem) vive en cli/commands.py.

Contrato de archivos:
  .deep/job.md                    → spec inmutable que escribe el navigator
  .deep/navigator/state/<mod>.json → estado de cada módulo construido por DeepSeek
  review.md                       → correcciones efímeras que escribe el navigator (se consumen)
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


# Campos estructurados de un módulo: `files:`, `uses:`, `done:`. Cada uno admite
# items en bullets debajo y/o una lista inline separada por comas en la misma línea.
_FIELD_RE = re.compile(r"^[ \t]*(files|uses|done)[ \t]*:(.*)$",
                       re.IGNORECASE | re.MULTILINE)
_EMPTY_MARKERS = {"(ninguno)", "(none)", "ninguno", "none", "n/a", "-", "—"}


def _parse_fields(body: str) -> Dict[str, List[str]]:
    """Extrae files/uses/done del cuerpo de un módulo. Si no hay etiquetas
    (formato v1, bullets sueltos), devuelve listas vacías y el body queda intacto."""
    fields: Dict[str, List[str]] = {"files": [], "uses": [], "done": []}
    labels = list(_FIELD_RE.finditer(body))
    for i, m in enumerate(labels):
        key = m.group(1).lower()
        start = m.end()
        end = labels[i + 1].start() if i + 1 < len(labels) else len(body)
        items: List[str] = []
        inline = m.group(2).strip()
        if inline:
            items += [x.strip() for x in inline.split(",") if x.strip()]
        items += _bullets(body[start:end])
        fields[key] = [it for it in items if it.lower() not in _EMPTY_MARKERS]
    return fields


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
    for mod in modules:
        mod.update(_parse_fields(mod["body"]))

    errors: List[str] = []
    if "TASKS" not in secs:
        errors.append("Falta la sección `## TASKS` con los módulos a construir.")
    elif not modules:
        errors.append("La sección `## TASKS` no tiene módulos. Agregá uno o más `### <nombre>`.")
    if "PLAN" not in secs:
        errors.append("Falta la sección `## PLAN` con la arquitectura general.")

    return {
        "title": _title(text),
        "stack": secs.get("STACK", "").strip(),
        "plan": secs.get("PLAN", ""),
        "contracts": secs.get("CONTRACTS", "").strip(),
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
        errors.append("Falta la sección `## CORRECTIONS`. El navigator debe escribir las correcciones ahí.")
    elif not modules:
        errors.append("`## CORRECTIONS` no tiene módulos (`### <nombre>`). Nada que corregir.")
    return {"modules": modules, "errors": errors}


# ── Plantilla ────────────────────────────────────────────────────────────────

JOB_TEMPLATE = """# JOB: {title}

## STACK
<!-- Lenguaje, versión y dependencias PERMITIDAS. Cerrado: DeepSeek no usa nada
     que no esté acá. -->
- lenguaje: <ej. PHP 8.2 / Python 3.12 / Go 1.22>
- dependencias: <lista exacta, o "ninguna">

## PLAN
<!-- Arquitectura general del proyecto. Lo escribe el navigator (el arquitecto).
     DeepSeek usa esto como plan y NO vuelve a planificar. -->

## CONTRACTS
<!-- Interfaces, tipos, esquemas y firmas COMPARTIDAS entre módulos. Se inyecta en
     CADA módulo como fuente de verdad, para que los cruces cierren y nadie invente.
     Ej: firmas de funciones públicas, forma de DTOs/structs, esquema de tablas,
     rutas HTTP, nombres de servicios. Si A expone algo que B consume, va acá. -->

## RULES
<!-- Restricciones que DeepSeek respeta en cada módulo. -->
- No agregar dependencias que no estén en STACK, PLAN o el módulo.
- No crear archivos que no estén listados en `files:` del módulo.
- Respetar exactamente las rutas, firmas y contratos definidos en CONTRACTS.
- Si falta información para implementar algo, dejar un TODO explícito — NO inventar.

## TASKS
<!-- Un `### <módulo>` por cada pieza a construir. DeepSeek construye uno por uno.
     Por cada módulo:
       files:  rutas EXACTAS que debe crear (y solo esas).
       uses:   qué contratos/módulos consume (de CONTRACTS o de otro módulo).
       done:   qué tiene que cumplir para considerarse terminado.
     Cuanto más concreto, menos margen de invención. -->
### modulo-ejemplo
files:
- ejemplo/main.py
uses:
- (ninguno)
done:
- función run() -> None que imprime "ok"
"""


def job_template(title: str = "mi-proyecto") -> str:
    return JOB_TEMPLATE.format(title=title)


# ── Estado por módulo ────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-") or "modulo"


def state_dir(project_dir: Path) -> Path:
    return Path(project_dir) / ".deep" / "navigator" / "state"


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
        "gate": result.get("gate"),
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


# ── Plan por módulo (lo que recibe DeepSeek al construir cada módulo) ─────────

def _sibling_excerpts(job: Dict, mod: Dict, project_dir: Path,
                      budget: int = 9000, per_file: int = 1200) -> str:
    """Código real ya construido por OTROS módulos, para que DeepSeek use las APIs
    que existen en vez de inventarlas. Agnóstico: inyecta el texto crudo (head),
    sin parsear firmas. Prioriza los módulos listados en `uses:` y respeta un
    presupuesto de caracteres."""
    states = {s["module"]: s for s in load_all_states(project_dir)}
    uses = {u.lower() for u in mod.get("uses", [])}

    ordered = []
    for m in job.get("modules", []):
        if m["name"] == mod["name"] or m["name"] not in states:
            continue
        priority = 0 if m["name"].lower() in uses else 1
        ordered.append((priority, states[m["name"]]))
    ordered.sort(key=lambda x: x[0])

    out, used = [], 0
    for _, st in ordered:
        for fp in st.get("files_written", []):
            p = Path(fp)
            if ".deep" in p.parts or p.name == "RESPONSE.md":
                continue
            try:
                text = p.read_text(encoding="utf-8")
                rel = p.resolve().relative_to(Path(project_dir).resolve())
            except (OSError, ValueError):
                continue
            snippet = text[:per_file]
            if len(text) > per_file:
                snippet += "\n# … (truncado) …"
            block = f"### {rel}\n{snippet}"
            if used + len(block) > budget:
                return "\n\n".join(out)
            out.append(block)
            used += len(block)
    return "\n\n".join(out)


def build_module_plan(job: Dict, mod: Dict, project_dir: Path) -> str:
    """Arma el plan que recibe DeepSeek para UN módulo: stack + plan global +
    contratos compartidos + código ya construido + detalle estructurado del módulo.
    DeepSeek no replanifica; solo construye contra este contrato."""
    parts: List[str] = []
    if job.get("stack"):
        parts.append("## STACK (cerrado — no uses nada fuera de esto)\n" + job["stack"])
    parts.append("## PLAN GENERAL (definido por el navigator)\n" + job.get("plan", ""))
    if job.get("contracts"):
        parts.append("## CONTRACTS (fuente de verdad — respetá estas firmas/esquemas EXACTAMENTE)\n"
                     + job["contracts"])

    siblings = _sibling_excerpts(job, mod, project_dir)
    if siblings:
        parts.append("## YA CONSTRUIDO POR OTROS MÓDULOS (usá estas APIs reales, NO las reinventes)\n"
                     + siblings)

    detail = [f"## MÓDULO A CONSTRUIR AHORA: {mod['name']}"]
    if mod.get("files"):
        detail.append("Archivos a crear (SOLO estos, ninguno más):\n"
                      + "\n".join(f"- {f}" for f in mod["files"]))
    if mod.get("uses"):
        detail.append("Consume (de CONTRACTS u otros módulos):\n"
                      + "\n".join(f"- {u}" for u in mod["uses"]))
    if mod.get("done"):
        detail.append("Terminado cuando:\n" + "\n".join(f"- {d}" for d in mod["done"]))
    # Fallback v1: si el módulo no usa campos estructurados, mandamos su body crudo.
    if not (mod.get("files") or mod.get("done")):
        detail.append(mod.get("body", ""))
    parts.append("\n".join(detail))

    return "\n\n".join(parts)


# ── Gate: lo declarado (files:) vs lo construido ─────────────────────────────

def gate_module(mod: Dict, files_written: List[str], project_dir: Path) -> Dict:
    """Compara los `files:` declarados por el módulo contra lo que DeepSeek escribió.
       missing → fuga (no cumplió el contrato);  extra → posible invención.
    Si el módulo no declara files: (job v1), no hay nada que verificar."""
    declared = {f.lstrip("/") for f in mod.get("files", [])}
    if not declared:
        return {"declared": [], "missing": [], "extra": [], "ok": True}
    built = set(_relative_code_files(files_written, project_dir))
    missing = sorted(d for d in declared if d not in built)
    extra = sorted(b for b in built if b not in declared)
    return {
        "declared": sorted(declared),
        "missing": missing,   # falla dura
        "extra": extra,       # advertencia (invención)
        "ok": not missing,
    }


# ── Render del review (lo que el usuario pasa al navigator) ──────────────────

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
    """Genera el texto que el usuario pasa al navigator para que revise el proyecto.
    Muestra, por módulo, lo PEDIDO (TASKS) frente a los archivos que DeepSeek
    construyó, más el inventario completo en disco — para detectar invención
    (archivos o dependencias que nadie pidió). El navigator lee los archivos directamente."""
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
        "Sos el navigator (el arquitecto del proyecto). Revisá lo que construyó DeepSeek en este directorio",
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
