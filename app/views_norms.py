"""
Normen-Tab: Norm-PDFs hochladen und in den RAG-Index aufnehmen.

Self-service: Nutzer laden lizenzierte Norm-PDFs hoch (landen in incoming/);
ein Klick stößt den Index-Aufbau an (manage.py build_rag_index), der Ollama
die Embeddings erzeugen lässt. Das Modell wird nicht trainiert (RAG).

Hinweis: Norm-PDFs sind i. d. R. lizenzpflichtig – nur lizenzierte Dokumente
hochladen.
"""
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from app import rag_service, norm_refs
from app.models import NormClause, NormLink

INCOMING = settings.INCOMING_DIR   # bewusst per Dateisystem erreichbar (Share)
ARCHIVE = settings.RAG_ARCHIVE_DIR  # schreibbar (im Prod unter /var/lib)


@lru_cache(maxsize=128)
def _pdf_pages(path: str, mtime: float) -> int:
    """Seitenzahl einer PDF (gecacht über (Pfad, mtime))."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        return 0


def _chroma_stats():
    """{name: {'chunks': n, 'max_page': p}} live aus der DB (pgvector)."""
    return rag_service.stats_by_source()


def _queue_and_index():
    """
    Baut zwei Listen:
      queue  – PDFs in incoming/ (Warteschlange), mit Fortschritt % der aktiven.
      indexed – Normen, die nur noch im Index/Archiv liegen (aus incoming entfernt).
    """
    stats = _chroma_stats()
    running = _is_indexing()

    INCOMING.mkdir(exist_ok=True)
    incoming = sorted(INCOMING.glob("*.pdf")) + sorted(INCOMING.glob("*.PDF"))
    incoming_names = [p.name for p in incoming]

    # Vorab: welche incoming-Datei hat schon Chunks? (für "Prozess ist weiter"-Heuristik)
    started_flags = [stats.get(p.name, {}).get("chunks", 0) > 0 for p in incoming]

    queue, done_in_incoming = [], []
    for i, p in enumerate(incoming):
        name = p.name
        total = _pdf_pages(str(p), p.stat().st_mtime)
        st = stats.get(name, {"chunks": 0, "max_page": 0, "kind": ""})
        pct = int(st["max_page"] / total * 100) if total else 0
        # "fertig", wenn alle Seiten erreicht ODER eine spätere Datei schon begonnen hat
        later_started = any(started_flags[i + 1:])
        is_done = st["chunks"] > 0 and (st["max_page"] >= total or later_started)
        if is_done:
            done_in_incoming.append({"name": name, "chunks": st["chunks"],
                                     "pages": st["max_page"], "kind": st.get("kind", "")})
            continue
        if st["chunks"] == 0:
            status = "pending"
        elif running:
            status = "running"
        else:
            status = "partial"   # angefangen, aber Prozess läuft nicht
        queue.append({
            "name": name, "size_mb": round(p.stat().st_size / 1_048_576, 1),
            "chunks": st["chunks"], "pages_total": total,
            "pages_done": st["max_page"], "percent": min(pct, 100), "status": status,
        })

    # Indexiert = vollständig (egal ob noch in incoming oder schon archiviert).
    archived = [{"name": n, "chunks": s["chunks"], "pages": s["max_page"],
                 "kind": s.get("kind", "")}
                for n, s in sorted(stats.items()) if n not in incoming_names]
    indexed = sorted(done_in_incoming + archived, key=lambda x: x["name"])
    available_names = set(stats.keys()) | set(incoming_names)
    return queue, indexed, available_names, running


def _normalize(s: str) -> str:
    """Vergleichsform: nur Buchstaben/Ziffern, klein (z. B. 'IEC 61508-3' -> 'iec615083')."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _standard_available(standard: str, pdf_names) -> str | None:
    """Gibt den passenden PDF-Dateinamen zurück, falls eine Norm vorliegt, sonst None."""
    key = _normalize(standard)
    if not key:
        return None
    for name in pdf_names:
        if key in _normalize(name):
            return name
    return None


@login_required
def norms_index(request):
    queue, indexed, available_names, running = _queue_and_index()
    chunk_count = sum(i["chunks"] for i in indexed) + sum(q["chunks"] for q in queue)
    pdf_names = list(available_names)

    # ── Gap-Analyse: vorhanden vs. referenziert vs. zu beschaffen ──────────
    # Referenziert = Normen, die WorkItems DES AKTIVEN PROJEKTS über
    # (bestätigte) NormLinks nutzen.
    from app.projects import get_active_project
    project = get_active_project(request)
    ref_rows = (
        NormClause.objects
        .filter(normlink__confirmed=True, normlink__item__project=project)
        .values("standard")
        .annotate(items=Count("normlink", distinct=True))
        .order_by("standard")
    )
    referenced = []
    to_procure = []
    for row in ref_rows:
        std = row["standard"]
        pdf = _standard_available(std, pdf_names)
        entry = {"standard": std, "items": row["items"],
                 "available": bool(pdf), "pdf": pdf}
        referenced.append(entry)
        if not pdf:
            to_procure.append(entry)

    # In der DB bekannte Normen (NormClause), egal ob referenziert.
    db_standards = (
        NormClause.objects.values("standard")
        .annotate(clauses=Count("id")).order_by("standard")
    )
    db_standards = [
        {**row, "available": bool(_standard_available(row["standard"], pdf_names))}
        for row in db_standards
    ]

    # Beschaffungsbedarf aus den Verweisen IN den Normtexten.
    # Checkbox „informative ignorieren" blendet TR/TS/Guide aus.
    ignore_informative = request.GET.get("ignore_informative") in ("1", "on", "true")
    procurement = norm_refs.procurement_gap(ignore_informative=ignore_informative)

    return render(request, "norms.html", {
        "active_tab": "norms",
        "queue": queue,
        "indexed": indexed,
        "chunk_count": chunk_count,
        "indexing": running,
        "referenced": referenced,
        "to_procure": to_procure,
        "db_standards": db_standards,
        "procurement": procurement,
        "ignore_informative": ignore_informative,
        "norm_classes": NORM_CLASSES,
        "incoming_path": str(INCOMING),
    })


@login_required
@xframe_options_sameorigin   # erlaubt das Einbetten der inline-PDF im iframe (sonst X-Frame-Options: DENY)
def norms_download(request):
    """Liefert eine Norm-PDF aus. `?inline=1` → inline (zum Einbetten/Anspringen
    einer Seite via #page=N), sonst als Download."""
    name = Path(request.GET.get("name", "")).name  # nur Basename (kein Traversal)
    if not name:
        raise Http404("kein Dateiname")
    inline = request.GET.get("inline") in ("1", "true", "on")
    for base in (ARCHIVE, INCOMING):
        path = base / name
        if path.is_file():
            return FileResponse(open(path, "rb"), as_attachment=not inline, filename=name)
    raise Http404("Datei nicht gefunden")


@login_required
@require_POST
def norms_forget(request):
    """
    „Vergessen": ein importiertes Dokument vollständig entfernen — Chunks aus
    dem Index UND die archivierte/eingehende PDF-Datei.
    """
    name = request.POST.get("name", "")
    if not name:
        return redirect("norms")
    removed = 0
    try:
        removed = rag_service.forget_source(name)
    except Exception as exc:
        messages.warning(request, f"Index-Bereinigung fehlgeschlagen: {exc}")
    # Datei aus Archiv bzw. incoming löschen.
    for path in (ARCHIVE / name, INCOMING / name):
        try:
            if path.is_file():
                path.unlink()
        except Exception:
            pass
    messages.info(request, f"„{name}“ vergessen ({removed} Chunks entfernt).")
    return redirect("norms")


@login_required
@require_POST
def norms_rename(request):
    """UPDATE: indexierte Norm umbenennen (Chunks + Archiv-/incoming-Datei)."""
    old = (request.POST.get("name") or "").strip()
    new = (request.POST.get("new_name") or "").strip()
    if not old or not new or old == new:
        return redirect("norms")
    try:
        n = rag_service.rename_source(old, new)
        for d in (ARCHIVE, INCOMING):
            src = d / old
            if src.is_file():
                src.rename(d / new)
        messages.success(request, f"„{old}“ → „{new}“ ({n} Chunks aktualisiert).")
    except Exception as exc:
        messages.warning(request, f"Umbenennen fehlgeschlagen: {exc}")
    return redirect("norms")


NORM_CLASSES = [("", "— unklassifiziert"), ("normative", "Normativ"),
                ("informative", "Informativ")]


@login_required
@require_POST
def norms_classify(request):
    """UPDATE: Klassifizierung einer indexierten Norm (Normativ/Informativ)."""
    name = (request.POST.get("name") or "").strip()
    cls = (request.POST.get("classification") or "").strip()
    valid = {c for c, _ in NORM_CLASSES}
    if name and cls in valid:
        n = rag_service.classify_source(name, cls)
        label = dict(NORM_CLASSES).get(cls, cls or "—")
        messages.success(request, f"„{name}“ klassifiziert als {label} ({n} Chunks).")
    return redirect("norms")


@login_required
def norms_progress(request):
    """JSON-Fortschritt fürs Polling: Warteschlange (mit %), Index, läuft?"""
    queue, indexed, _avail, running = _queue_and_index()
    return JsonResponse({
        "running": running,
        "chunk_count": sum(i["chunks"] for i in indexed) + sum(q["chunks"] for q in queue),
        "queue": queue,
        "indexed": indexed,
    })


@login_required
@require_POST
def norms_upload(request):
    INCOMING.mkdir(exist_ok=True)
    files = request.FILES.getlist("pdfs")
    saved = 0
    for f in files:
        if not f.name.lower().endswith(".pdf"):
            messages.warning(request, f"Übersprungen (keine PDF): {f.name}")
            continue
        # einfacher, sicherer Dateiname
        safe = Path(f.name).name
        with open(INCOMING / safe, "wb") as out:
            for chunk in f.chunks():
                out.write(chunk)
        saved += 1
    if saved:
        messages.success(request, f"{saved} PDF(s) hochgeladen nach incoming/.")
    return redirect("norms")


@login_required
@require_POST
def norms_build(request):
    """Stößt den Index-Aufbau im Hintergrund an (nicht blockierend)."""
    only = request.POST.get("only", "")
    args = [sys.executable, str(settings.BASE_DIR / "manage.py"),
            "build_rag_index"]
    if only:
        args += ["--only", Path(only).stem]
    # Log nach /var/lib (BASE_DIR ist im Produktivbetrieb read-only); absturzsicher.
    try:
        log = open(settings.DATA_DIR / "rag_index.log", "ab")
    except OSError:
        log = subprocess.DEVNULL
    try:
        subprocess.Popen(args, cwd=str(settings.BASE_DIR), stdout=log, stderr=log)
        messages.info(request, "Indexierung gestartet (läuft im Hintergrund). "
                               "Seite später aktualisieren.")
    except Exception as exc:
        messages.error(request, f"Indexierung konnte nicht gestartet werden: {exc}")
    return redirect("norms")


def _is_indexing():
    """Läuft eine Indexierung? Aus der Fortschrittsdatei (läuft + Lebenszeichen der
    letzten 3 Minuten) – pgrep gibt es im Container-Image nicht, und der Lauf kann
    in einem anderen Container (MCP) gestartet worden sein."""
    import time
    from app import rag_service
    pr = rag_service.read_progress()
    return bool(pr.get("running")) and time.time() - float(pr.get("updated", 0)) < 180
