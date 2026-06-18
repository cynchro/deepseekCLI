"""CodeBuilder: delega la generación/edición de código a FLASH.

PRO (en el agent loop) decide qué y dónde, y llama a las tools generate_code /
apply_edit con una especificación compacta. El builder usa FLASH —más barato y
rápido— para producir los bytes, manteniendo liviano el contexto de PRO.

Usa el MISMO DeepSeekClient que el loop (pasando model=FLASH por llamada), así
get_stats() agrega el gasto de ambos modelos.
"""
import re
from pathlib import Path
from typing import List

from core.client import DeepSeekClient
from core.models import MODEL_FLASH

_GEN_SYS = ("Sos un generador de código senior. Producís archivos completos, "
            "production-ready, sin placeholders ni TODOs. Seguís las convenciones del "
            "proyecto. Devolvés SOLO el contenido del archivo, sin explicaciones ni fences.")
_EDIT_SYS = (
    "Sos un desarrollador senior que aplica cambios QUIRÚRGICOS. No reescribís el archivo "
    "entero: devolvés solo los bloques de búsqueda/reemplazo necesarios, en este formato EXACTO "
    "y nada más:\n"
    "<<<<<<< SEARCH\n"
    "<texto EXACTO actual, copiado tal cual del archivo, con contexto suficiente para ser único>\n"
    "=======\n"
    "<texto nuevo>\n"
    ">>>>>>> REPLACE\n"
    "Repetí el bloque por cada cambio. El SEARCH debe coincidir carácter por carácter con el "
    "archivo actual. No incluyas explicaciones ni fences markdown.")


def strip_code(text: str) -> str:
    """Quita un bloque ``` envolvente si el modelo lo agregó."""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip("\n")
    return t + "\n" if t else t


_SR_RE = re.compile(
    r"<{5,}\s*SEARCH\s*\n(.*?)\n={5,}\s*\n(.*?)\n>{5,}\s*REPLACE",
    re.DOTALL,
)


def parse_search_replace(text: str):
    """Extrae bloques (search, replace) del formato del editor quirúrgico."""
    return [(m.group(1), m.group(2)) for m in _SR_RE.finditer(text or "")]


def apply_search_replace(current: str, blocks) -> tuple:
    """Aplica los bloques en orden sobre `current`. Devuelve (nuevo, aplicados, error)."""
    new = current
    applied = 0
    for search, replace in blocks:
        n = new.count(search)
        if n == 0:
            return new, applied, f"bloque SEARCH no encontrado: {search[:80]!r}"
        if n > 1:
            return new, applied, f"bloque SEARCH ambiguo ({n} coincidencias): {search[:80]!r}"
        new = new.replace(search, replace, 1)
        applied += 1
    return new, applied, None


class CodeBuilder:
    def __init__(self, client: DeepSeekClient, model: str = MODEL_FLASH,
                 rules: List[str] = None, project_context: str = None,
                 max_context_chars: int = 6000):
        self.client = client
        self.model = model
        self.rules = rules or []
        self.project_context = project_context or ""
        self.max_context_chars = max_context_chars

    def _rules_block(self) -> str:
        block = ""
        if self.project_context:
            block += "\n" + self.project_context[:2000] + "\n"
        if self.rules:
            block += "\nReglas del proyecto:\n" + "\n".join(f"- {r}" for r in self.rules) + "\n"
        return block

    def _context_block(self, workspace, context_files) -> str:
        if not context_files:
            return ""
        parts = []
        for cf in list(context_files)[:8]:
            try:
                txt = (Path(workspace) / cf).read_text(
                    encoding="utf-8", errors="replace")[:self.max_context_chars]
                parts.append(f"### {cf}\n{txt}")
            except Exception:
                continue
        return ("\nArchivos de contexto:\n" + "\n\n".join(parts) + "\n") if parts else ""

    def generate(self, path, spec, workspace, context_files=None) -> dict:
        prompt = (
            f"Generá el contenido COMPLETO del archivo `{path}`.\n\n"
            f"Especificación:\n{spec}\n"
            f"{self._context_block(workspace, context_files)}"
            f"{self._rules_block()}"
            "\nDevolvé SOLO el código del archivo."
        )
        resp = self.client.complete(
            [{"role": "system", "content": _GEN_SYS},
             {"role": "user", "content": prompt}],
            model=self.model, temperature=0.2, max_tokens=8000,
        )
        if not resp.get("success"):
            return {"success": False, "error": resp.get("content", "")}
        return {"success": True, "content": strip_code(resp["content"])}

    def edit(self, path, instructions, current, workspace, context_files=None) -> dict:
        numbered = "\n".join(f"{i + 1:>5}\t{ln}" for i, ln in enumerate(current.splitlines()))
        prompt = (
            f"Modificá el archivo `{path}` según las instrucciones, con bloques "
            f"SEARCH/REPLACE quirúrgicos (no reescribas todo el archivo).\n\n"
            f"Instrucciones:\n{instructions}\n"
            f"{self._context_block(workspace, context_files)}"
            f"{self._rules_block()}"
            f"\nContenido actual de `{path}` (con nº de línea solo de referencia; "
            f"NO los incluyas en el SEARCH):\n```\n{numbered}\n```\n"
            "\nDevolvé SOLO los bloques SEARCH/REPLACE necesarios."
        )
        resp = self.client.complete(
            [{"role": "system", "content": _EDIT_SYS},
             {"role": "user", "content": prompt}],
            model=self.model, temperature=0.2, max_tokens=8000,
        )
        if not resp.get("success"):
            return {"success": False, "error": resp.get("content", "")}
        blocks = parse_search_replace(resp["content"])
        if not blocks:
            return {"success": False,
                    "error": "FLASH no devolvió bloques SEARCH/REPLACE válidos"}
        new, applied, err = apply_search_replace(current, blocks)
        if err:
            return {"success": False, "error": err}
        return {"success": True, "content": new, "applied": applied}
