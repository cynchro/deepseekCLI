"""Índice de recuperación de código (BM25 léxico) para el agent loop.

No usa embeddings (DeepSeek no expone endpoint de embeddings): rankea chunks de
código por relevancia léxica a la consulta con Okapi BM25, con tokenización
consciente de código (parte camelCase y snake_case). Para buscar en un codebase
grande es mucho mejor que grep —que es binario, matchea o no— porque devuelve los
N fragmentos MÁS relevantes con su ubicación.

Es Python puro, sin dependencias ni descargas. El índice es incremental: solo
re-chunkea los archivos que cambiaron (fingerprint mtime+size) y se persiste en
`.deep/index/`. El scoring está desacoplado, así que más adelante se puede enchufar
un backend de embeddings (ej. fastembed) sin tocar el resto.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".deep",
              "dist", "build", ".rag", ".pytest_cache", ".mypy_cache", ".idea",
              ".egg-info", "site-packages"}
_SKIP_SUFFIXES = {".lock", ".min.js", ".map", ".png", ".jpg", ".jpeg", ".gif",
                  ".pdf", ".zip", ".tar", ".gz", ".whl", ".npy", ".bin", ".ico",
                  ".woff", ".woff2", ".ttf", ".mp4", ".mp3"}
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml"}

_MAX_FILE_BYTES = 400_000
_CHUNK_LINES = 60
_CHUNK_OVERLAP = 15

_WORD = re.compile(r"[A-Za-z0-9_]+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def tokenize(text: str) -> list:
    """Tokeniza texto/código: cada palabra baja a minúsculas y además se parte por
    snake_case y camelCase, así 'getUserName' matchea 'user' y 'name'."""
    out = []
    for w in _WORD.findall(text):
        wl = w.lower()
        out.append(wl)
        for part in w.split("_"):
            pl = part.lower()
            if pl and pl != wl:
                out.append(pl)
        for part in _CAMEL.findall(w):
            pl = part.lower()
            if pl and pl != wl:
                out.append(pl)
    return out


def _iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in p.parts):
            continue
        if p.name in _SKIP_NAMES or p.suffix.lower() in _SKIP_SUFFIXES:
            continue
        try:
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield p


def _fingerprint(p: Path) -> str:
    st = p.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _chunk_file(rel_path: str, text: str) -> list:
    """Parte un archivo en ventanas de líneas con solapamiento. Cada chunk guarda
    su rango de líneas para poder citar archivo:línea."""
    lines = text.splitlines()
    if not lines:
        return []
    chunks = []
    step = max(_CHUNK_LINES - _CHUNK_OVERLAP, 1)
    for start in range(0, len(lines), step):
        window = lines[start:start + _CHUNK_LINES]
        body = "\n".join(window).strip()
        if not body:
            continue
        chunks.append({
            "path": rel_path,
            "start": start + 1,
            "end": min(start + _CHUNK_LINES, len(lines)),
            "text": "\n".join(window),
        })
        if start + _CHUNK_LINES >= len(lines):
            break
    return chunks


class CodeIndex:
    """Índice BM25 incremental sobre los archivos de texto del workspace."""

    k1 = 1.5
    b = 0.75

    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.dir = self.workspace / ".deep" / "index"
        self.manifest_path = self.dir / "manifest.json"
        self.chunks_path = self.dir / "chunks.json"
        self.manifest = {}      # rel_path -> fingerprint
        self.chunks = []        # [{path, start, end, text}]
        # estructuras BM25 en memoria (se reconstruyen al cargar/indexar)
        self._tf = []           # por chunk: Counter de términos
        self._len = []          # por chunk: longitud en tokens
        self._df = Counter()    # término -> nº de chunks que lo contienen
        self._avgdl = 0.0

    # ── persistencia ──────────────────────────────────────────────────────────
    def _load(self):
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self.chunks = json.loads(self.chunks_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.manifest, self.chunks = {}, []

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.chunks_path.write_text(json.dumps(self.chunks), encoding="utf-8")

    # ── indexado incremental ────────────────────────────────────────────────────
    def build(self) -> dict:
        """Re-chunkea solo lo que cambió y reconstruye las estructuras BM25.
        Devuelve {files, chunks, changed}."""
        self._load()
        current = {}
        for p in _iter_files(self.workspace):
            rel = str(p.relative_to(self.workspace))
            try:
                current[rel] = _fingerprint(p)
            except OSError:
                continue

        changed = [rel for rel, fp in current.items() if self.manifest.get(rel) != fp]
        removed = [rel for rel in self.manifest if rel not in current]

        if changed or removed:
            stale = set(changed) | set(removed)
            kept = [c for c in self.chunks if c["path"] not in stale]
            for rel in changed:
                try:
                    text = (self.workspace / rel).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                kept.extend(_chunk_file(rel, text))
            self.chunks = kept
            self.manifest = current
            self._save()

        self._reindex()
        return {"files": len(current), "chunks": len(self.chunks),
                "changed": len(changed) + len(removed)}

    def _reindex(self):
        self._tf, self._len, self._df = [], [], Counter()
        for c in self.chunks:
            toks = tokenize(c["text"])
            tf = Counter(toks)
            self._tf.append(tf)
            self._len.append(len(toks))
            for term in tf:
                self._df[term] += 1
        self._avgdl = (sum(self._len) / len(self._len)) if self._len else 0.0

    # ── búsqueda ────────────────────────────────────────────────────────────────
    def search(self, query: str, k: int = 8) -> list:
        if not self.chunks:
            return []
        q_terms = set(tokenize(query))
        if not q_terms:
            return []
        n = len(self.chunks)
        idf = {}
        for t in q_terms:
            df = self._df.get(t, 0)
            if df:
                idf[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))
        if not idf:
            return []
        scored = []
        for i, tf in enumerate(self._tf):
            dl = self._len[i] or 1
            s = 0.0
            for t, w in idf.items():
                f = tf.get(t, 0)
                if f:
                    s += w * (f * (self.k1 + 1)) / (
                        f + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1)))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        out = []
        for s, i in scored[:k]:
            c = self.chunks[i]
            out.append({"path": c["path"], "start": c["start"], "end": c["end"],
                        "score": round(s, 3), "text": c["text"]})
        return out
