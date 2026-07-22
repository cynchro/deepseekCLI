"""Contexto de proyecto para el agente: DEEP.md jerárquico (estilo CLAUDE.md).

Carga, si existen:
  - global:   ~/.config/deep/DEEP.md
  - proyecto: <workspace>/DEEP.md

Se inyecta como instrucciones autoritativas en el system prompt del agente.
El comando /init genera el DEEP.md del proyecto corriendo al propio agente.
"""
from pathlib import Path

GLOBAL_DEEP_MD = Path.home() / ".config" / "deep" / "DEEP.md"


def project_md_path(workspace) -> Path:
    return workspace / "DEEP.md"


def load_project_context(workspace) -> str:
    """Concatena DEEP.md global + del proyecto. Devuelve '' si no hay ninguno."""
    blocks = []
    sources = [("global", GLOBAL_DEEP_MD), ("del proyecto", project_md_path(workspace))]
    for label, p in sources:
        if not p.exists():
            continue
        try:
            txt = p.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if txt:
            blocks.append(f"## Contexto {label} ({p.name})\n{txt}")
    if not blocks:
        return ""
    return ("INSTRUCCIONES DEL PROYECTO (DEEP.md) — son autoritativas, respetalas:\n\n"
            + "\n\n".join(blocks))


# Tarea canónica para /init: el agente explora y escribe el DEEP.md.
INIT_TASK = (
    "Explorá este proyecto usando tus herramientas (list_dir, glob, grep, read_file) "
    "y creá un archivo DEEP.md en la raíz del workspace que sirva de contexto para "
    "futuras sesiones. Incluí: (1) una descripción breve del proyecto, (2) el stack y "
    "lenguajes, (3) la estructura de carpetas relevante, (4) cómo instalar/correr/testear, "
    "(5) convenciones de código que detectes. Sé conciso y concreto. Si ya existe DEEP.md, "
    "actualizalo sin borrar notas manuales que parezcan agregadas por una persona."
)
