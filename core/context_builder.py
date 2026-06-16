"""Construcción de contexto mínimo para generación por archivo."""

from pathlib import Path
from typing import Dict, List, Optional

_MAX_SNIPPET_LINES = 100

_TRIVIAL_NAMES = {
    ".env", ".env.example", ".gitignore", ".dockerignore", ".editorconfig",
    "requirements.txt", "pyproject.toml", "setup.cfg", "Makefile",
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
}

_TRIVIAL_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env"}

_TRIVIAL_KEYWORDS = (
    "config", "constant", "constants", "dto", "schema", "env file",
    "gitignore", "docker-compose", "manifest", "metadata",
)


def normalize_path(path: str) -> str:
    return path.strip().lstrip("/").replace("\\", "/")


def extract_snippet(content: str, max_lines: int = _MAX_SNIPPET_LINES) -> str:
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    head = max_lines // 2
    tail = max_lines - head
    omitted = len(lines) - max_lines
    return (
        "\n".join(lines[:head])
        + f"\n# ... {omitted} líneas omitidas ...\n"
        + "\n".join(lines[-tail:])
    )


def is_trivial_file(path: str, description: str = "") -> bool:
    p = Path(normalize_path(path))
    name = p.name.lower()
    desc = (description or "").lower()

    if name in _TRIVIAL_NAMES:
        return True
    if p.suffix.lower() in _TRIVIAL_EXTENSIONS:
        return True
    if name == "__init__.py" and ("empty" in desc or "package" in desc or not desc):
        return True
    if any(kw in desc for kw in _TRIVIAL_KEYWORDS):
        return True
    if name.endswith("_dto.py") or name.endswith("_constants.py"):
        return True
    return False


def is_scaffold_file(file_entry: Dict) -> bool:
    if file_entry.get("scaffold"):
        return True
    desc = (file_entry.get("description") or "").lower()
    return any(kw in desc for kw in ("scaffold", "stub", "interface only", "skeleton"))


def build_generation_context(
    task: str,
    plan: Dict,
    file_entry: Dict,
    project_dir: Path,
    written_paths: Dict[str, Path],
    *,
    scaffold_mode: bool = False,
    build_state=None,
) -> str:
    """Arma contexto acotado: arquitectura + deps + estado global + errores recientes."""
    path = normalize_path(file_entry["path"])
    architecture = plan.get("architecture", "")
    description = file_entry.get("description", "")
    depends_on = [normalize_path(d) for d in file_entry.get("depends_on", [])]

    parts = [
        f"TAREA GLOBAL:\n{task}\n",
        f"ARQUITECTURA:\n{architecture}\n",
        f"ARCHIVO A GENERAR: {path}",
        f"DESCRIPCIÓN: {description}",
    ]

    if build_state:
        state_block = build_state.format_state_block()
        mistakes_block = build_state.format_mistakes_block()
        if state_block:
            parts.append(state_block)
        if mistakes_block:
            parts.append(mistakes_block)

    if scaffold_mode:
        parts.append(
            "MODO SCAFFOLD: generá solo estructura, interfaces, firmas y exports. "
            "Sin implementación completa todavía."
        )

    dep_blocks: List[str] = []
    for dep in depends_on:
        if dep not in written_paths:
            continue
        dep_path = written_paths[dep]
        if not dep_path.exists():
            continue
        try:
            text = dep_path.read_text(encoding="utf-8")
        except OSError:
            continue
        dep_blocks.append(
            f"--- {dep} ---\n{extract_snippet(text)}\n--- fin {dep} ---"
        )

    if dep_blocks:
        parts.append("ARCHIVOS DEPENDIENTES (solo deps directas):\n" + "\n".join(dep_blocks))
    else:
        parts.append("ARCHIVOS DEPENDIENTES: (ninguno escrito aún)")

    planned = [normalize_path(f["path"]) for f in plan.get("files", [])]
    parts.append(
        f"MANIFIESTO ({len(planned)} archivos, paths solamente):\n"
        + "\n".join(f"  - {p}" for p in planned)
    )

    return "\n\n".join(parts)
