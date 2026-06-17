"""CodeBuilder: delega la generación/edición de código a FLASH.

PRO (en el agent loop) decide qué y dónde, y llama a las tools generate_code /
apply_edit con una especificación compacta. El builder usa FLASH —más barato y
rápido— para producir los bytes, manteniendo liviano el contexto de PRO.

Usa el MISMO DeepSeekClient que el loop (pasando model=FLASH por llamada), así
get_stats() agrega el gasto de ambos modelos.
"""
from pathlib import Path
from typing import List

from core.client import DeepSeekClient
from core.models import MODEL_FLASH

_GEN_SYS = ("Sos un generador de código senior. Producís archivos completos, "
            "production-ready, sin placeholders ni TODOs. Devolvés SOLO el "
            "contenido del archivo, sin explicaciones ni fences markdown.")
_EDIT_SYS = ("Sos un desarrollador senior. Aplicás cambios precisos y devolvés el "
             "archivo COMPLETO ya modificado, sin placeholders ni explicaciones.")


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


class CodeBuilder:
    def __init__(self, client: DeepSeekClient, model: str = MODEL_FLASH,
                 rules: List[str] = None, max_context_chars: int = 6000):
        self.client = client
        self.model = model
        self.rules = rules or []
        self.max_context_chars = max_context_chars

    def _rules_block(self) -> str:
        if not self.rules:
            return ""
        return "\nReglas del proyecto:\n" + "\n".join(f"- {r}" for r in self.rules) + "\n"

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
        prompt = (
            f"Modificá el archivo `{path}` según las instrucciones.\n\n"
            f"Instrucciones:\n{instructions}\n"
            f"{self._context_block(workspace, context_files)}"
            f"{self._rules_block()}"
            f"\nContenido actual de `{path}`:\n```\n{current}\n```\n"
            "\nDevolvé el contenido COMPLETO del archivo ya modificado."
        )
        resp = self.client.complete(
            [{"role": "system", "content": _EDIT_SYS},
             {"role": "user", "content": prompt}],
            model=self.model, temperature=0.2, max_tokens=8000,
        )
        if not resp.get("success"):
            return {"success": False, "error": resp.get("content", "")}
        return {"success": True, "content": strip_code(resp["content"])}
