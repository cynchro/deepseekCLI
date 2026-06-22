"""Planificación estructurada del proyecto (JSON)."""

import json
import re
from pathlib import Path
from typing import Dict, List

import core.debug as _dbg

PLAN_SYSTEM = (
    "Eres un arquitecto de software senior. Diseñás proyectos como conjuntos de "
    "archivos pequeños con responsabilidad única. Respondés ÚNICAMENTE con JSON válido, "
    "sin markdown ni texto adicional."
)

PLAN_SCHEMA_HINT = """{
  "architecture": "descripción concisa de la arquitectura",
  "files": [
    {
      "path": "ruta/relativa/archivo.ext",
      "description": "qué hace este archivo",
      "depends_on": ["otro/archivo.ext"],
      "scaffold": false
    }
  ],
  "order": ["archivo1.ext", "archivo2.ext"]
}"""


def build_plan_prompt(task: str, rules_block: str, experience_context: str) -> str:
    return f"""Diseñá el plan de implementación para esta tarea.

TAREA:
{task}
{experience_context}
{rules_block}

REQUISITOS DEL PLAN:
- Dividí el sistema en archivos pequeños, cada uno con una sola responsabilidad.
- Incluí TODOS los archivos necesarios (código, config, Docker, tests, README si aplica).
- El campo "order" debe listar rutas en orden topológico correcto (dependencias primero).
- Cada entrada en "files" debe tener: path, description, depends_on (array, puede estar vacío).
- Opcional: "scaffold": true para archivos que solo definen interfaces/firmas en una primera pasada.
- "depends_on" solo puede referenciar paths declarados en "files".
- Rutas relativas, sin barra inicial.

Respondé SOLO con JSON con esta forma:
{PLAN_SCHEMA_HINT}
"""


def parse_json_response(raw: str) -> Dict:
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
    text = re.sub(r"```json\n?|```\n?", "", text).strip()
    return json.loads(text)


def normalize_plan(plan: Dict) -> Dict:
    """Valida y normaliza el plan; resuelve order por topología si hace falta."""
    if not isinstance(plan.get("architecture"), str):
        raise ValueError("El plan debe incluir 'architecture' (string)")

    files_raw = plan.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise ValueError("El plan debe incluir 'files' (array no vacío)")

    files: List[Dict] = []
    paths_seen = set()
    for entry in files_raw:
        if not isinstance(entry, dict):
            continue
        path = _norm(entry.get("path", ""))
        if not path or path in paths_seen or ".." in Path(path).parts:
            continue
        paths_seen.add(path)
        deps = [_norm(d) for d in entry.get("depends_on", []) if _norm(d)]
        files.append({
            "path": path,
            "description": str(entry.get("description", "")).strip(),
            "depends_on": [d for d in deps if d != path],
            "scaffold": bool(entry.get("scaffold", False)),
        })

    if not files:
        raise ValueError("No hay archivos válidos en el plan")

    file_map = {f["path"]: f for f in files}
    for f in files:
        f["depends_on"] = [d for d in f["depends_on"] if d in file_map and d != f["path"]]

    order = [_norm(p) for p in plan.get("order", []) if _norm(p)]
    order = [p for p in order if p in file_map]
    if len(order) != len(file_map):
        order = _topological_order(files)
        _dbg.log("PLAN", f"order regenerado por topología: {order}")

    return {
        "architecture": plan["architecture"].strip(),
        "files": files,
        "order": order,
    }


def _norm(path: str) -> str:
    return path.strip().lstrip("/").replace("\\", "/")


def _topological_order(files: List[Dict]) -> List[str]:
    file_map = {f["path"]: f for f in files}
    visited, temp, result = set(), set(), []

    def visit(path: str):
        if path in visited:
            return
        if path in temp:
            return
        temp.add(path)
        for dep in file_map.get(path, {}).get("depends_on", []):
            if dep in file_map:
                visit(dep)
        temp.discard(path)
        visited.add(path)
        result.append(path)

    for path in file_map:
        visit(path)
    return result


def plan_summary(plan: Dict) -> str:
    return json.dumps({
        "architecture": plan.get("architecture", "")[:300],
        "file_count": len(plan.get("files", [])),
        "order": plan.get("order", []),
    }, ensure_ascii=False)


def summarize_written_files(written_paths: Dict, plan: Dict, max_snippet: int = 120) -> str:
    """Resumen compacto del progreso para re-planificación."""
    from core.context_builder import extract_snippet

    lines = []
    for path in plan.get("order", []):
        if path not in written_paths:
            continue
        fp = written_paths[path]
        if not fp.exists():
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError:
            continue
        entry = next((f for f in plan.get("files", []) if _norm(f["path"]) == path), {})
        lines.append(
            f"- {path}: {entry.get('description', '')[:80]} "
            f"({len(text)} chars)\n{extract_snippet(text, max_lines=8)[:max_snippet]}"
        )
    return "\n".join(lines) if lines else "(ningún archivo escrito aún)"


def build_replan_prompt(
    plan: Dict,
    written_summary: str,
    task: str,
    state_block: str,
) -> str:
    return f"""You are a senior software architect.

TAREA ORIGINAL:
{task}

PLAN ORIGINAL:
{json.dumps(plan, ensure_ascii=False, indent=2)}

PROGRESO HASTA AHORA:
{written_summary}

{state_block}

TASK:
Update the remaining plan if needed based on what was already built.

CONSTRAINTS:
- Do NOT modify already completed files (keep their path, description, depends_on unchanged)
- Only adjust remaining files and the order of pending work
- Keep consistency with existing architecture and written code
- Return the FULL updated JSON plan (same schema: architecture, files, order)

Respondé SOLO con JSON válido.
"""


def merge_plan(original: Dict, updated: Dict, completed_paths: List[str]) -> Dict:
    """Fusiona plan re-planificado preservando archivos ya completados."""
    completed = {_norm(p) for p in completed_paths}
    orig_map = {_norm(f["path"]): f for f in original.get("files", [])}

    try:
        updated_norm = normalize_plan(updated)
    except (ValueError, json.JSONDecodeError):
        _dbg.log("REPLAN", "merge falló — se mantiene plan original")
        return original

    merged_files: List[Dict] = []
    seen = set()

    for path in original.get("order", []):
        if path in completed and path in orig_map:
            merged_files.append(dict(orig_map[path]))
            seen.add(path)

    for f in updated_norm["files"]:
        p = f["path"]
        if p not in completed and p not in seen:
            merged_files.append(f)
            seen.add(p)

    for path in completed:
        if path in orig_map and path not in seen:
            merged_files.append(dict(orig_map[path]))
            seen.add(path)

    completed_order = [p for p in original.get("order", []) if p in completed]
    remaining_order = [p for p in updated_norm["order"] if p not in completed]
    new_order = completed_order + remaining_order
    for f in merged_files:
        if f["path"] not in new_order:
            new_order.append(f["path"])

    merged = normalize_plan({
        "architecture": updated_norm.get("architecture") or original.get("architecture", ""),
        "files": merged_files,
        "order": new_order,
    })
    _dbg.log("REPLAN", f"merge ok — completed={len(completed)}  total={len(merged['files'])}")
    return merged
