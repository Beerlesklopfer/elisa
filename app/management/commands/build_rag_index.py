"""
Baut den Norm-RAG-Index auf: PDFs -> Chunks -> Embeddings (Ollama) -> Postgres/pgvector.

Fester, wiederholbar ausführbarer Teil des Systems. Ollama erzeugt die
Embeddings; das Modell wird NICHT trainiert (CLAUDE.md: RAG statt Fine-Tuning).
Schreibt in `EmbeddingChunk` (Collection 'normen'), aus dem die App liest.

Verwendung:
    python manage.py build_rag_index                 # alle PDFs aus incoming/
    python manage.py build_rag_index --source rag/documents
    python manage.py build_rag_index --only IEC61508-3
    python manage.py build_rag_index --reset         # Collection vorher leeren
"""
import glob
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Max

from app import rag_service

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


class Command(BaseCommand):
    help = "Baut den Norm-RAG-Index aus PDFs (Ollama-Embeddings -> pgvector)."

    def add_arguments(self, parser):
        parser.add_argument("--source", default=str(settings.INCOMING_DIR),
                            help="Verzeichnis mit Norm-PDFs (Default: INCOMING_DIR).")
        parser.add_argument("--only", default="",
                            help="Nur Dateien mit diesem Teilstring im Namen.")
        parser.add_argument("--reset", action="store_true",
                            help="Collection vor dem Aufbau leeren (Neuaufbau).")

    def handle(self, *args, **opts):
        import shutil
        from pypdf import PdfReader
        from app.models import EmbeddingChunk

        COLL = rag_service.COLLECTION
        source = opts["source"]
        only = opts["only"].lower()
        archive = settings.RAG_ARCHIVE_DIR
        archive.mkdir(parents=True, exist_ok=True)

        pdfs = sorted(glob.glob(os.path.join(source, "*.pdf"))
                      + glob.glob(os.path.join(source, "*.PDF")))
        if only:
            pdfs = [p for p in pdfs if only in os.path.basename(p).lower()]
        if not pdfs:
            self.stderr.write(f"Keine PDFs in {source} (Filter: '{only}').")
            return

        if opts["reset"]:
            EmbeddingChunk.objects.filter(collection=COLL).delete()

        # Seiten je Datei vorab zählen -> Gesamtfortschritt.
        files = []
        for path in pdfs:
            try:
                files.append({"path": path, "name": os.path.basename(path),
                              "pages_total": len(PdfReader(path).pages)})
            except Exception as exc:
                self.stderr.write(f"  ! {os.path.basename(path)}: nicht lesbar ({exc})")
        pages_total_all = sum(f["pages_total"] for f in files) or 1

        progress = {
            "running": True, "pid": os.getpid(),
            "started": time.time(), "updated": time.time(),
            "files_total": len(files), "files_done": 0,
            "pages_total": pages_total_all, "pages_done": 0,
            "current": None, "chunks": rag_service.total_chunks(COLL),
            "files": [{"name": f["name"], "pages_total": f["pages_total"],
                       "pages_done": 0, "chunks": 0, "status": "pending"}
                      for f in files],
        }
        rag_service.write_progress(progress)

        self.stdout.write(f"Quelle: {source} | Ziel: {COLL} (pgvector)")
        self.stdout.write(f"PDFs: {len(files)} | Seiten gesamt: {pages_total_all}\n")

        # Bereits indexierte Dateien erkennen (Resume).
        existing_max = {}
        if not opts["reset"]:
            for row in (EmbeddingChunk.objects.filter(collection=COLL)
                        .values("source").annotate(mx=Max("page"))):
                existing_max[row["source"]] = row["mx"] or 0

        total_chunks = 0
        for idx, f in enumerate(files):
            name, path = f["name"], f["path"]
            fp = progress["files"][idx]

            # Resume: schon vollständig? -> nur archivieren.
            if existing_max.get(name, 0) >= f["pages_total"] > 0:
                fp["status"] = "done"
                fp["pages_done"] = f["pages_total"]
                progress["files_done"] += 1
                progress["pages_done"] += f["pages_total"]
                try:
                    shutil.move(path, str(archive / name)); fp["archived"] = True
                except Exception:
                    pass
                rag_service.write_progress(progress)
                self.stdout.write(f"  = {name}: bereits indexiert -> archiviert")
                continue

            fp["status"] = "running"
            progress["current"] = name
            rag_service.write_progress(progress)

            # Dubletten-Erkennung über SHA-256 der Dateibytes (gleicher Inhalt,
            # anderer Name → überspringen).
            file_hash = rag_service.file_sha256(path)
            dupe = rag_service.duplicate_source(file_hash, exclude_source=name)
            if dupe:
                fp["status"] = "done"
                fp["pages_done"] = f["pages_total"]
                progress["files_done"] += 1
                progress["pages_done"] += f["pages_total"]
                try:
                    shutil.move(path, str(archive / name)); fp["archived"] = True
                except Exception:
                    pass
                rag_service.write_progress(progress)
                self.stdout.write(self.style.WARNING(
                    f"  ⊘ {name}: inhaltsgleich zu „{dupe}“ – übersprungen (Dublette)"))
                continue

            reader = PdfReader(path)
            file_chunks = 0
            resume_from = existing_max.get(name, 0)
            for page_no, page in enumerate(reader.pages, start=1):
                if page_no < resume_from:
                    fp["pages_done"] = page_no
                    continue
                text = (page.extract_text() or "").strip()
                chunks = chunk_text(text) if text else []
                if chunks:
                    vecs = rag_service.embed_many(chunks)
                    EmbeddingChunk.objects.filter(
                        collection=COLL, source=name, page=page_no).delete()
                    EmbeddingChunk.objects.bulk_create([
                        EmbeddingChunk(collection=COLL, source=name, page=page_no,
                                       text=chunk, content_hash=file_hash,
                                       uid=rag_service.make_uid(COLL, name, page_no, j),
                                       embedding=vec)
                        for j, (chunk, vec) in enumerate(zip(chunks, vecs))])
                    file_chunks += len(chunks)
                fp["pages_done"] = page_no
                fp["chunks"] = file_chunks
                progress["pages_done"] = sum(x["pages_done"] for x in progress["files"])
                progress["chunks"] = rag_service.total_chunks(COLL)
                progress["updated"] = time.time()
                rag_service.write_progress(progress)

            fp["status"] = "done"
            progress["files_done"] += 1
            total_chunks += file_chunks
            try:
                shutil.move(path, str(archive / name)); fp["archived"] = True
            except Exception as exc:
                self.stderr.write(f"  ! Verschieben fehlgeschlagen ({name}): {exc}")
            rag_service.write_progress(progress)
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ {name}: {file_chunks} Chunks -> archiviert"))

        progress["running"] = False
        progress["current"] = None
        progress["updated"] = time.time()
        rag_service.write_progress(progress)
        self.stdout.write(self.style.SUCCESS(
            f"\nFertig. {total_chunks} neue Chunks, Collection: {rag_service.total_chunks(COLL)}"))
