"""
Norm-RAG über Postgres + pgvector (löst ChromaDB ab).

Embeddings (nomic-embed-text, 768 Dim) liegen in `EmbeddingChunk`; die Suche
ist eine Kosinus-Distanz-Abfrage (HNSW-Index). Degradiert elegant: fehlt der
Index oder Ollama, gibt es einfach keinen Kontext (der Chat läuft ohne Normbezug
weiter). Kein Fine-Tuning – die Norm ist externes Wissen zur Laufzeit (CLAUDE.md).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from django.conf import settings

COLLECTION = os.getenv("RAG_COLLECTION", "normen")
TOP_K = int(os.getenv("RAG_TOP_K", "4"))

# Fortschrittsdatei, die der Index-Aufbau (build_rag_index) fortlaufend schreibt.
PROGRESS_PATH = Path(os.getenv(
    "RAG_PROGRESS_FILE", str(settings.DATA_DIR / "index_progress.json")))


# ── Fortschritt (datei-basiert, unverändert) ───────────────────────────────

def read_progress() -> dict:
    try:
        return json.loads(PROGRESS_PATH.read_text())
    except Exception:
        return {}


def write_progress(data: dict) -> None:
    try:
        PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_PATH.write_text(json.dumps(data))
    except Exception:
        pass


# ── Embeddings (Ollama oder Eliezer, siehe app/local_llm.py) ──────────────

from app.local_llm import embed_one, embed_many  # noqa: E402,F401


def make_uid(*parts) -> str:
    return hashlib.md5("-".join(str(p) for p in parts).encode()).hexdigest()


def file_sha256(path) -> str:
    """SHA-256 der Dateibytes (Dokument-Inhalts-Hash für Dubletten-Erkennung)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def duplicate_source(content_hash: str, exclude_source: str = "",
                     collection: str = COLLECTION):
    """Liefert den Quellnamen mit gleichem Inhalts-Hash (≠ exclude) oder None."""
    from app.models import EmbeddingChunk
    if not content_hash:
        return None
    qs = EmbeddingChunk.objects.filter(collection=collection,
                                       content_hash=content_hash)
    if exclude_source:
        qs = qs.exclude(source=exclude_source)
    row = qs.values_list("source", flat=True).first()
    return row


# ── Index-Statistik (aus der DB, Quelle der Wahrheit) ──────────────────────

def chunk_counts_by_source(collection: str = COLLECTION) -> dict:
    """{dateiname: anzahl_chunks} live aus der DB (für die Fortschrittsanzeige)."""
    from app.models import EmbeddingChunk
    try:
        rows = EmbeddingChunk.objects.filter(collection=collection) \
            .values_list("source", flat=True)
        return dict(Counter(rows))
    except Exception:
        return {}


def stats_by_source(collection: str = COLLECTION) -> dict:
    """{quelle: {'chunks','max_page','kind'}} – für die Normen-Übersicht."""
    from app.models import EmbeddingChunk
    stats: dict = {}
    try:
        for src, pg, kind in EmbeddingChunk.objects.filter(collection=collection) \
                .values_list("source", "page", "kind"):
            s = stats.setdefault(src, {"chunks": 0, "max_page": 0, "kind": ""})
            s["chunks"] += 1
            s["max_page"] = max(s["max_page"], pg or 0)
            if kind:
                s["kind"] = kind
    except Exception:
        pass
    return stats


def classify_source(name: str, classification: str,
                    collection: str = COLLECTION) -> int:
    """Setzt die Klassifizierung (kind) aller Chunks einer Quelle. #aktualisiert."""
    from app.models import EmbeddingChunk
    return EmbeddingChunk.objects.filter(
        collection=collection, source=name).update(kind=classification)


def available_norms() -> list[str]:
    """Deterministische Liste der tatsächlich indexierten Norm-Quellen."""
    return sorted(chunk_counts_by_source().keys())


def all_norm_documents() -> list[str]:
    """Alle Norm-Chunk-Texte (für die Beschaffungslücken-Analyse)."""
    from app.models import EmbeddingChunk
    try:
        return list(EmbeddingChunk.objects.filter(collection=COLLECTION)
                    .values_list("text", flat=True))
    except Exception:
        return []


def total_chunks(collection: str = COLLECTION) -> int:
    from app.models import EmbeddingChunk
    try:
        return EmbeddingChunk.objects.filter(collection=collection).count()
    except Exception:
        return 0


def forget_source(name: str, collection: str = COLLECTION) -> int:
    """Löscht alle Chunks einer Quelle. Liefert die Anzahl gelöschter Chunks."""
    from app.models import EmbeddingChunk
    deleted, _ = EmbeddingChunk.objects.filter(
        collection=collection, source=name).delete()
    return deleted


def rename_source(old: str, new: str, collection: str = COLLECTION) -> int:
    """Benennt eine indexierte Quelle um (alle Chunks). Liefert #aktualisiert."""
    from app.models import EmbeddingChunk
    return EmbeddingChunk.objects.filter(
        collection=collection, source=old).update(source=new)


# ── Retrieval (pgvector Kosinus-Distanz) ───────────────────────────────────

def _search(collection: str, question: str, n: int):
    from pgvector.django import CosineDistance
    from app.models import EmbeddingChunk
    emb = embed_one(question)
    if emb is None:
        return []
    qs = (EmbeddingChunk.objects.filter(collection=collection)
          .annotate(dist=CosineDistance("embedding", emb))
          .order_by("dist")[:n])
    return [(c.text, {"quelle": c.source, "seite": c.page, "distanz": float(c.dist)})
            for c in qs]


def retrieve_norm_context(question: str, n: int = TOP_K):
    """Liefert [(chunk, {'quelle','seite'})] aus der Norm-Collection oder []."""
    try:
        return _search(COLLECTION, question, n)
    except Exception:
        return []


def format_context(hits) -> str:
    return "\n\n".join(
        f"[Quelle: {m.get('quelle', '?')}, Seite {m.get('seite', '?')}]\n{doc}"
        for doc, m in hits
    )
