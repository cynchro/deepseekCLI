"""Bitácora persistente por proyecto (.deep/journal.md) — la memoria entre sesiones.

Es la tercera capa de memoria del agente, complementaria a las otras dos:
  - DEEP.md            → QUÉ ES el proyecto (hechos estables)        [core/context.py]
  - .deep/tasks.json   → QUÉ FALTA (TODO activo)                     [core/tasks.py]
  - .deep/journal.md   → QUÉ SE HIZO y DÓNDE QUEDAMOS (este módulo)

Al salir, el REPL resume la sesión con FLASH (barato) y agrega una entrada datada.
Al abrir deep en la carpeta, se muestra la última entrada ("en la última sesión
quedamos en…") y se inyecta en el contexto del agente para que un "seguí" retome
de verdad. El formato es markdown legible/editable a mano: es un roadmap, no un blob.

NO inventa: el prompt de resumen calca las reglas de fidelidad de core/compaction.py
(si un test falló, figura como falla; nada que no esté en el transcript).
"""
import json
import re
from datetime import datetime
from pathlib import Path

from core import compaction as _compaction
from core.models import MODEL_FLASH

_MAX_ENTRIES = 40                 # cap de entradas guardadas (el archivo no crece sin fin)
_SUMMARY_BUDGET = 80000           # chars del transcript que se mandan a resumir (la cola, lo reciente)

_SYS_JOURNAL = (
    "Sos el archivador de una sesión de trabajo de ingeniería. A partir del transcript de "
    "abajo, escribí una entrada de bitácora para que en la próxima sesión se pueda retomar "
    "sin perder el hilo.\n\n"
    "REGLA #1 — NO INVENTES. Usá SOLO hechos presentes en el transcript. Prohibido agregar "
    "archivos, decisiones o resultados que no aparecen, o dar por pasado algo que falló: si un "
    "test/comando falló, decílo como falla.\n\n"
    "Respondé SOLO con JSON válido (sin texto alrededor, sin markdown) con estas claves:\n"
    '  "hecho": qué se hizo realmente esta sesión (archivos con su ruta, cambios concretos).\n'
    '  "decisiones": decisiones de diseño y su motivo, si se explicitaron (o "" si no hubo).\n'
    '  "proximo_paso": qué quedó pendiente / por dónde seguir, tal como se dijo (o "" si no quedó claro).\n'
    "Sé conciso y concreto. Conservá rutas, nombres y resultados de tests tal cual."
)


def journal_path(workspace) -> Path:
    return workspace / ".deep" / "journal.md"


def _split_entries(text: str):
    """Parte el markdown en entradas (cada una empieza con una línea '## ')."""
    parts = re.split(r"(?m)^(?=## )", text)
    return [p for p in parts if p.strip()]


def load_recap(workspace) -> str:
    """Texto de la última entrada de la bitácora (con su encabezado), o '' si no hay."""
    p = journal_path(workspace)
    if not p.exists():
        return ""
    try:
        entries = _split_entries(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return entries[-1].strip() if entries else ""


def render_entry(entry: dict) -> str:
    """Formatea una entrada como sección markdown datada."""
    stamp = entry.get("stamp") or datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"## {stamp}"]
    if entry.get("hecho"):
        lines.append(f"**Hecho:** {entry['hecho'].strip()}")
    if entry.get("decisiones"):
        lines.append(f"**Decisiones:** {entry['decisiones'].strip()}")
    if entry.get("proximo_paso"):
        lines.append(f"**Próximo paso:** {entry['proximo_paso'].strip()}")
    return "\n".join(lines) + "\n"


def append_entry(workspace, entry: dict) -> None:
    """Agrega una entrada al final de la bitácora y poda a las últimas _MAX_ENTRIES."""
    p = journal_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _split_entries(p.read_text(encoding="utf-8")) if p.exists() else []
    existing.append(render_entry(entry))
    kept = existing[-_MAX_ENTRIES:]
    p.write_text("\n".join(s.strip() + "\n" for s in kept), encoding="utf-8")


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL)
    raw = re.sub(r"```json\n?|```\n?", "", raw).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def summarize_session(client, messages) -> dict | None:
    """Resume los mensajes no-system de la sesión en una entrada de bitácora.

    Devuelve {hecho, decisiones, proximo_paso, stamp} o None si no hubo nada
    sustancial (sesión vacía o el modelo no devolvió contenido)."""
    parts = _compaction._render(messages[1:] if messages else [])
    if not parts:
        return None
    text = "\n".join(parts)
    if len(text) > _SUMMARY_BUDGET:        # nos quedamos con la cola: lo más reciente importa más
        text = text[-_SUMMARY_BUDGET:]
    res = client.complete(
        [{"role": "system", "content": _SYS_JOURNAL},
         {"role": "user", "content": text}],
        model=MODEL_FLASH, temperature=0.0, max_tokens=1200,
    )
    if not res.get("success"):
        return None
    data = _parse_json(res.get("content", ""))
    if not data:
        # Fallback: si no parseó JSON pero hubo respuesta, guardala como "hecho".
        raw = (res.get("content") or "").strip()
        data = {"hecho": raw} if raw else {}
    entry = {
        "hecho": (data.get("hecho") or "").strip(),
        "decisiones": (data.get("decisiones") or "").strip(),
        "proximo_paso": (data.get("proximo_paso") or "").strip(),
        "stamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if not (entry["hecho"] or entry["decisiones"] or entry["proximo_paso"]):
        return None
    return entry
