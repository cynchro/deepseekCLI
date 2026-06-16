"""Escáner determinista de proyectos existentes.

Detecta estructura (monolito vs monorepo), stacks y entry points sin usar el LLM.
Produce un "mapa del proyecto" reutilizable por el onboarding y por el update consciente.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

# Directorios de ruido: nunca se descienden ni cuentan.
_IGNORE_DIRS = {
    ".git", ".deep", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "__pycache__", "dist", "build", ".next", ".nuxt", "out", "target",
    ".idea", ".vscode", "vendor", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "coverage", ".cache", ".gradle", ".terraform", ".parcel-cache",
}

# Marcador de sub-proyecto -> lenguaje base.
_MARKERS = {
    "package.json": "node",
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "setup.py": "python",
    "Pipfile": "python",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "composer.json": "php",
    "Gemfile": "ruby",
    "pubspec.yaml": "dart",
    "mix.exs": "elixir",
}

# Posibles entry points por lenguaje (relativos a la raíz del sub-proyecto).
_ENTRYPOINTS = {
    "python": ["main.py", "app.py", "manage.py", "wsgi.py", "asgi.py",
               "run.py", "__main__.py", "src/main.py"],
    "node": ["index.js", "server.js", "app.js", "main.js", "src/index.js",
             "src/main.js", "src/index.ts", "src/main.ts", "index.ts",
             "src/main.tsx", "src/index.tsx", "src/main.jsx", "src/App.tsx"],
    "go": ["main.go", "cmd/main.go"],
    "rust": ["src/main.rs"],
    "java": ["src/main/java"],
    "php": ["index.php", "public/index.php"],
    "ruby": ["config.ru", "app.rb", "main.rb"],
}

_MAX_TREE_ENTRIES = 200


def scan(root: Path) -> Dict:
    """Escanea `root` y devuelve un mapa estructurado del proyecto."""
    root = Path(root).resolve()
    subprojects = _find_subprojects(root)

    if not subprojects:
        kind = "unknown"
    elif len(subprojects) == 1 and subprojects[0]["path"] == ".":
        kind = "monolith"
    else:
        kind = "monorepo"

    languages = sorted({s["language"] for s in subprojects})
    file_count, tree = _build_tree(root)

    return {
        "name": root.name,
        "root": str(root),
        "kind": kind,
        "languages": languages,
        "subprojects": subprojects,
        "file_count": file_count,
        "tree": tree,
    }


def _find_subprojects(root: Path) -> List[Dict]:
    """Busca marcadores de sub-proyecto y arma una entrada por cada uno."""
    found: Dict[str, Dict] = {}  # rel_dir -> entry (uno por directorio)
    for marker, language in _MARKERS.items():
        for marker_path in root.rglob(marker):
            if _is_ignored(marker_path, root):
                continue
            sub_dir = marker_path.parent
            rel = _rel(sub_dir, root)
            # Un mismo directorio puede tener varios marcadores; nos quedamos
            # con el primero pero acumulamos info de framework.
            if rel not in found:
                found[rel] = {
                    "path": rel,
                    "language": language,
                    "markers": [marker],
                    "framework": _detect_framework(sub_dir, language),
                    "entrypoints": _detect_entrypoints(sub_dir, language),
                }
            else:
                found[rel]["markers"].append(marker)
                if not found[rel]["framework"]:
                    found[rel]["framework"] = _detect_framework(sub_dir, language)

    # Orden estable: la raíz primero, después alfabético.
    return sorted(found.values(), key=lambda s: (s["path"] != ".", s["path"]))


def _detect_framework(sub_dir: Path, language: str) -> Optional[str]:
    """Heurística liviana de framework leyendo manifiestos."""
    try:
        if language == "node":
            pkg = json.loads((sub_dir / "package.json").read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for name, label in (
                ("next", "Next.js"), ("@angular/core", "Angular"),
                ("@nestjs/core", "NestJS"), ("nuxt", "Nuxt"),
                ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"),
                ("express", "Express"), ("fastify", "Fastify"),
                ("vite", "Vite"),
            ):
                if name in deps:
                    return label
            return None
        if language == "python":
            blob = ""
            for fname in ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py"):
                fp = sub_dir / fname
                if fp.exists():
                    blob += fp.read_text(encoding="utf-8", errors="ignore").lower()
            for needle, label in (
                ("django", "Django"), ("fastapi", "FastAPI"),
                ("flask", "Flask"), ("starlette", "Starlette"),
                ("aiohttp", "aiohttp"), ("tornado", "Tornado"),
            ):
                if needle in blob:
                    return label
            return None
    except Exception:
        return None
    return None


def _detect_entrypoints(sub_dir: Path, language: str) -> List[str]:
    found = []
    for candidate in _ENTRYPOINTS.get(language, []):
        if (sub_dir / candidate).exists():
            found.append(candidate)
    return found


def _build_tree(root: Path) -> tuple:
    """Devuelve (cantidad_de_archivos, árbol_textual_truncado)."""
    lines: List[str] = []
    count = 0
    entries = 0

    def walk(directory: Path, prefix: str):
        nonlocal count, entries
        try:
            children = sorted(
                directory.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),
            )
        except (PermissionError, OSError):
            return
        for child in children:
            if child.is_dir() and child.name in _IGNORE_DIRS:
                continue
            if child.is_file():
                count += 1
            if entries >= _MAX_TREE_ENTRIES:
                continue
            entries += 1
            lines.append(f"{prefix}{child.name}{'/' if child.is_dir() else ''}")
            if child.is_dir():
                walk(child, prefix + "  ")

    walk(root, "")
    if entries >= _MAX_TREE_ENTRIES:
        lines.append("  … (árbol truncado)")
    return count, "\n".join(lines)


def format_map(pmap: Dict) -> str:
    """Render legible del mapa para mostrar en la terminal."""
    kind_label = {
        "monolith": "monolito",
        "monorepo": "monorepo",
        "unknown": "estructura no reconocida",
    }.get(pmap["kind"], pmap["kind"])

    lines = [
        f"📂 Proyecto: {pmap['name']}  ({kind_label}, {pmap['file_count']} archivos)",
    ]
    subs = pmap.get("subprojects", [])
    if subs:
        lines.append("   Componentes:")
        for s in subs:
            loc = "raíz" if s["path"] == "." else s["path"]
            stack = s["language"]
            if s.get("framework"):
                stack += f"/{s['framework']}"
            entry = f"  →  {', '.join(s['entrypoints'])}" if s.get("entrypoints") else ""
            lines.append(f"     • {loc}: {stack}{entry}")
    elif pmap.get("languages"):
        lines.append(f"   Lenguajes: {', '.join(pmap['languages'])}")
    return "\n".join(lines)


def _rel(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return rel if rel else "."


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in _IGNORE_DIRS for part in parts)


# ── selección de archivos relevantes (para update consciente) ──────────────────

# Extensiones de texto/código que tiene sentido enviar al LLM.
_TEXT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".go", ".rs",
    ".java", ".kt", ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp", ".dart",
    ".html", ".css", ".scss", ".sass", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".env", ".md", ".txt", ".sql", ".sh", ".xml",
}
_MAX_FILE_BYTES = 200_000
_STOPWORDS = {
    "the", "and", "for", "que", "con", "los", "las", "del", "una", "uno",
    "por", "para", "como", "este", "esta", "que", "agregar", "agrega", "add",
    "crear", "crea", "create", "hacer", "haz", "make", "cambiar", "cambia",
    "modificar", "modifica", "update", "nuevo", "nueva", "new",
}


def select_relevant_files(root, pmap: Dict, change: str, max_files: int = 12):
    """Selecciona los archivos más relevantes a `change`, respetando fronteras de sub-proyecto.

    Devuelve `(archivos: List[Path], target_subs: List[str])`. `target_subs` vacío
    significa "sin restricción de componente" (monolito o cambio ambiguo).
    """
    root = Path(root)
    tokens = _tokenize(change)
    subs = pmap.get("subprojects", []) if pmap else []

    candidates = [
        f for f in root.rglob("*")
        if f.is_file() and not _is_ignored(f, root) and _is_text_file(f)
    ]

    target_subs = _target_subprojects(subs, tokens)
    if target_subs:
        candidates = [
            f for f in candidates if _subproject_of(f, root, subs) in target_subs
        ]

    scored = [(_relevance(f, root, tokens), f) for f in candidates]
    scored.sort(key=lambda x: (-x[0], str(x[1])))
    selected = [f for _, f in scored[:max_files]]
    return selected, target_subs


def _tokenize(text: str) -> set:
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _is_text_file(path: Path) -> bool:
    if path.name.startswith("."):
        return path.suffix in _TEXT_EXTS or path.name in (".env", ".gitignore")
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return path.suffix in _TEXT_EXTS or path.suffix == ""


def _target_subprojects(subs: List[Dict], tokens: set) -> List[str]:
    """Sub-proyectos mencionados (por nombre de carpeta, lenguaje o framework)."""
    targets = []
    for s in subs:
        if s["path"] == ".":
            continue
        keywords = set(_tokenize(s["path"]))
        keywords.add(s.get("language", "").lower())
        if s.get("framework"):
            keywords.add(s["framework"].lower())
        if keywords & tokens:
            targets.append(s["path"])
    return targets


def _subproject_of(path: Path, root: Path, subs: List[Dict]) -> str:
    """Devuelve el path del sub-proyecto que contiene a `path` (el prefijo más largo)."""
    rel = path.relative_to(root).as_posix()
    best = "."
    for s in subs:
        sp = s["path"]
        if sp == ".":
            continue
        if rel == sp or rel.startswith(sp + "/"):
            if len(sp) > len(best):
                best = sp
    return best


def _relevance(path: Path, root: Path, tokens: set) -> int:
    """Puntaje por solapamiento de tokens; el path pesa más que el contenido."""
    rel = path.relative_to(root).as_posix()
    score = len(_tokenize(rel) & tokens) * 3
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
        score += len(_tokenize(head) & tokens)
    except Exception:
        pass
    return score
