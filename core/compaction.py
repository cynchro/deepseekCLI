"""Compactación fiel del historial del agente.

Cuando el contexto crece, hay que resumir el trabajo viejo — pero un resumen flojo
pierde rutas de archivos, decisiones y resultados de tests, y el agente repite trabajo
o se contradice. Este módulo busca FIDELIDAD:

- No pre-trunca cada mensaje a unos pocos chars (el resumidor ve el contenido real,
  con un tope por mensaje grande para no explotar con un dump enorme).
- Map-reduce: si el tramo a resumir es enorme, lo parte en segmentos, resume cada uno
  y después combina — así nada se cae por apretar todo en una sola llamada.
- Prompt estructurado que exige preservar objetivo, TODOS los archivos con su ruta, las
  decisiones, los comandos corridos y su resultado, y los pendientes.

Usa FLASH (barato) — la compactación es poco frecuente y conviene gastar en fidelidad.
"""
from core.models import MODEL_FLASH

SUMMARY_MARKER = "[Resumen del trabajo previo en esta tarea]"

_PER_MSG_CAP = 6000       # tope por mensaje antes de resumir (vs. 1500 del enfoque viejo)
_SEGMENT_BUDGET = 80000   # chars por segmento del map-reduce (~20k tokens, holgado para FLASH)

_SYS_SUMMARIZE = (
    "Sos un archivador de trabajo de ingeniería. Resumí EXCLUSIVAMENTE lo que aparece en el "
    "transcript de abajo, para que otro agente pueda continuar.\n\n"
    "REGLA #1 — NO INVENTES. Incluí solo hechos presentes en el transcript. Está PROHIBIDO:\n"
    "- agregar archivos, funciones, decisiones, comandos o dependencias que no se mencionan;\n"
    "- 'completar' un proyecto típico con piezas que parecen razonables pero no están;\n"
    "- asumir que algo funciona. Si un test FALLA, decílo como falla; nunca lo des por pasado.\n"
    "Si un dato no está en el transcript, omitilo — no lo rellenes.\n\n"
    "Preservá, citando textual cuando puedas:\n"
    "1. La tarea/objetivo y el estado real (incluido lo que está roto o a medias).\n"
    "2. Los archivos creados/modificados que se mencionan, con su RUTA EXACTA y qué se hizo.\n"
    "3. Las decisiones de diseño y su motivo, si se explicitaron.\n"
    "4. Comandos corridos y su RESULTADO real (tests que pasan Y los que fallan, con el error).\n"
    "5. Lo que quedó PENDIENTE, tal como se dijo.\n"
    "Conservá rutas, nombres y números tal cual. Sé completo con lo que ESTÁ, sin agregar lo que no."
)
_SYS_COMBINE = (
    "Combiná estos resúmenes parciales (en orden cronológico) en UNO solo, coherente. "
    "NO inventes nada que no esté en los parciales: no agregues archivos, decisiones ni "
    "resultados. Conservá todas las rutas, los resultados de tests (incluidos los que fallan) "
    "y los pendientes tal como aparecen. Si hubo un fallo, debe seguir figurando como fallo."
)


def _render(messages, per_msg_cap: int = _PER_MSG_CAP):
    """Renderiza los mensajes a texto, conservando el contenido real (con tope por
    mensaje) e indicando las tool_calls de los mensajes sin texto."""
    parts = []
    for m in messages:
        content = m.get("content") or ""
        if not content and m.get("tool_calls"):
            names = [tc["function"]["name"] for tc in m["tool_calls"]]
            content = "(llamó tools: " + ", ".join(names) + ")"
        if not content:
            continue
        if len(content) > per_msg_cap:
            content = content[:per_msg_cap] + f"\n[...+{len(content) - per_msg_cap} chars omitidos...]"
        parts.append(f"{m['role'].upper()}: {content}")
    return parts


def _segments(parts, budget: int = _SEGMENT_BUDGET):
    """Agrupa los renders en segmentos que no superen `budget` chars."""
    segs, cur, n = [], [], 0
    for p in parts:
        if cur and n + len(p) > budget:
            segs.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += len(p)
    if cur:
        segs.append(cur)
    return segs


def _summarize(client, text: str, model: str) -> str:
    res = client.complete(
        [{"role": "system", "content": _SYS_SUMMARIZE},
         {"role": "user", "content": text}],
        model=model, temperature=0.0, max_tokens=2500,
    )
    return res.get("content", "") if res.get("success") else ""


def _combine(client, partials, model: str) -> str:
    joined = "\n\n--- parcial ---\n".join(partials)
    res = client.complete(
        [{"role": "system", "content": _SYS_COMBINE},
         {"role": "user", "content": joined}],
        model=model, temperature=0.0, max_tokens=3000,
    )
    return res.get("content", "") if res.get("success") else ""


def summarize_head(client, head, model: str = MODEL_FLASH) -> str:
    """Resume el tramo `head` de mensajes con map-reduce y prompt fiel.
    Devuelve el texto del resumen (sin el marcador) o '' si no se pudo."""
    parts = _render(head)
    if not parts:
        return ""
    segs = _segments(parts)
    if len(segs) == 1:
        return _summarize(client, "\n".join(segs[0]), model)
    # map: resumir cada segmento
    partials = [s for s in (_summarize(client, "\n".join(seg), model) for seg in segs) if s]
    if not partials:
        return ""
    if len(partials) == 1:
        return partials[0]
    # reduce: combinar los parciales en uno solo
    return _combine(client, partials, model)
