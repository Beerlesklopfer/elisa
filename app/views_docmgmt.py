"""
Dokumentenmanagement je Projekt (Eingangsdokumente).

PEP (Product Engineering Process) und REQ (Kundenanforderungen) sind statisch:
sie kommen vom Kunden und werden im Tool nie verändert. Sie werden zusätzlich
über den MCP-Server read-only bereitgestellt (mcp_server/server.py).
"""
import threading

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_sameorigin

from . import project_index, lifecycle
from .models import ProjectDocument, DocumentKind, Confidentiality, ItemStatus
from .projects import get_active_project
from .permissions import project_member_required


def _index_async(doc_id):
    """Dokument im Hintergrund indizieren (RAG, projekt-skopiert)."""
    def run():
        try:
            doc = ProjectDocument.objects.get(pk=doc_id)
            n = project_index.index_document(doc)
            ProjectDocument.objects.filter(pk=doc_id).update(indexed_chunks=n)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


@login_required
@project_member_required
def doc_list(request):
    project = get_active_project(request)
    docs = project.documents.all()
    is_admin = request.user.is_staff
    def with_next(qs):
        out = []
        for d in qs:
            nxt = lifecycle.next_states(d.status)
            # Signiert/eingefroren: nur Admins dürfen (de)signieren / ändern.
            if not is_admin:
                if d.status == ItemStatus.SIGNED:
                    nxt = []
                else:
                    nxt = [c for c in nxt if c != ItemStatus.SIGNED]
            d.allowed_next = [(c, ItemStatus(c).label) for c in nxt]
            d.is_frozen = d.status == ItemStatus.SIGNED
            out.append(d)
        return out

    main_kinds = {"PEP", "REQ"}
    grouped = {
        "PEP": with_next(docs.filter(kind=DocumentKind.PEP)),
        "REQ": with_next(docs.filter(kind=DocumentKind.REQ)),
        "OTHER": with_next(docs.exclude(kind__in=main_kinds)),
    }
    return render(request, "docmanagement.html", {
        "active_tab": "docmgmt",
        "project": project,
        "grouped": grouped,
        "kinds": DocumentKind.choices,
        "confidentialities": Confidentiality.choices,
        "is_admin": is_admin,
    })


@login_required
@project_member_required
@require_POST
def doc_transition(request, pk):
    doc = get_object_or_404(ProjectDocument, pk=pk,
                            project=get_active_project(request))
    try:
        lifecycle.transition(doc, request.POST.get("status"), request.user,
                             note=request.POST.get("note", ""))
        messages.success(request, f"„{doc}“: Status {doc.get_status_display()} (Rev. {doc.iteration}).")
    except lifecycle.TransitionError as exc:
        messages.error(request, str(exc))
    return redirect("docmgmt")


@login_required
@project_member_required
@require_POST
def doc_upload(request):
    project = get_active_project(request)
    f = request.FILES.get("file")
    if not f:
        messages.warning(request, "Keine Datei gewählt.")
        return redirect("docmgmt")
    kind = request.POST.get("kind", DocumentKind.OTHER)
    doc = ProjectDocument.objects.create(
        project=project, kind=kind,
        confidentiality=request.POST.get("confidentiality", Confidentiality.INTERNAL),
        safety_relevant=bool(request.POST.get("safety_relevant")),
        revision=request.POST.get("revision", ""),
        title=request.POST.get("title", "") or f.name,
        file=f, original_name=f.name, uploaded_by=request.user,
        is_static=kind in (DocumentKind.PEP, DocumentKind.REQ),
    )
    # Alle Projektdokumente werden vom LLM (RAG) indiziert (CLAUDE.md).
    _index_async(doc.pk)
    messages.success(request, f"„{f.name}“ hochgeladen ({kind}) — wird indiziert …")
    return redirect("docmgmt")


@login_required
@project_member_required
@xframe_options_sameorigin   # erlaubt das Einbetten der inline-PDF im iframe (sonst X-Frame-Options: DENY)
def doc_download(request, pk):
    """Liefert ein Projektdokument aus. `?inline=1` → inline (zum Einbetten /
    Anspringen einer Seite per #page=N im Viewer); sonst Download."""
    doc = get_object_or_404(ProjectDocument, pk=pk,
                            project=get_active_project(request))
    inline = request.GET.get("inline") in ("1", "true", "on")
    name = doc.original_name or doc.file.name.rsplit("/", 1)[-1]
    try:
        return FileResponse(doc.file.open("rb"), as_attachment=not inline,
                            filename=name)
    except FileNotFoundError:
        raise Http404("Datei fehlt")


@login_required
@project_member_required
@require_POST
def doc_delete(request, pk):
    from app.models import ItemStatus
    doc = get_object_or_404(ProjectDocument, pk=pk,
                            project=get_active_project(request))
    # Signiert/eingefroren: nur Admins dürfen es noch anfassen.
    if doc.status == ItemStatus.SIGNED and not request.user.is_staff:
        messages.error(request, "Signiertes (eingefrorenes) Dokument – nur Admins dürfen es löschen.")
        return redirect("docmgmt")
    name = str(doc)
    project_index.remove_document(doc)   # aus dem Projekt-Index entfernen
    doc.file.delete(save=False)
    doc.delete()
    messages.info(request, f"„{name}“ gelöscht (inkl. Index).")
    return redirect("docmgmt")
