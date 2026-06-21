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

import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv",
              ".deep", "dist", "build", ".rag", ".pytest_cache", ".mypy_cache",
              ".idea", ".egg-info", "site-packages"}

# Tamaño de lote al calcular embeddings. Embeber miles de chunks en una sola
# llamada hace explotar la RAM (el modelo + onnxruntime materializa todo junto);
# en lotes el pico queda acotado sin importar el tamaño del repo.
_EMBED_BATCH = 32
_SKIP_SUFFIXES = {".lock", ".min.js", ".map", ".png", ".jpg", ".jpeg", ".gif",
                  ".pdf", ".zip", ".tar", ".gz", ".whl", ".npy", ".bin", ".ico",
                  ".woff", ".woff2", ".ttf", ".mp4", ".mp3"}
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml"}

_MAX_FILE_BYTES = 400_000
_CHUNK_LINES = 60
_CHUNK_OVERLAP = 15

_WORD = re.compile(r"[A-Za-z0-9_]+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

# Peso del componente semántico en el score híbrido (el resto es BM25 léxico).
_HYBRID_ALPHA = 0.5


def get_embedder():
    """Backend de embeddings OPCIONAL y enchufable. Devuelve un callable
    (list[str] -> list[list[float]]) si hay un backend disponible, o None para caer a
    BM25 puro. Hoy soporta `fastembed` (dependencia opcional, no se importa salvo acá).
    Se desactiva con DEEP_NO_SEMANTIC=1."""
    if os.getenv("DEEP_NO_SEMANTIC"):
        return None
    try:
        from fastembed import TextEmbedding
    except Exception:
        return None
    # Modelo configurable. Para consultas en español conviene uno multilingüe, ej.
    # DEEP_EMBED_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2".
    # Sin setear, usa el default de fastembed (English-centric, liviano).
    model_name = (os.getenv("DEEP_EMBED_MODEL") or "").strip()
    try:
        model = TextEmbedding(model_name=model_name) if model_name else TextEmbedding()
    except Exception:
        return None

    def embed(texts):
        return [list(map(float, v)) for v in model.embed(list(texts))]

    return embed


def _cosine(a, b) -> float:
    """Coseno en Python puro (sin numpy, para no agregar deps al camino base)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


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

    def __init__(self, workspace, embedder=None):
        self.workspace = Path(workspace).resolve()
        self.dir = self.workspace / ".deep" / "index"
        self.manifest_path = self.dir / "manifest.json"
        self.chunks_path = self.dir / "chunks.json"
        self.vectors_path = self.dir / "vectors.json"
        self.embedder = embedder   # callable opcional; None -> solo BM25
        self.manifest = {}      # rel_path -> fingerprint
        self.chunks = []        # [{path, start, end, text}]
        self.vectors = {}       # chunk_hash -> vector (solo si hay embedder)
        # estructuras BM25 en memoria (se reconstruyen al cargar/indexar)
        self._tf = []           # por chunk: Counter de términos
        self._len = []          # por chunk: longitud en tokens
        self._df = Counter()    # término -> nº de chunks que lo contienen
        self._avgdl = 0.0

    @staticmethod
    def _chunk_hash(c) -> str:
        h = hashlib.sha1(f"{c['path']}:{c['start']}:{c['text']}".encode("utf-8"))
        return h.hexdigest()

    # ── persistencia ──────────────────────────────────────────────────────────
    def _load(self):
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self.chunks = json.loads(self.chunks_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.manifest, self.chunks = {}, []
        if self.embedder is not None:
            try:
                self.vectors = json.loads(self.vectors_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.vectors = {}

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.chunks_path.write_text(json.dumps(self.chunks), encoding="utf-8")

    def _embed_missing(self):
        """Calcula y persiste los vectores de los chunks que aún no tienen (incremental).
        Descarta vectores de chunks que ya no existen."""
        if self.embedder is None:
            return
        hashes = [self._chunk_hash(c) for c in self.chunks]
        missing = [h for h, c in zip(hashes, self.chunks) if h not in self.vectors]
        if missing:
            by_hash = {self._chunk_hash(c): c for c in self.chunks}
            # Por lotes: acota el pico de RAM y persiste el progreso, así una
            # interrupción no obliga a recalcular todo desde cero la próxima vez.
            for i in range(0, len(missing), _EMBED_BATCH):
                batch = missing[i:i + _EMBED_BATCH]
                try:
                    vecs = self.embedder([by_hash[h]["text"] for h in batch])
                except Exception:
                    break  # si el embedder falla, persistimos lo hecho y seguimos con BM25
                for h, v in zip(batch, vecs):
                    self.vectors[h] = v
                self._persist_vectors(hashes)
        self._persist_vectors(hashes)

    def _persist_vectors(self, hashes):
        """Poda vectores huérfanos y persiste el índice de vectores en disco."""
        self.vectors = {h: self.vectors[h] for h in hashes if h in self.vectors}
        try:
            self.vectors_path.write_text(json.dumps(self.vectors), encoding="utf-8")
        except OSError:
            pass

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
        self._embed_missing()
        return {"files": len(current), "chunks": len(self.chunks),
                "changed": len(changed) + len(removed), "semantic": self.embedder is not None}

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

    def _bm25_scores(self, query: str) -> dict:
        """Score BM25 por chunk para la consulta. {i: score} solo de los que matchean."""
        q_terms = set(tokenize(query))
        if not q_terms:
            return {}
        n = len(self.chunks)
        idf = {}
        for t in q_terms:
            df = self._df.get(t, 0)
            if df:
                idf[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))
        scores = {}
        for i, tf in enumerate(self._tf):
            dl = self._len[i] or 1
            s = 0.0
            for t, w in idf.items():
                f = tf.get(t, 0)
                if f:
                    s += w * (f * (self.k1 + 1)) / (
                        f + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1)))
            if s > 0:
                scores[i] = s
        return scores

    # ── búsqueda ────────────────────────────────────────────────────────────────
    def search(self, query: str, k: int = 8) -> list:
        """Devuelve los k chunks más relevantes. Con embedder activo usa score híbrido
        (BM25 léxico + coseno semántico), que además rescata matches que el léxico no ve
        (ej. consulta en español sobre identificadores en inglés). Sin embedder: BM25 puro."""
        if not self.chunks:
            return []
        bm25 = self._bm25_scores(query)

        use_semantic = (self.embedder is not None and self.vectors)
        if not use_semantic:
            ranked = sorted(bm25.items(), key=lambda kv: kv[1], reverse=True)
            chosen = [(i, s) for i, s in ranked[:k]]
        else:
            try:
                qvec = self.embedder([query])[0]
            except Exception:
                qvec = None
            if qvec is None:
                ranked = sorted(bm25.items(), key=lambda kv: kv[1], reverse=True)
                chosen = [(i, s) for i, s in ranked[:k]]
            else:
                bm_max = max(bm25.values()) if bm25 else 0.0
                final = {}
                for i, c in enumerate(self.chunks):
                    bm_norm = (bm25.get(i, 0.0) / bm_max) if bm_max else 0.0
                    cos = max(0.0, _cosine(qvec, self.vectors.get(self._chunk_hash(c), [])))
                    score = _HYBRID_ALPHA * cos + (1 - _HYBRID_ALPHA) * bm_norm
                    if score > 0:
                        final[i] = score
                chosen = sorted(final.items(), key=lambda kv: kv[1], reverse=True)[:k]

        out = []
        for i, s in chosen:
            c = self.chunks[i]
            out.append({"path": c["path"], "start": c["start"], "end": c["end"],
                        "score": round(s, 3), "text": c["text"]})
        return out
