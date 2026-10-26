"""
MCP-Server (Streamable HTTP + optional SSE, Bearer-Token-Auth) für ELISA.

Stellt die statischen, kundengelieferten Dokumente je Projekt READ-ONLY bereit
(PEP – Product Engineering Process, REQ – Kundenanforderungen). Verbindet sich
ein MCP-Client (z. B. Claude Desktop), muss er einen gültigen Bearer-Token
mitschicken (Verwaltung im Django-Admin: „MCP tokens").

Transporte (Pfad: /<projekt>/<scope>/…):
    mcp                 Streamable HTTP (aktueller Standard, immer aktiv)
    sse + messages/     SSE (veraltet) – abschaltbar mit MCP_SSE_ENABLED=false

Start:
    python -m mcp_server.server            # lauscht auf 0.0.0.0:8765
Konfig (env):
    MCP_HOST (default 0.0.0.0), MCP_PORT (default 8765), MCP_SSE_ENABLED (true)
"""
import asyncio
import json
import os

# ── Django-Kontext herstellen (ORM-Zugriff auf Projekte/Dokumente/Tokens) ──
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "elisa.settings")
# Tools laufen im async-Kontext (FastMCP); Django-ORM dort erlauben. Der
# MCP-Server ist einplatz-/wenig-last, das kurze Blockieren ist akzeptabel.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")
import django  # noqa: E402
django.setup()

from django.utils import timezone  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from app.models import (  # noqa: E402
    Project, ProjectDocument, DocumentKind, ItemStatus, MCPToken)
from app import project_index, lifecycle  # noqa: E402

# DNS-Rebinding-Schutz der MCP-SDK: prüft den Host-Header und lässt per Default
# nur localhost zu – das bricht Betrieb auf dem LAN-Interface und hinter nginx
# (Host = iec61508.intranet…). Wir sichern jeden Request bereits selbst über
# Bearer-Token + Scope (BearerASGIMiddleware), daher ist der zusätzliche Filter
# redundant. MCP_ALLOWED_HOSTS (kommagetrennt) schaltet ihn bei Bedarf scharf;
# leer => aus.
_allowed_hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=bool(_allowed_hosts),
    allowed_hosts=_allowed_hosts,
    allowed_origins=_allowed_hosts,
)
# Stateless Streamable HTTP: keine serverseitigen Sessions – Clients (Claude Code,
# Worker) überleben einen Neustart/Redeploy des Servers ohne "Session not found".
# Unsere Tools brauchen keine Server→Client-Nachrichten. MCP_STATELESS=false → Sessions.
_stateless = os.getenv("MCP_STATELESS", "true").lower() in ("1", "true", "yes", "on")
mcp = FastMCP("ELISA PEP/REQ", transport_security=_transport_security,
              stateless_http=_stateless)


# ── Tools (read-only) ──────────────────────────────────────────────────────

@mcp.tool()
def list_projects() -> list[dict]:
    """Listet die verfügbaren Projekte (Mandanten) mit Schlüssel und Name."""
    return [{"key": p.key, "name": p.name}
            for p in Project.objects.filter(archived=False)]


def _doc_text(project_key: str, kind: str) -> str:
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return f"(unbekanntes Projekt: {project_key})"
    docs = proj.documents.filter(kind=kind)
    if not docs:
        return f"(kein {kind}-Dokument im Projekt {project_key})"
    from pathlib import Path
    parts = []
    for d in docs:
        for _seite, text in project_index.extract_text(Path(d.file.path)):
            if text.strip():
                parts.append(text)
    return "\n\n".join(parts) or "(kein extrahierbarer Text)"


@mcp.tool()
def get_pep(project_key: str) -> str:
    """Liefert den vollständigen PEP-Text (Product Engineering Process) eines Projekts."""
    return _doc_text(project_key, DocumentKind.PEP)


@mcp.tool()
def get_req(project_key: str) -> str:
    """Liefert die Kundenanforderungen (REQ) eines Projekts als Text."""
    return _doc_text(project_key, DocumentKind.REQ)


@mcp.tool()
def ask_esra(prompt: str, project_key: str = "", role: str = "") -> str:
    """
    Fragt ESRA – die lokale Normenrecherche-Persona (Ollama), RAG-geerdet an
    den Normen und, falls project_key gesetzt, an den Projektdokumenten. Esra
    antwortet ausschließlich aus den vorhandenen Dokumenten (keine Erfindungen).
    Optional `role` (eine der 8 V-Modell-Rollen: REQ/SPEC/ARCH/MOD/MODTEST/
    INTTEST/SYSTEST/ACCTEST) gibt dem Modell seine Rollen- + Projektbeschreibung mit.
    """
    from django.conf import settings
    from app import rag_service, llm_roles

    proj = Project.objects.filter(key=project_key).first() if project_key else None
    ctx = rag_service.format_context(rag_service.retrieve_norm_context(prompt))
    if proj:
        ph = project_index.retrieve_project_context(proj, prompt)
        if ph:
            ctx += "\n\nProjektdokumente:\n" + rag_service.format_context(ph)

    messages = [{"role": "system",
                 "content": "Du bist das lokale Assistenzmodell. Antworte knapp "
                            "und geerdet am Kontext; erfinde nichts."}]
    role_ctx = llm_roles.context_for(project=proj, role=(role or None))
    if role_ctx:
        messages.append({"role": "system", "content": role_ctx})
    if ctx:
        messages.append({"role": "system", "content": f"Kontext:\n{ctx}"})
    messages.append({"role": "user", "content": prompt})

    import ollama
    client = ollama.Client(host=settings.OLLAMA_HOST)
    resp = client.chat(model=settings.OLLAMA_CHAT_MODEL, messages=messages)
    return resp["message"]["content"]


@mcp.tool()
def list_roles() -> list[dict]:
    """
    Listet die 8 V-Modell-Personas mit IEC-61508-Bezug (Klarname). Der SCOPE
    deines Tokens bestimmt, in welcher Rolle du arbeitest (REQ/SPEC/ARCH/MOD bzw.
    die Testrollen) – die ausführliche Persona holst du mit `get_persona`.
    """
    from app.models import LLMRoleDescription, VModelRole
    by_role = {r.role: r for r in LLMRoleDescription.objects.all()}
    out = []
    for code, label in VModelRole.choices:
        rd = by_role.get(code)
        out.append({
            "role": code, "label": label,
            "iec_reference": rd.iec_reference if rd else "",
            "has_description": bool(rd and rd.description),
        })
    return out


@mcp.tool()
def get_persona(project_key: str, role: str) -> dict:
    """
    Liefert die PERSONA eines V-Schritts und das Projekt zum „In-Rolle-gehen":
    die im Admin gepflegte Rollenbeschreibung (mit Abgrenzung nach oben/unten +
    Auftrag, die Dokumentenreihe auf Konsistenz zu prüfen), den IEC-61508-Bezug
    (Klarname) sowie die Projektbeschreibung. Nimm diese Persona ein, BEVOR du im
    Projekt arbeitest. `role` ∈ REQ/SPEC/ARCH/MOD/MODTEST/INTTEST/SYSTEST/ACCTEST
    – das ist der Scope, mit dem dein Token verbunden ist.

    GOVERNANCE (gilt für ALLE Schreib-Tools): Du verfasst NIE verbindlichen Inhalt
    und erfindest nichts. Deine Beiträge sind Vorschläge (DRAFT, generated_by_llm);
    verbindlich wird etwas erst durch menschliche Freigabe (Statusautomat
    DRAFT→PROPOSED→APPROVED, letzter Schritt menschlich). Abgeleitete Items folgen
    der Struktur der Quelle, Lücken werden GEMELDET statt erfunden, Sprache der
    Quelle bleibt erhalten. Korrektheits-Invarianten liegen in der DB, nicht im Prompt.
    """
    from app.models import VModelRole
    from app import llm_roles
    role = (role or "").upper()
    if role not in VModelRole.values:
        return {"ok": False, "error": f"role muss aus {list(VModelRole.values)} sein"}
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {"ok": False, "error": f"unbekanntes Projekt: {project_key}"}
    desc = llm_roles.role_description(role)
    if not desc:
        return {"ok": False, "error": f"keine Rollenbeschreibung für {role} gepflegt"}
    return {
        "ok": True,
        "role": role,
        "label": dict(VModelRole.choices).get(role, role),
        "iec_reference": llm_roles.iec_reference_for(role),
        "project": proj.name,
        "project_description": (proj.description or "").strip(),
        "persona": llm_roles.context_for(project=proj, role=role),
    }


def _doc_dict(d) -> dict:
    return {
        "id": d.pk, "kind": d.kind, "title": str(d),
        "is_norm": d.kind == DocumentKind.NORM,
        "confidentiality": d.confidentiality,
        "safety_relevant": d.safety_relevant,
        "revision": d.revision, "static": d.is_static,
        "indexed_chunks": d.indexed_chunks,
        "status": d.status,                          # DRAFT|PROPOSED|REWORK|APPROVED|OBSOLETE
        "iteration": d.iteration,
        "next_states": lifecycle.next_states(d.status),
        "processed_at": d.processed_at.isoformat() if d.processed_at else None,
    }


@mcp.tool()
def list_project_documents(project_key: str) -> list[dict]:
    """Listet alle Eingangsdokumente eines Projekts mit Klassifizierung & Status."""
    proj = Project.objects.filter(key=project_key).first()
    return [_doc_dict(d) for d in proj.documents.all()] if proj else []


def _next_req_id(proj) -> str:
    from app.models import WorkItem, Phase
    n = WorkItem.objects.filter(project=proj, phase=Phase.REQUIREMENT).count() + 1
    while WorkItem.objects.filter(project=proj, identifier=f"REQ-{n:03d}").exists():
        n += 1
    return f"REQ-{n:03d}"


@mcp.tool()
def list_requirements(project_key: str) -> list[dict]:
    """Listet die Anforderungen (REQ-WorkItems) eines Projekts."""
    from app.models import Phase
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    return [{
        "identifier": w.identifier, "title": w.title, "status": w.status,
        "generated_by_llm": w.generated_by_llm,
    } for w in proj.work_items.filter(phase=Phase.REQUIREMENT)]


@mcp.tool()
def propose_requirement(project_key: str, title: str, body: str,
                        rationale: str = "", identifier: str = "") -> dict:
    """
    Schlägt eine neue Anforderung (REQ) VOR. Governance: wird als DRAFT mit
    generated_by_llm=True angelegt und NIE durch das LLM freigegeben. Ein Mensch
    prüft, überarbeitet und gibt frei (Statusautomat DRAFT→PROPOSED→APPROVED,
    letzter Schritt menschlich). Erfordert ein WRITE-Token.
    """
    from app.models import WorkItem, Phase, ItemStatus
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {"ok": False, "error": f"unbekanntes Projekt: {project_key}"}
    ident = (identifier or "").strip() or _next_req_id(proj)
    if WorkItem.objects.filter(project=proj, identifier=ident).exists():
        return {"ok": False, "error": f"{ident} existiert bereits"}
    w = WorkItem.objects.create(
        project=proj, phase=Phase.REQUIREMENT, identifier=ident,
        title=title, body=body, rationale=rationale,
        status=ItemStatus.DRAFT,
        generated_by_llm=True, llm_model="mcp/claude-desktop",
    )
    from app.models import enqueue_esra, EsraTask
    enqueue_esra(proj, EsraTask.Kind.MATCH_ITEM, work_item=w)  # Generate-Event
    return {"ok": True, "identifier": w.identifier, "status": w.status,
            "hinweis": "Als DRAFT-VORSCHLAG angelegt (generated_by_llm). "
                       "Menschliche Prüfung & Freigabe (PL/FSM) erforderlich."}


@mcp.tool()
def update_requirement(project_key: str, identifier: str, title: str = "",
                       body: str = "", rationale: str = "") -> dict:
    """
    Überarbeitet einen ANFORDERUNGS-ENTWURF (nur Status DRAFT). Bereits in
    Prüfung/freigegebene Items werden nicht angetastet. Erfordert WRITE-Token.
    """
    from app.models import WorkItem, Phase, ItemStatus
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {"ok": False, "error": f"unbekanntes Projekt: {project_key}"}
    w = WorkItem.objects.filter(project=proj, identifier=identifier,
                                phase=Phase.REQUIREMENT).first()
    if not w:
        return {"ok": False, "error": f"{identifier} nicht gefunden"}
    if w.status != ItemStatus.DRAFT:
        return {"ok": False, "error": f"{identifier} ist nicht mehr DRAFT "
                f"(Status {w.status}) – nur ein Mensch darf das ändern."}
    if title:
        w.title = title
    if body:
        w.body = body
    if rationale:
        w.rationale = rationale
    w.generated_by_llm = True
    w.save()
    return {"ok": True, "identifier": w.identifier, "status": w.status}


@mcp.tool()
def next_feedback_request(project_key: str) -> dict:
    """
    Holt die nächste offene Write-time-Feedback-Anfrage eines Projekts (FIFO)
    und markiert sie als in Bearbeitung. Liefert Entwurf, Nachbar-Items UND die
    PERSONA des jeweiligen V-Schritts + Projektbeschreibung – damit das Team
    in der richtigen Rolle antwortet. Danach `submit_feedback` aufrufen.

    Antworte als Lektor: NUR prüfbare Hinweise, schreibe keinen Inhalt.
    Toast-Format: {"type":"notice|radio|checkbox|form","severity":"info|warn|conflict",
    "message":..,"options":[..],"fields":[{"name":..,"label":..}],"action":..}
    """
    from app.models import FeedbackRequest, FeedbackStatus
    from app import llm_roles
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {}
    req = (FeedbackRequest.objects.filter(project=proj,
           status=FeedbackStatus.PENDING).order_by("created_at").first())
    if not req:
        return {}
    req.status = FeedbackStatus.CLAIMED
    req.save(update_fields=["status"])
    phase = getattr(req.item, "phase", None)
    role = llm_roles.PHASE_TO_ROLE.get(phase, phase)
    persona = llm_roles.context_for(project=proj, item=req.item)
    return {
        "request_id": req.id,
        "draft": req.draft,
        "neighbours": req.neighbours,
        "v_step": phase,
        "role": role,                                       # V-Modell-Rolle (Persona)
        "iec_reference": llm_roles.iec_reference_for(phase) if phase else "",
        "persona": persona,            # Rollenbeschreibung + Projektbeschreibung
    }


@mcp.tool()
def submit_feedback(request_id: int, toasts: list) -> dict:
    """
    Liefert die Toasts (Hinweise) zu einer Feedback-Anfrage zurück. NUR Toasts –
    niemals Inhalt. `toasts` ist eine Liste im Toast-Format. WRITE-Token nötig.
    """
    from django.utils import timezone
    from app.models import FeedbackRequest, FeedbackStatus
    req = FeedbackRequest.objects.filter(pk=request_id).first()
    if not req:
        return {"ok": False, "error": "Anfrage nicht gefunden"}
    req.toasts = toasts if isinstance(toasts, list) else []
    req.source = "team"
    req.answered_by = "mcp-team"
    req.status = FeedbackStatus.ANSWERED
    req.answered_at = timezone.now()
    req.save()
    return {"ok": True, "request_id": req.id, "anzahl_toasts": len(req.toasts)}


@mcp.tool()
def list_unprocessed_documents(project_key: str) -> list[dict]:
    """Listet die noch NICHT freigegebenen Dokumente (Status != APPROVED)."""
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    return [_doc_dict(d) for d in proj.documents.exclude(
        status=ItemStatus.APPROVED)]


@mcp.tool()
def set_document_status(doc_id: int, status: str, note: str = "") -> dict:
    """
    Schaltet ein Dokument den iterativen Zyklus WEITER. Erlaubt sind nur die
    nächsten Schritte – es darf NICHTS übersprungen werden:
      DRAFT → PROPOSED → (REWORK ↺ PROPOSED) → APPROVED;
      APPROVED → DRAFT (neue Revision) | OBSOLETE.
    Reine Workflow-Metadatik (kein Inhalt).
    """
    valid = {c[0] for c in ItemStatus.choices}
    if status not in valid:
        return {"ok": False, "error": f"status muss aus {sorted(valid)} sein"}
    d = ProjectDocument.objects.filter(pk=doc_id).first()
    if not d:
        return {"ok": False, "error": "Dokument nicht gefunden"}
    try:
        lifecycle.transition(d, status, user=None, note=note)
    except lifecycle.TransitionError as exc:
        return {"ok": False, "error": str(exc),
                "next_states": lifecycle.next_states(d.status)}
    return {"ok": True, "id": d.pk, "status": d.status, "iteration": d.iteration}


# ── Voll-CRUD für WorkItems ────────────────────────────────────────────────
# PEP/REQ sind Kunden-Ausgangsdokumente und dürfen LLM-verwaltet werden;
# SPEC/ARCH/MOD entstehen nur als DRAFT-Vorschlag (menschliche Freigabe).

def _next_id(proj, phase: str) -> str:
    from app.models import WorkItem
    n = WorkItem.objects.filter(project=proj, phase=phase).count() + 1
    while WorkItem.objects.filter(project=proj, identifier=f"{phase}-{n:03d}").exists():
        n += 1
    return f"{phase}-{n:03d}"


def _wi_dict(w) -> dict:
    return {"identifier": w.identifier, "phase": w.phase, "title": w.title,
            "body": w.body, "rationale": w.rationale, "status": w.status,
            "generated_by_llm": w.generated_by_llm}


@mcp.tool()
def list_workitems(project_key: str, phase: str = "") -> list[dict]:
    """Listet WorkItems eines Projekts (optional gefiltert auf REQ/SPEC/ARCH/MOD)."""
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    qs = proj.work_items.all()
    if phase:
        qs = qs.filter(phase=phase.upper())
    return [_wi_dict(w) for w in qs]


@mcp.tool()
def get_workitem(project_key: str, identifier: str) -> dict:
    """Liefert ein WorkItem (oder {})."""
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    return _wi_dict(w) if w else {}


@mcp.tool()
def create_outline_item(project_key: str, ref_identifier: str, mode: str = "child",
                        title: str = "", body: str = "", rationale: str = "",
                        derived_from: list = None) -> dict:
    """
    GLIEDERUNG anlegen: legt ein Item (DRAFT-Vorschlag, generated_by_llm) an und
    NUMMERIERT AUTOMATISCH relativ zu `ref_identifier`:
      • mode='child'   → Subitem        (S4.1 → S4.1.<n>)
      • mode='sibling' → gleiche Ebene  (S4.1 → S4.<n>)
    Erbt die Traceability (`derived_from`) der Referenz, sofern nicht angegeben.

    Wie create_workitem: NIE verbindlich (Freigabe bleibt menschlich), nichts
    erfinden — nur STRUKTURIEREN. ZUERST get_persona laden und in Rolle gehen.
    REQ NICHT hiermit (nur reimport_requirements). WRITE-Token nötig.
    """
    from app.models import Phase
    from app import outline
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {"ok": False, "error": f"unbekanntes Projekt: {project_key}"}
    phase, derived = outline.resolve_ref(proj, ref_identifier)
    if phase is None:
        return {"ok": False, "error": f"Referenz {ref_identifier} nicht gefunden"}
    if phase == Phase.REQUIREMENT:
        return {"ok": False, "error": "REQ entstehen nur über reimport_requirements"}
    if derived_from:
        derived = list(proj.work_items.filter(identifier__in=derived_from))
        if not derived:
            return {"ok": False, "error": "derived_from nicht auflösbar"}
    new = outline.create_outline_item(
        proj, ref_identifier, mode if mode in ("child", "sibling") else "child", phase,
        title=title, body=body, rationale=rationale,
        generated_by_llm=True, llm_model="mcp", derived=derived)
    return {"ok": True, "identifier": new.identifier, "phase": new.phase}


@mcp.tool()
def create_workitem(project_key: str, phase: str, title: str, body: str = "",
                    rationale: str = "", identifier: str = "",
                    derived_from: list = None) -> dict:
    """
    Legt ein SPEC/ARCH/MOD-WorkItem als DRAFT-Vorschlag an (generated_by_llm;
    Freigabe/APPROVED bleibt menschlich).

    ⚠ ZUERST DIE ROLLE LADEN (Pflicht): Rufe VOR dem ersten Anlegen
    `get_persona(project_key, role)` auf und arbeite STRIKT in dieser Persona –
    deren Abgrenzung nach oben/unten („WAS, nicht WIE"), der Auftrag zur Konsistenz
    der Dokumentenreihe und „Lücken MELDEN statt erfinden" sind bindend. Ohne
    eingenommene Persona legst du KEINE Items an.

    ANFORDERUNGEN (REQ) NICHT hiermit anlegen: REQ entstehen/ändern sich NUR über
    `reimport_requirements`.

    ⛔ KEINE FANTASIE — STRIKTE ABLEITUNG (nicht verhandelbar): Du verfasst KEINEN
    verbindlichen Inhalt (nur DRAFT-Vorschläge, Freigabe ist menschlich) und
    erfindest nichts; du STRUKTURIERST nur vorhandenen. Korrektheits-Invarianten
    (Orphan-/Abdeckungsprüfung, Status) liegen in der DB, nicht im Prompt. Der `body` darf
    AUSSCHLIESSLICH enthalten, was NACHWEISLICH in den `derived_from`-Items steht.
    • ERFINDE NICHTS: keine Akzeptanzkriterien, Schwellen, Reaktionszeiten,
      Mechanismen, Randbedingungen, Annahmen oder „best practice", die nicht in
      der Quelle stehen. Kein Ausschmücken, kein Hinzudichten.
    • GLIEDERUNG FOLGT DER QUELLE: Übernimm Struktur, Reihenfolge und Benennung
      der ÜBERGEORDNETEN Ebene (deiner `derived_from`-Items). Erfinde KEINE eigene
      Gliederung/Nummerierung. Was für DEINEN V-Schritt konkret gilt, liefert die
      Persona (get_persona) – KEINE phasenfremden Beispiele hier.
    • LÜCKEN werden GEMELDET, nicht gefüllt: wo die Quelle schweigt, kurzer
      Vermerk „nicht spezifiziert" — KEINE Prosa, die die Lücke ausgestaltet.
    • SPRACHE der Quelle beibehalten — NICHT übersetzen (eigenes Werkzeug).

    TRACEABILITY: `derived_from` ist PFLICHT — Liste der Identifier der über-
    geordneten Items, aus denen dieses Item abgeleitet ist (z. B. ["R3.1"]). Ohne
    auflösbare Referenz wird NICHTS angelegt (verhindert Orphans/erfundene Items).

    `title` = Kurzlabel; `body` darf **Markdown**. Normen via list_norms/
    search_norms/fulltext_search_norms. WRITE-Token nötig.
    """
    from app.models import WorkItem, Phase, ItemStatus
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {"ok": False, "error": f"unbekanntes Projekt: {project_key}"}
    phase = (phase or "").upper()
    if phase not in Phase.values:
        return {"ok": False, "error": f"phase muss aus {list(Phase.values)} sein"}
    if phase == Phase.REQUIREMENT:
        return {"ok": False, "error": "Anforderungen (REQ) werden NUR über "
                "reimport_requirements verwaltet (Quelldokument-Reimport)."}
    # PFLICHT-Traceability: SPEC/ARCH/MOD MÜSSEN aus mind. einem vorhandenen Item
    # abgeleitet sein. Wir lösen die Eltern VOR dem Anlegen auf – existiert keine
    # Referenz, wird NICHTS angelegt (kein Orphan, keine freischwebende Fantasie).
    refs = [(r or "").strip() for r in (derived_from or []) if (r or "").strip()]
    if not refs:
        return {"ok": False, "error": "derived_from ist PFLICHT: ein SPEC/ARCH/MOD "
                "muss nachweisbar aus REQ/höheren Items abgeleitet sein – sonst "
                "Orphan/erfundener Inhalt."}
    parents, missing = [], []
    for r in refs:
        p = WorkItem.objects.filter(project=proj, identifier=r).first()
        (parents.append(p) if p else missing.append(r))
    if not parents:
        return {"ok": False, "error": f"keine der derived_from-Referenzen existiert "
                f"({missing}); Item NICHT angelegt."}
    ident = (identifier or "").strip() or _next_id(proj, phase)
    if WorkItem.objects.filter(project=proj, identifier=ident).exists():
        return {"ok": False, "error": f"{ident} existiert bereits"}
    w = WorkItem.objects.create(
        project=proj, phase=phase, identifier=ident, title=(title or "")[:160],
        body=body, rationale=rationale, status=ItemStatus.DRAFT,
        generated_by_llm=True, llm_model="mcp")
    linked = []
    for p in parents:
        if p.pk != w.pk:
            w.derived_from.add(p)
            linked.append(p.identifier)
    from app.models import enqueue_esra, EsraTask
    enqueue_esra(proj, EsraTask.Kind.MATCH_ITEM, work_item=w)  # Generate-Event
    return {"ok": True, "identifier": w.identifier, "phase": w.phase,
            "status": w.status, "derived_from": linked,
            "derived_from_missing": missing}


@mcp.tool()
def update_workitem(project_key: str, identifier: str, title: str = "",
                    body: str = "", rationale: str = "") -> dict:
    """Ändert ein SPEC/ARCH/MOD-WorkItem (nur solange DRAFT; sonst nur ein
    Mensch). ANFORDERUNGEN (REQ) werden NICHT hiermit geändert — sie ändern sich
    AUSSCHLIESSLICH über `reimport_requirements`.

    Es gelten dieselben Regeln wie bei create_workitem: ZUERST
    `get_persona(project_key, role)` laden und ihr folgen; KEINE FANTASIE — der
    `body` darf nur enthalten, was nachweislich aus den übergeordneten
    (derived_from-)Items folgt; Gliederung der Quelle folgen; Lücken MELDEN statt
    füllen; Sprache der Quelle beibehalten (nicht übersetzen). Du verfasst keinen
    verbindlichen Inhalt — DRAFT-Vorschlag, Freigabe bleibt menschlich.
    WRITE-Token nötig."""
    from app.models import Phase, ItemStatus
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return {"ok": False, "error": f"{identifier} nicht gefunden"}
    if w.phase == Phase.REQUIREMENT:
        return {"ok": False, "error": "Anforderungen (REQ) ändern sich NUR über "
                "reimport_requirements (Quelldokument-Reimport), nicht einzeln."}
    if w.status != ItemStatus.DRAFT:
        return {"ok": False, "error": f"{identifier} ist nicht DRAFT (Status {w.status}) "
                "– nur ein Mensch darf das ändern."}
    if title:
        w.title = title[:160]
    if body:
        w.body = body
    if rationale:
        w.rationale = rationale
    w.generated_by_llm = True
    w.save()
    return {"ok": True, "identifier": w.identifier, "status": w.status}


@mcp.tool()
def delete_workitem(project_key: str, identifier: str) -> dict:
    """Löscht ein SPEC/ARCH/MOD-WorkItem (nur solange DRAFT). ANFORDERUNGEN (REQ)
    werden NICHT einzeln gelöscht — sie werden ausschließlich über
    `reimport_requirements` neu importiert. WRITE-Token nötig."""
    from app.models import Phase, ItemStatus
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return {"ok": False, "error": f"{identifier} nicht gefunden"}
    if w.phase == Phase.REQUIREMENT:
        return {"ok": False, "error": "Anforderungen (REQ) werden nur über "
                "reimport_requirements verwaltet, nicht einzeln gelöscht."}
    if w.status != ItemStatus.DRAFT:
        return {"ok": False, "error": f"{identifier} ist nicht DRAFT – Löschen nur durch Mensch."}
    ident = w.identifier
    w.delete()
    return {"ok": True, "deleted": ident}


def _file_req_source(proj, source_path: str) -> dict:
    """Legt das gelesene Quelldokument als REQ-ProjectDocument im Projekt ab
    (Festplatten-Import). `source_path` = Dateiname im incoming-Share (nur
    Basename, kein Traversal). Idempotent: existiert es schon, passiert nichts.
    Wird beim Reimport aufgerufen, damit die gelesene Spec zugleich im Projekt
    abgelegt (und RAG-indiziert) ist."""
    import threading
    from pathlib import Path
    from django.conf import settings as dj
    from django.core.files import File
    from app.models import ProjectDocument, DocumentKind
    name = Path(source_path or "").name
    if not name:
        return {"status": "kein source_path"}
    existing = ProjectDocument.objects.filter(project=proj, original_name=name).first()
    if existing:
        return {"status": "bereits vorhanden", "id": existing.pk}
    src = Path(dj.INCOMING_DIR) / name
    if not src.is_file():
        return {"status": "nicht im Festplatten-Share gefunden", "pfad": str(src)}
    doc = ProjectDocument(project=proj, kind=DocumentKind.REQ, title=name,
                          original_name=name, is_static=True, safety_relevant=True)
    with open(src, "rb") as fh:
        doc.file.save(name, File(fh), save=True)

    def _idx(pk):
        try:
            d = ProjectDocument.objects.get(pk=pk)
            ProjectDocument.objects.filter(pk=pk).update(
                indexed_chunks=project_index.index_document(d))
        except Exception:
            pass
    threading.Thread(target=_idx, args=(doc.pk,), daemon=True).start()
    return {"status": "angelegt", "id": doc.pk, "kind": "REQ", "name": name}


@mcp.tool()
def reimport_requirements(project_key: str, source: str, requirements: list,
                          source_path: str = "") -> dict:
    """
    RE-IMPORT der Anforderungen (REQ) aus dem Kunden-Quelldokument. Dies ist der
    EINZIGE Weg, REQ anzulegen oder zu ändern – create/update/delete_workitem
    sind für REQ gesperrt. Je `identifier` wird das REQ-Item angelegt oder
    aktualisiert (mit lückenloser Historie). Erneuter Aufruf = erneuter Reimport.

    `requirements`: Liste von Objekten
      {"identifier": "R4.1", "title": "Kurzlabel",
       "body": "<VOLLSTÄNDIGER, WORTGETREUER Originaltext der Anforderung>",
       "rationale": "Quelle/Abschnitt (optional)"}

    ZWINGEND:
    • `body` = der VOLLSTÄNDIGE, WORTGETREUE Text aus dem Quelldokument (inkl.
      zugehöriger Anmerkungen). KEINE Zusammenfassungen, KEINE Paraphrasen,
      kein Kürzen.
    • ORIGINALSPRACHE beibehalten — NICHT übersetzen (Übersetzung ist ein
      separates Werkzeug).

    WERKZEUGE:
    • `body` darf **Markdown** enthalten (wird im UI gerendert) – nutze das für
      Struktur (Überschriften, Listen, Tabellen, Hervorhebungen). Das ändert den
      Wortlaut nicht, macht ihn nur lesbar.
    • Zitierte Normen werden im UI automatisch erkannt und – falls vorhanden –
      direkt verlinkt. Prüfe/finde vorhandene Normen vorab mit `list_norms`,
      `search_norms` (RAG-Index) und `fulltext_search_norms` (Volltext).

    PROVENIENZ (zwingend): `source` UND die `rationale` jeder Anforderung MÜSSEN den
    VOLLSTÄNDIGEN Dokumentennamen (kein Kürzel) enthalten — und, falls im Dokument
    vorhanden, zusätzlich AUTOR und VERSION/REVISION (samt Datum). So bleibt jede
    Anforderung eindeutig auf die signierte Quelle rückführbar.

    QUELLDOKUMENT ABLEGEN (Festplatten-Import): Gib `source_path` = Dateiname der
    Spec im incoming-Share an. Die gelesene Spec wird dann ZUGLEICH als REQ-
    ProjectDocument im Projekt abgelegt und RAG-indiziert (idempotent — existiert
    sie schon, passiert nichts). Ohne `source_path` werden nur die Anforderungen
    importiert.

    `title` ist nur ein Kurzlabel; der prüfbare Inhalt steht vollständig und
    unverändert im `body`. WRITE-Token nötig.
    """
    from app.models import WorkItem, Phase, ItemStatus
    from app import history as hist_mod
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {"ok": False, "error": f"unbekanntes Projekt: {project_key}"}
    if not isinstance(requirements, list) or not requirements:
        return {"ok": False, "error": "requirements muss eine nicht-leere Liste sein"}
    created, updated, errors, seen = [], [], [], set()
    note = f"Reimport: {source}" if source else "Reimport"
    for r in requirements:
        if not isinstance(r, dict):
            errors.append("Eintrag ist kein Objekt"); continue
        ident = (r.get("identifier") or "").strip()
        body = r.get("body") or ""
        if not ident or not body.strip():
            errors.append(f"identifier/body fehlt bei {r.get('identifier')!r}"); continue
        seen.add(ident)
        title = (r.get("title") or ident)[:160]
        rationale = r.get("rationale") or ""
        w = WorkItem.objects.filter(project=proj, identifier=ident).first()
        if w and w.phase != Phase.REQUIREMENT:
            errors.append(f"{ident} ist keine Anforderung (phase {w.phase})"); continue
        if w:
            before = hist_mod.snapshot(w)
            w.title, w.body, w.rationale = title, body, rationale
            # REQ spiegeln das signierte Kundendokument → per Default APPROVED.
            w.status = ItemStatus.APPROVED
            w.generated_by_llm, w.llm_model = True, "mcp"
            w.save()
            hist_mod.record_changes(w, before, by=None, note=note)
            updated.append(ident)
        else:
            w = WorkItem.objects.create(
                project=proj, phase=Phase.REQUIREMENT, identifier=ident,
                title=title, body=body, rationale=rationale,
                status=ItemStatus.APPROVED, generated_by_llm=True, llm_model="mcp")
            hist_mod.record_created(w, by=None, note=note)
            created.append(ident)
    orphaned = list(WorkItem.objects.filter(project=proj, phase=Phase.REQUIREMENT)
                    .exclude(identifier__in=seen).values_list("identifier", flat=True))
    filed = _file_req_source(proj, source_path) if source_path else None
    return {"ok": True, "source": source, "angelegt": created, "aktualisiert": updated,
            "nicht_im_reimport": orphaned, "errors": errors, "quelldokument": filed}


# ── Dokumente lesen + Schlagwortkatalog ────────────────────────────────────

def _kw_slug(s: str) -> str:
    from django.utils.text import slugify
    return slugify(s or "", allow_unicode=False)[:80]


@mcp.tool()
def get_document(project_key: str, doc_id: int) -> dict:
    """Liefert den indexierten Volltext eines Projektdokuments (für die
    Schlagwort-Ableitung). `doc_id` aus list_project_documents. Text aus dem
    RAG-Index zusammengesetzt (kein Datei-Zugriff)."""
    from app.models import Project, ProjectDocument, EmbeddingChunk
    from app import project_index
    proj = Project.objects.filter(key=project_key).first()
    d = ProjectDocument.objects.filter(pk=doc_id, project=proj).first() if proj else None
    if not d:
        return {"ok": False, "error": "Dokument nicht gefunden"}
    src = d.original_name or (d.file.name.rsplit("/", 1)[-1] if d.file else "")
    rows = list(EmbeddingChunk.objects.filter(
        collection=project_index.collection_name(proj), source=src)
        .order_by("page", "uid").values_list("text", flat=True))
    return {"ok": True, "id": d.pk, "name": src, "kind": d.kind,
            "chunks": len(rows), "text": ("\n".join(rows))[:20000]}


@mcp.tool()
def tag_document(project_key: str, doc_id: int, keywords: list) -> dict:
    """Schlägt Schlagworte für ein Dokument vor (Schlagwortkatalog). Legt fehlende
    Keywords an und verknüpft sie als VORSCHLAG (confirmed=False, generated_by_llm);
    erst ein menschlicher Klick bestätigt sie — bis dahin nicht verbindlich.
    `keywords` = Liste. WRITE-Token nötig."""
    from app.models import Project, ProjectDocument, Keyword, KeywordLink
    proj = Project.objects.filter(key=project_key).first()
    d = ProjectDocument.objects.filter(pk=doc_id, project=proj).first() if proj else None
    if not d:
        return {"ok": False, "error": "Dokument nicht gefunden"}
    added = []
    for kw in (keywords or []):
        slug = _kw_slug(kw)
        if not slug:
            continue
        k, _ = Keyword.objects.get_or_create(text=slug, defaults={"label": (kw or "").strip()[:120]})
        KeywordLink.objects.get_or_create(
            keyword=k, document=d,
            defaults={"generated_by_llm": True, "llm_model": "mcp", "confirmed": False})
        added.append(slug)
    return {"ok": True, "document": d.original_name or d.pk, "keywords": added}


@mcp.tool()
def tag_workitem(project_key: str, identifier: str, keywords: list) -> dict:
    """Wie tag_document, aber für ein WorkItem (Schlagworte als Vorschlag).
    WRITE-Token nötig."""
    from app.models import Project, Keyword, KeywordLink
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return {"ok": False, "error": f"{identifier} nicht gefunden"}
    added = []
    for kw in (keywords or []):
        slug = _kw_slug(kw)
        if not slug:
            continue
        k, _ = Keyword.objects.get_or_create(text=slug, defaults={"label": (kw or "").strip()[:120]})
        KeywordLink.objects.get_or_create(
            keyword=k, work_item=w,
            defaults={"generated_by_llm": True, "llm_model": "mcp", "confirmed": False})
        added.append(slug)
    return {"ok": True, "identifier": w.identifier, "keywords": added}


@mcp.tool()
def tag_chunk(project_key: str, chunk_uid: str, keywords: list) -> dict:
    """Schlagworte für EINEN RAG-Chunk vorschlagen (feinkörniger Schlagwortkatalog
    — JEDER Chunk braucht MEHRERE Schlagworte; der Katalog soll auf hunderte
    Einträge wachsen). Keywords werden angelegt (Keyword.text ist UNIQUE) und als
    Vorschlag mit dem Chunk verknüpft (confirmed=False, generated_by_llm). Hol dir
    die Chunks mit list_document_chunks bzw. fulltext_search_norms (uid). WRITE."""
    from app.models import EmbeddingChunk, Keyword, KeywordLink
    ch = EmbeddingChunk.objects.filter(uid=chunk_uid).first()
    if not ch:
        return {"ok": False, "error": "Chunk (uid) nicht gefunden"}
    added = []
    for kw in (keywords or []):
        slug = _kw_slug(kw)
        if not slug:
            continue
        k, _ = Keyword.objects.get_or_create(text=slug, defaults={"label": (kw or "").strip()[:120]})
        KeywordLink.objects.get_or_create(
            keyword=k, chunk=ch,
            defaults={"generated_by_llm": True, "llm_model": "mcp", "confirmed": False})
        added.append(slug)
    return {"ok": True, "chunk_uid": chunk_uid, "keywords": added}


@mcp.tool()
def list_document_chunks(project_key: str, doc_id: int, limit: int = 300) -> list:
    """Listet die RAG-Chunks eines Projektdokuments (uid, Seite, Textauszug, bereits
    vergebene Schlagworte) — damit Esra JEDEN Chunk einzeln per tag_chunk
    verschlagwortet."""
    from app.models import Project, ProjectDocument, EmbeddingChunk
    from app import project_index
    proj = Project.objects.filter(key=project_key).first()
    d = ProjectDocument.objects.filter(pk=doc_id, project=proj).first() if proj else None
    if not d:
        return []
    src = d.original_name or (d.file.name.rsplit("/", 1)[-1] if d.file else "")
    rows = (EmbeddingChunk.objects.filter(
                collection=project_index.collection_name(proj), source=src)
            .order_by("page", "uid")[:limit])
    return [{"uid": c.uid, "page": c.page, "text": (c.text or "")[:300],
             "keywords": list(c.keyword_links.values_list("keyword__text", flat=True))}
            for c in rows]


@mcp.tool()
def audit_downgrade(project_key: str, identifier: str, finding: str) -> dict:
    """AUDIT-RÜCKSTUFUNG (externer Auditor: TÜV/Kunde/Sub): stuft ein Item um GENAU
    EINE Stufe ZURÜCK (Rückweisung, NIE hinauf) und postet das Finding/den Befund
    in den Item-Chat. Die Freigabe nach oben bleibt rein menschlich (3-Personen-
    Regel, IEC 61508). Nutze dies, wenn ein Audit-Dokument eine Abweichung an
    einem Item belegt. WRITE-Token nötig."""
    from app.models import Project, ChatMessage, ChatRole
    from app import lifecycle
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return {"ok": False, "error": "Item nicht gefunden"}
    try:
        ev = lifecycle.audit_downgrade(w, None, note=(finding or "")[:240])
    except lifecycle.TransitionError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        ChatMessage.objects.create(
            session=_owner_less_item_chat(w), role=ChatRole.ASSISTANT,
            content=f"🔎 Audit-Finding: {finding}\n→ zurückgestuft auf {ev.to_state}.",
            author_label="@nathan", generated_by_llm=True, llm_model="mcp/nathan")
    except Exception:
        pass
    return {"ok": True, "identifier": identifier, "new_status": ev.to_state}


@mcp.tool()
def next_translation_task(project_key: str) -> dict:
    """Holt die nächste OFFENE Übersetzungs-Aufgabe (vom „Übersetzen"-Button erzeugt)
    und markiert sie laufend. Liefert identifier, lang, lang_name, title, body. Für
    den Tertius-Übersetzer-Worker: danach das LLM fragen und complete_translation
    mit dem Ergebnis aufrufen."""
    from app.models import Project, ItemTranslation
    from app import languages as _L
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {}
    t = (ItemTranslation.objects.filter(work_item__project=proj,
                                        status=ItemTranslation.Status.PENDING)
         .select_related("work_item").order_by("updated_at").first())
    if not t:
        return {}
    t.status = ItemTranslation.Status.RUNNING
    t.save(update_fields=["status"])
    return {"identifier": t.work_item.identifier, "lang": t.lang,
            "lang_name": _L.name(t.lang), "title": t.work_item.title or "",
            "body": t.work_item.body or ""}


@mcp.tool()
def complete_translation(project_key: str, identifier: str, lang: str,
                         text: str, ok: bool = True) -> dict:
    """Schreibt das Übersetzungs-Ergebnis zurück (DONE/ERROR). Vom Tertius-Worker
    nach der LLM-Übersetzung aufgerufen; die UI pollt es dann."""
    from app.models import Project, ItemTranslation
    proj = Project.objects.filter(key=project_key).first()
    t = (ItemTranslation.objects.filter(
            work_item__project=proj, work_item__identifier=identifier,
            lang=lang).first() if proj else None)
    if not t:
        return {"ok": False, "error": "Aufgabe nicht gefunden"}
    t.status = ItemTranslation.Status.DONE if ok else ItemTranslation.Status.ERROR
    t.text = text or ""
    t.save(update_fields=["status", "text", "updated_at"])
    return {"ok": True, "identifier": identifier, "status": t.status}


@mcp.tool()
def next_esra_task(project_key: str) -> dict:
    """Holt die nächste OFFENE Esra-Aufgabe (event-getrieben bei Upload/Generate
    erzeugt) und markiert sie als laufend. Liefert kind (TAG_DOC|TAG_NORM|MATCH_ITEM)
    + Ziel (doc_id/identifier/ref). Leeres Objekt = nichts zu tun. Nach Erledigung
    complete_esra_task aufrufen."""
    from app.models import Project, EsraTask
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return {}
    t = (EsraTask.objects.filter(project=proj, status=EsraTask.Status.PENDING)
         .order_by("created_at").first())
    if not t:
        return {}
    t.status = EsraTask.Status.RUNNING
    t.save(update_fields=["status"])
    return {"task_id": t.id, "kind": t.kind, "doc_id": t.document_id,
            "identifier": t.work_item.identifier if t.work_item_id else "",
            "ref": t.ref}


@mcp.tool()
def complete_esra_task(task_id: int, ok: bool = True, note: str = "") -> dict:
    """Schließt eine Esra-Aufgabe ab (DONE/ERROR) mit kurzer Notiz."""
    from django.utils import timezone
    from app.models import EsraTask
    t = EsraTask.objects.filter(pk=task_id).first()
    if not t:
        return {"ok": False, "error": "Task nicht gefunden"}
    t.status = EsraTask.Status.DONE if ok else EsraTask.Status.ERROR
    t.note = (note or "")[:2000]
    t.processed_at = timezone.now()
    t.save(update_fields=["status", "note", "processed_at"])
    return {"ok": True, "task_id": task_id, "status": t.status}


@mcp.tool()
def list_keywords(project_key: str) -> list:
    """Schlagwortkatalog des Projekts: je Dokument/Item die Schlagworte (Vorschlag
    + bestätigt). Kompakter Index – damit das lokale Modell (Ollama) Kontext-Breite
    spart (Schlagworte statt Volltext)."""
    from app.models import Project, KeywordLink
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    by = {}
    for l in (KeywordLink.objects.select_related("keyword", "document", "work_item", "chunk")):
        if l.document_id and l.document and l.document.project_id == proj.id:
            key = ("doc", l.document.original_name or f"Doc#{l.document_id}")
        elif l.work_item_id and l.work_item and l.work_item.project_id == proj.id:
            key = ("item", l.work_item.identifier)
        elif l.chunk_id and l.chunk and l.chunk.project_id == proj.id:
            key = ("chunk", l.chunk.source)        # feinkörnig je Projekt-Dokument
        else:
            continue
        by.setdefault(key, {"confirmed": [], "proposed": []})
        (by[key]["confirmed"] if l.confirmed else by[key]["proposed"]).append(l.keyword.text)
    return [{"kind": k[0], "target": k[1],
             "keywords_confirmed": sorted(set(v["confirmed"])),
             "keywords_proposed": sorted(set(v["proposed"]))}
            for k, v in sorted(by.items())]


# ── Norm-Suche (Normen & Regelwerke im RAG-Index) ──────────────────────────

@mcp.tool()
def list_norms() -> list:
    """Listet die im System vorhandenen Normen/Regelwerke (Quellen im Norm-RAG-
    Index) mit Chunk-Anzahl. Nutze dies, um zu prüfen, welche zitierte Norm
    überhaupt vorhanden (und damit verlinkbar/durchsuchbar) ist."""
    from app import rag_service
    counts = rag_service.chunk_counts_by_source()
    return [{"name": n, "chunks": counts.get(n, 0)} for n in rag_service.available_norms()]


@mcp.tool()
def list_norm_chunks(source: str, limit: int = 200, offset: int = 0) -> list:
    """Listet RAG-Chunks EINER Norm (uid, Seite, Auszug, bereits vergebene
    Schlagworte), PAGINIERT (limit/offset) — damit Esra JEDEN Norm-Chunk per
    tag_chunk verschlagwortet und so den Normen-Schlagwortkatalog (hunderte/
    tausende, Keywords UNIQUE) aufbaut. `source` = Dateiname aus list_norms."""
    from app.models import EmbeddingChunk
    lim = max(1, min(int(limit), 500))
    off = max(0, int(offset))
    rows = (EmbeddingChunk.objects.filter(collection="normen", source=source)
            .order_by("page", "uid")[off:off + lim])
    return [{"uid": c.uid, "page": c.page, "text": (c.text or "")[:300],
             "keywords": list(c.keyword_links.values_list("keyword__text", flat=True))}
            for c in rows]


@mcp.tool()
def list_norm_keywords(source: str = "") -> list:
    """Normen-Schlagwortkatalog: je Norm-Quelle die auf ihren Chunks vergebenen
    Schlagworte (aggregiert, mit Anzahl). Optional auf EINE `source` eingrenzen."""
    from app.models import KeywordLink
    by = {}
    qs = (KeywordLink.objects.select_related("keyword", "chunk")
          .filter(chunk__collection="normen"))
    if source:
        qs = qs.filter(chunk__source=source)
    for l in qs:
        if l.chunk_id and l.chunk:
            by.setdefault(l.chunk.source, set()).add(l.keyword.text)
    return [{"source": s, "keywords": sorted(kw), "count": len(kw)}
            for s, kw in sorted(by.items())]


@mcp.tool()
def search_norms(query: str, n: int = 5) -> list:
    """Semantische Suche (RAG-Index) in den vorhandenen Normen. Liefert die
    ähnlichsten Stellen mit Quelle, Seite und Textauszug – z. B. um zu einer
    Anforderung die passende Norm/Klausel zu finden."""
    from app import rag_service
    hits = rag_service.retrieve_norm_context(query, n)
    return [{"source": meta.get("quelle"), "page": meta.get("seite"),
             "text": (doc or "")[:600]} for doc, meta in hits]


@mcp.tool()
def fulltext_search_norms(query: str, n: int = 10) -> list:
    """Volltext-/Substring-Suche (exakte Begriffe) in den vorhandenen Normen.
    Liefert Treffer mit Quelle, Seite und Auszug. Für genaue Klausel-/Begriffs-
    treffer, wenn die semantische Suche zu unscharf ist."""
    from app.models import EmbeddingChunk
    from app import rag_service
    qs = (EmbeddingChunk.objects.filter(collection=rag_service.COLLECTION,
                                        text__icontains=query)
          .order_by("source", "page")[:max(1, min(n, 50))])
    return [{"source": c.source, "page": c.page, "text": (c.text or "")[:600]} for c in qs]


# ── Item-Chat (mit Menschen chatten) + Routing ─────────────────────────────

def _owner_less_item_chat(item):
    from app.models import ChatSession
    s = ChatSession.objects.filter(related_item=item, owner__isnull=True).first()
    if not s:
        s = ChatSession.objects.create(related_item=item, owner=None,
                                       project=item.project,
                                       title=f"Item-Chat {item.identifier}")
    return s


@mcp.tool()
def list_my_mentions(project_key: str, handle: str) -> list:
    """
    ROUTING – so chattest du mit den Menschen: Nutzer sprechen dich im Item-Chat
    per @<handle> an (z. B. @claude). Dieses Tool findet die Item-Chats, in denen
    du erwähnt wurdest und die ZULETZT von einem Menschen geschrieben wurden (also
    auf deine Antwort warten). Liefert [{identifier, last_message}]. Danach:
    get_item_chat lesen → post_item_chat antworten.

    ECHTZEIT (bevorzugt): Sobald du angesprochen wurdest, LAUSCHE auf dem SSE-Kanal
    `…/events` – neue @-Erwähnungen kommen dort live als `event: chat_mention`
    ({identifier, from, message}). Dann musst du nicht pollen; dieses Tool ist der
    Fallback bzw. holt den Rückstand (Backlog vor Verbindungsaufbau).
    """
    from app.models import ChatSession, ChatRole
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    token = "@" + handle.lstrip("@").lower()
    out = []
    for s in (ChatSession.objects.filter(project=proj, owner__isnull=True,
                                         related_item__isnull=False)
              .select_related("related_item")):
        msgs = list(s.messages.all())
        if not msgs or msgs[-1].role != ChatRole.USER:
            continue
        if any(token in (m.content or "").lower() for m in msgs) or \
                "@all" in (msgs[-1].content or "").lower():
            out.append({"identifier": s.related_item.identifier,
                        "last_message": (msgs[-1].content or "")[:300],
                        "last_sender": _sender_handle(msgs[-1]),
                        "last_sender_name": msgs[-1].sender_label()})
    return out


@mcp.tool()
def delete_revision(project_key: str, identifier: str) -> dict:
    """Löscht die AKTUELLE (jüngste) Inhalts-Revision eines WorkItems → Rollback auf
    den vorigen Stand (das jüngste Edit-Batch wird entfernt; Statusübergänge bleiben).
    Privilegiert – nur bewusst einsetzen. WRITE-Token nötig."""
    from app.models import Project
    from app import history as hist_mod
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return {"ok": False, "error": f"{identifier} nicht gefunden"}
    ok = hist_mod.delete_current_revision(w, by=None)
    return {"ok": ok, "identifier": identifier,
            "note": "auf vorigen Stand zurückgerollt" if ok
                    else "keine löschbare Inhalts-Revision"}


@mcp.tool()
def list_personas(project_key: str = "") -> list[dict]:
    """Verbundene LLM-Personas mit LOKALITÄT (local/external) + @handle. Zweck: eine
    LOKALE Persona kann eine EXTERNE per @handle um eine externe Verifikation/
    Zweitmeinung bitten (und umgekehrt) – sie unterscheidet lokal vs. extern."""
    from app.models import WorkerBackend
    from app.participants import locality_of
    out, seen = [], set()
    for b in WorkerBackend.objects.filter(active=True).select_related("token"):
        h = b.effective_handle
        if not h or h in seen:
            continue
        seen.add(h)
        out.append({"handle": h, "name": b.name,
                    "provider": (b.provider or "").upper(),
                    "locality": locality_of(b.provider, b.effective_base_url)})
    return out


# `llm_model`-Sentinel der Auto-Begrüßung (Wendelin stellt die Personas vor). Diese
# Nachricht listet alle @-Handles, soll aber KEINE Persona-Antwort auslösen.
INTRO_MARKER = "rag/welcome"


def _sender_handle(m) -> str:
    """Adressierbarer @-Handle des Absenders (statt Klarname) – damit eine Persona
    die richtige Person zurück-adressieren kann statt generisch „@Mensch". Mensch →
    @<vorname>; LLM/Persona → ihr author_label (bereits ein @-Handle)."""
    from app.participants import slug_handle
    if getattr(m, "author_id", None):
        h = slug_handle(m.author.first_name) or slug_handle(m.author.get_username())
        return ("@" + h) if h else ""
    return (m.author_label or "")


@mcp.tool()
def list_my_chat_mentions(project_key: str, handle: str) -> list:
    """Wie list_my_mentions, aber für die CHAT-SESSIONS (Projekt-Chat UND RAG-Chats,
    auch nutzereigene): findet Sessions, in deren LETZTER Nachricht du per @<handle>
    (regex, wortgenau) erwähnt wurdest und die NICHT von dir stammt. `@all` in einer
    Nachricht eines MENSCHEN richtet sich an ALLE Teilnehmer, also auch an dich. Erlaubt auch
    Inter-Persona-Dialoge (eine andere Persona darf dich ansprechen) – begrenzt
    gegen Endlosschleifen (nach mehreren Nicht-Mensch-Nachrichten in Folge wird
    pausiert, bis wieder ein Mensch schreibt). Liefert [{session_id, title,
    last_message}]. Danach: get_chat lesen → post_chat antworten."""
    import re as _re
    from app.models import ChatSession, ChatRole
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    h = handle.lstrip("@").lower()
    rx = _re.compile(r"@([\w\-äöüÄÖÜß]+)")
    out, CAP = [], 6
    for s in ChatSession.objects.filter(project=proj).prefetch_related("messages"):
        msgs = list(s.messages.all())
        if not msgs:
            continue
        last = msgs[-1]
        if (last.llm_model or "") == INTRO_MARKER:
            continue                                   # Auto-Begrüßung (listet alle @-Handles
                                                       # nur informativ) → NICHT als Ansprache
                                                       # werten. Persona↔Persona bleibt möglich.
        if (last.author_label or "").lstrip("@").lower() == h:
            continue                                   # nicht auf mich selbst antworten
        tagged = {m.lower() for m in rx.findall(last.content or "")}
        # @all richtet sich an alle – aber nur, wenn ein MENSCH schreibt (sonst würden
        # sich Personas gegenseitig endlos anstoßen).
        if h not in tagged and not ("all" in tagged and last.role == ChatRole.USER):
            continue                                   # weder @handle noch @all in der LETZTEN Nachricht
        trailing = 0                                   # Loop-Schranke
        for m in reversed(msgs):
            if m.role == ChatRole.USER:
                break
            trailing += 1
        if trailing >= CAP:
            continue
        out.append({"session_id": s.id, "title": s.title or "",
                    "last_message": (last.content or "")[:300],
                    "last_sender": _sender_handle(last),
                    "last_sender_name": last.sender_label()})
    return out


@mcp.tool()
def list_chats(project_key: str, include_personal: bool = False, limit: int = 30) -> list:
    """MITLESEN: listet die Chats eines Projekts (neueste zuerst) mit Session-ID,
    Titel, letzter Nachricht und Zeit – dann mit get_chat(session_id, after_id)
    lesen. Standard: nur die GETEILTEN Projekt-Chats. `include_personal=true` nimmt
    auch die persönlichen RAG-Chats der Mitglieder hinzu (datenschutzrelevant:
    nur mit Grund und Berechtigung verwenden). Nur lesend."""
    from app.models import ChatSession
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    qs = ChatSession.objects.filter(project=proj, related_item__isnull=True)
    if not include_personal:
        qs = qs.filter(shared=True)
    out = []
    for s in qs.select_related("owner").prefetch_related("messages").order_by("-updated_at")[:max(1, min(limit, 200))]:
        msgs = list(s.messages.all())
        last = msgs[-1] if msgs else None
        out.append({"session_id": s.id, "title": s.title or "", "shared": s.shared,
                    "owner": (s.owner.get_username() if s.owner_id else ""),
                    "messages": len(msgs),
                    "last_id": last.id if last else 0,
                    "last_sender": _sender_handle(last) if last else "",
                    "last_message": (last.content or "")[:300] if last else "",
                    "updated_at": s.updated_at.isoformat()})
    return out


@mcp.tool()
def get_chat(session_id: int, after_id: int = 0) -> list:
    """Liest eine Chat-Session (Projekt-/RAG-Chat) – Verlauf zum Antworten oder
    Mitlesen. `after_id` = nur Nachrichten NACH dieser ID (für fortlaufendes
    Mitlesen: zuletzt gesehene ID merken). Nutze dies, nachdem
    list_my_chat_mentions oder list_chats dich zu einer Session geführt hat."""
    from app.models import ChatSession
    s = ChatSession.objects.filter(id=session_id).first()
    if not s:
        return []
    return [{"id": m.id, "role": m.role, "sender": m.sender_label(),
             "sender_handle": _sender_handle(m), "content": m.content}
            for m in s.messages.filter(id__gt=after_id)]


@mcp.tool()
def post_chat(session_id: int, message: str, sender: str = "") -> dict:
    """Antwortet in einer Chat-Session (Projekt-/RAG-Chat) als Persona (role=
    ASSISTANT, mit Provenienz). `sender` = dein @-Handle. NIE Quelle der Wahrheit;
    schreibt nichts Verbindliches. WRITE-Token nötig."""
    from app.models import ChatSession, ChatMessage, ChatRole
    s = ChatSession.objects.filter(id=session_id).first()
    if not s:
        return {"ok": False, "error": "Session nicht gefunden"}
    ChatMessage.objects.create(session=s, role=ChatRole.ASSISTANT, content=message,
                               author_label=sender or "@llm", generated_by_llm=True)
    return {"ok": True, "session_id": session_id}


@mcp.tool()
def get_item_chat(project_key: str, identifier: str) -> list:
    """Liest den Item-Chat eines WorkItems (alle Beteiligten: Menschen + LLMs).
    Nutze dies, nachdem dich list_my_mentions zu einem Item geführt hat, um den
    Verlauf zu lesen und dann mit post_item_chat zu antworten."""
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return []
    return [{"id": m.id, "role": m.role, "sender": m.sender_label(),
             "sender_handle": _sender_handle(m), "content": m.content,
             "generated_by_llm": m.generated_by_llm}
            for m in _owner_less_item_chat(w).messages.all()]


@mcp.tool()
def post_item_chat(project_key: str, identifier: str, message: str,
                   sender: str = "") -> dict:
    """
    Schreibt eine Nachricht in den ITEM-CHAT (beratend, role=ASSISTANT, mit
    Provenienz). So antwortest du den Menschen, die dich per @<handle> angesprochen
    haben; du darfst sie ebenfalls per @<vorname> adressieren.

    `sender` = DEIN Absender-Name/Handle (z. B. dein @-Handle), damit im Chat dein
    Name statt „LLM" steht. Bitte immer mit angeben.

    GUARDRAIL: Der Chat ist NIE Quelle der Wahrheit. Dieses Tool schreibt NICHTS in
    WorkItem.body o. ä.; Übernahme in eine Spezifikation ist immer manuelles,
    menschliches Einfügen. Verbindliche Inhalte trägt nur ein Mensch im Editor ein.
    WRITE-Token nötig.
    """
    from app.models import ChatMessage, ChatRole
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return {"ok": False, "error": f"{identifier} nicht gefunden"}
    if not (message or "").strip():
        return {"ok": False, "error": "leere Nachricht"}
    ChatMessage.objects.create(session=_owner_less_item_chat(w),
                               role=ChatRole.ASSISTANT, content=message,
                               author_label=(sender or "").strip()[:64],
                               generated_by_llm=True, llm_model="mcp")
    return {"ok": True, "identifier": w.identifier}


# ── Bearer-Token-Auth (SSE) ────────────────────────────────────────────────

# Die Teststufen sind KEINE Token-Scope-Dimension, wohl aber ein URL-Scope: die
# V-Schritt-Personas (Gideon … Thomas) verbinden sich mit ALL-System-Tokens auf
# …/<projekt>/<teststufe>/mcp und bekommen nur Anfragen ihrer Phase.
VALID_SCOPES = {"all", "req", "spec", "arch", "mod",
                "modtest", "inttest", "systest", "acctest"}

# Tools, die den Datenbestand verändern -> nur mit access=WRITE erlaubt.
WRITE_TOOLS = {"set_document_status", "propose_requirement", "update_requirement",
               "submit_feedback", "create_workitem", "update_workitem",
               "delete_workitem", "reimport_requirements", "post_item_chat",
               "tag_document", "tag_workitem", "tag_chunk", "audit_downgrade",
               "post_chat", "create_outline_item", "delete_revision"}

# V-Stufen je Scope-Slug (req/spec/arch/mod). ALL deckt alle ab.
SCOPE_PHASES = {"req": "REQ", "spec": "SPEC", "arch": "ARCH", "mod": "MOD",
                "modtest": "MODTEST", "inttest": "INTTEST", "systest": "SYSTEST",
                "acctest": "ACCTEST"}


async def _buffer_body(receive):
    """ASGI-Body puffern und die Original-Messages zum Replay zurückgeben."""
    body, msgs, more = b"", [], True
    while more:
        m = await receive()
        msgs.append(m)
        if m["type"] == "http.request":
            body += m.get("body", b"")
            more = m.get("more_body", False)
        else:
            more = False
    return body, msgs


def _is_write_call(body: bytes) -> bool:
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return False
    items = data if isinstance(data, list) else [data]
    for it in items:
        if isinstance(it, dict) and it.get("method") == "tools/call":
            if (it.get("params") or {}).get("name") in WRITE_TOOLS:
                return True
    return False


def _foreign_object_id(args: dict, project_id: int) -> bool:
    """True, wenn eine ID in den Tool-Argumenten auf ein Objekt eines ANDEREN
    Projekts zeigt (unbekannte IDs bleiben dem Tool überlassen: „nicht gefunden")."""
    from app.models import ChatSession, EsraTask, FeedbackRequest
    checks = (("session_id", ChatSession), ("task_id", EsraTask),
              ("request_id", FeedbackRequest), ("doc_id", ProjectDocument))
    for name, model in checks:
        val = args.get(name)
        if val is None:
            continue
        try:
            owner = model.objects.filter(pk=int(val)).values_list("project_id", flat=True).first()
        except (TypeError, ValueError):
            return True
        if owner is not None and owner != project_id:
            return True
    return False


def _scope_violation(body: bytes, tok) -> str | None:
    """Sperrt Tool-Aufrufe auf das Projekt + (außer ALL) die V-Stufe des Tokens.
    Liefert eine Fehlermeldung oder None, wenn alles erlaubt ist."""
    if getattr(tok, "system", False):
        return None        # eingebaute System-Personas: KEINE Projekt-/Scope-Schranke
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return None
    items = data if isinstance(data, list) else [data]
    proj_key = getattr(getattr(tok, "project", None), "key", None)
    allowed_phase = SCOPE_PHASES.get(tok.scope_slug) if tok.scope != "ALL" else None
    for it in items:
        if not (isinstance(it, dict) and it.get("method") == "tools/call"):
            continue
        args = ((it.get("params") or {}).get("arguments")) or {}
        pk = args.get("project_key")
        if pk and proj_key and pk != proj_key:
            return f"Token ist auf Projekt '{proj_key}' gesperrt, nicht '{pk}'."
        # Tools, die Objekte per ID ansprechen (ohne project_key), dürfen nicht über
        # die Projektgrenze greifen: die ID muss zu einem Objekt des Token-Projekts gehören.
        if tok.project_id and _foreign_object_id(args, tok.project_id):
            return "Das Objekt gehört zu einem anderen Projekt als der Token."
        if allowed_phase:
            phase = (args.get("phase") or "").upper()
            ident = (args.get("identifier") or "").upper()
            ref = phase or (ident.split("-", 1)[0] if "-" in ident else "")
            if ref and ref != allowed_phase:
                return (f"Token-Scope '{tok.scope_slug}' erlaubt nur {allowed_phase}, "
                        f"nicht '{ref}'.")
    return None


def _get_token(headers: dict):
    auth = headers.get(b"authorization", b"").decode()
    if not auth.lower().startswith("bearer "):
        return None
    raw = auth.split(" ", 1)[1].strip()
    tok = MCPToken.objects.filter(token=raw, active=True).first()
    if tok:
        MCPToken.objects.filter(pk=tok.pk).update(last_used=timezone.now())
    return tok


def _scope_ok(tok, url_scope: str) -> bool:
    """Token darf nur seinen eigenen V-Modell-Scope (oder ALL) bedienen."""
    return tok.scope == "ALL" or tok.scope_slug == url_scope


# ── Push-Kanal: offene FeedbackRequests an verbundene Worker pushen ─────────

def _claim_pending(project_key: str, url_scope: str) -> list[dict]:
    """
    Holt offene (PENDING) FeedbackRequests eines Projekts – gefiltert auf den
    V-Schritt des Scopes – und markiert sie atomar als CLAIMED (kein doppeltes
    Pushen an mehrere Worker). Liefert selbsttragende Payloads inkl. Persona,
    sodass ein Worker OHNE DB-Zugriff antworten kann.
    """
    from app.models import FeedbackRequest, FeedbackStatus, Project
    from app import llm_roles
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return []
    out = []
    qs = FeedbackRequest.objects.filter(
        project=proj, status=FeedbackStatus.PENDING).order_by("created_at")
    for req in qs:
        phase = getattr(req.item, "phase", None)
        if url_scope != "all" and (phase or "").lower() != url_scope:
            continue
        # atomar beanspruchen (race-sicher gegen weitere Worker/Verbindungen)
        claimed = FeedbackRequest.objects.filter(
            pk=req.pk, status=FeedbackStatus.PENDING).update(
                status=FeedbackStatus.CLAIMED)
        if not claimed:
            continue
        role = llm_roles.PHASE_TO_ROLE.get(phase, phase)
        out.append({
            "request_id": req.id,
            "v_step": phase,
            "role": role,
            "iec_reference": llm_roles.iec_reference_for(phase) if phase else "",
            "draft": req.draft,
            "neighbours": req.neighbours,
            "persona": llm_roles.context_for(project=proj, item=req.item),
        })
    return out


def _max_chat_id() -> int:
    """Aktuelle höchste ChatMessage-ID (Cursor-Start, um Backlog zu überspringen)."""
    from django.db.models import Max
    from app.models import ChatMessage
    try:
        return ChatMessage.objects.aggregate(m=Max("id"))["m"] or 0
    except Exception:
        return 0


def _claim_chat_mentions(project_key: str, after_id: int):
    """
    Neue menschliche Item-Chat-Nachrichten mit @-Erwähnung (id > after_id) eines
    Projekts. Liefert (payloads, neue_max_id). Self-contained (Item-Identifier +
    Text), damit das verbundene LLM via get_item_chat/post_item_chat antworten
    kann. Das LLM entscheidet selbst, ob SEIN @-Handle gemeint ist.
    """
    from app.models import ChatMessage, ChatRole, Project
    proj = Project.objects.filter(key=project_key).first()
    if not proj:
        return [], after_id
    qs = (ChatMessage.objects.filter(
            session__project=proj, session__related_item__isnull=False,
            role=ChatRole.USER, content__contains="@", id__gt=after_id)
          .select_related("session", "session__related_item", "author")
          .order_by("id"))
    out, last = [], after_id
    for m in qs:
        last = max(last, m.id)
        item = m.session.related_item
        recent = [{"role": x.role, "content": (x.content or "")[:400]}
                  for x in m.session.messages.all().order_by("created_at")[-8:]]
        out.append({"identifier": item.identifier, "title": item.title,
                    "body": (item.body or "")[:800],
                    "from": m.author.get_username() if m.author_id else "user",
                    "message": (m.content or "")[:500], "history": recent})
    return out, last


def _submit_worker_toasts(request_id: int, toasts, who: str = "llm-worker") -> bool:
    """Schreibt die vom Worker gelieferten Toasts zurück (NUR Toasts, nie Inhalt)."""
    from app.models import FeedbackRequest, FeedbackStatus
    req = FeedbackRequest.objects.filter(pk=request_id).first()
    if not req:
        return False
    req.toasts = toasts if isinstance(toasts, list) else []
    req.source = "worker"
    req.answered_by = who
    req.status = FeedbackStatus.ANSWERED
    req.answered_at = timezone.now()
    req.save()
    return True


def _submit_chat_reply(project_key: str, identifier: str, message: str, sender: str) -> bool:
    """Worker-Antwort auf eine @-Erwähnung → als ASSISTANT-Nachricht in den
    Item-Chat (beratend, mit Absender-Label). Schreibt NIE in WorkItem.body."""
    from app.models import Project, ChatMessage, ChatRole
    if not (message or "").strip():
        return False
    proj = Project.objects.filter(key=project_key).first()
    w = proj.work_items.filter(identifier=identifier).first() if proj else None
    if not w:
        return False
    ChatMessage.objects.create(session=_owner_less_item_chat(w),
                               role=ChatRole.ASSISTANT, content=message,
                               author_label=(sender or "").strip()[:64],
                               generated_by_llm=True, llm_model="mcp-worker")
    return True


class BearerASGIMiddleware:
    """
    ASGI-Middleware: Bearer-Token-Auth + V-Modell-Scope aus der URL.
    Pfad-Schema:  /<scope>/sse   (scope ∈ all|req|spec|arch|mod)
    Der Scope wird gegen den Token geprüft und für die innere SSE-App
    abgetrennt (die sieht /sse bzw. /messages/).
    """

    def __init__(self, app):
        self.app = app

    async def _deny(self, send, status, msg):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body",
                    "body": ('{"error":"%s"}' % msg).encode()})

    async def _events_stream(self, scope, receive, send, project_key, url_scope):
        """
        SSE-Push OHNE Poll: hält die Verbindung offen und pusht neue (PENDING)
        FeedbackRequests des Projekts/Scopes als `event: feedback`. Der Server
        beobachtet seine eigene DB (das ist NICHT der Operator); der verbundene
        Worker wird per Event getriggert und antwortet via POST .../toasts.
        """
        from asgiref.sync import sync_to_async
        interval = float(os.getenv("MCP_EVENTS_POLL", "1.5"))
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream"),
                                (b"cache-control", b"no-cache"),
                                (b"connection", b"keep-alive")]})
        await send({"type": "http.response.body", "body": b": connected\n\n",
                    "more_body": True})
        # Chat-Cursor: nur @-Erwähnungen NACH Verbindungsaufbau pushen (kein Backlog;
        # ältere holt das LLM bei Bedarf über list_my_mentions).
        chat_after = await sync_to_async(_max_chat_id, thread_sensitive=True)()

        gone = {"v": False}
        async def _watch():
            while not gone["v"]:
                m = await receive()
                if m.get("type") == "http.disconnect":
                    gone["v"] = True
                    return
        watcher = asyncio.ensure_future(_watch())
        try:
            while not gone["v"]:
                reqs = await sync_to_async(_claim_pending, thread_sensitive=True)(
                    project_key, url_scope)
                for payload in reqs:
                    data = json.dumps(payload, ensure_ascii=False).encode()
                    await send({"type": "http.response.body",
                                "body": b"event: feedback\ndata: " + data + b"\n\n",
                                "more_body": True})
                # Neue Item-Chat-@-Erwähnungen pushen (LLM hört auf dem Chat-Kanal).
                mentions, chat_after = await sync_to_async(
                    _claim_chat_mentions, thread_sensitive=True)(project_key, chat_after)
                for payload in mentions:
                    data = json.dumps(payload, ensure_ascii=False).encode()
                    await send({"type": "http.response.body",
                                "body": b"event: chat_mention\ndata: " + data + b"\n\n",
                                "more_body": True})
                await send({"type": "http.response.body", "body": b": ping\n\n",
                            "more_body": True})
                await asyncio.sleep(interval)
        except (asyncio.CancelledError, RuntimeError):
            pass
        finally:
            watcher.cancel()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path.rstrip("/") in ("", "/health"):
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body",
                        "body": _health_body()})
            return

        # Pfad: /<projekt>/<scope>/<rest>   (rest = mcp | sse | messages/…)
        parts = path.lstrip("/").split("/", 2)
        if len(parts) < 2:
            return await self._deny(send, 404, "Pfad erwartet /<projekt>/<scope>/mcp")
        url_project, url_scope = parts[0], parts[1].lower()
        rest = "/" + (parts[2] if len(parts) > 2 else "")
        if url_scope not in VALID_SCOPES:
            return await self._deny(send, 404, "unbekannter Scope (all|req|spec|arch|mod)")

        from asgiref.sync import sync_to_async
        headers = dict(scope.get("headers") or [])
        tok = await sync_to_async(_get_token)(headers)
        if tok is None:
            return await self._deny(send, 401, "invalid or missing bearer token")
        # Token ist auf EIN Projekt beschränkt -> Projekt in der URL muss passen.
        tok_project = await sync_to_async(lambda t: t.project.key if t.project_id else None)(tok)
        if tok_project != url_project:
            return await self._deny(send, 403,
                                    f"Token gilt nur für Projekt '{tok_project}', nicht '{url_project}'")
        if not _scope_ok(tok, url_scope):
            return await self._deny(send, 403,
                                    f"Token-Scope '{tok.scope_slug}' deckt '{url_scope}' nicht ab")

        # ── Push-Kanal (SSE) ohne Poll + Worker-Submit ──────────────────────
        #   GET  /<projekt>/<scope>/events                 -> SSE-Stream offener Anfragen
        #   POST /<projekt>/<scope>/events/<id>/toasts     -> Worker liefert Toasts
        if rest.startswith("/events"):
            if scope.get("method") == "POST":
                if tok.access != "WRITE":
                    return await self._deny(send, 403, "events-submit braucht WRITE-Token")
                seg = rest.strip("/").split("/")        # ["events","<id>","toasts"]
                # Worker-Antwort auf eine Chat-@-Erwähnung.
                if len(seg) == 2 and seg[1] == "chat-reply":
                    body, _m = await _buffer_body(receive)
                    try:
                        d = json.loads(body or b"{}") or {}
                    except Exception:
                        return await self._deny(send, 400, "ungueltiges JSON")
                    ok = await sync_to_async(_submit_chat_reply)(
                        url_project, d.get("identifier", ""), d.get("message", ""),
                        d.get("sender", ""))
                    await send({"type": "http.response.start", "status": 200 if ok else 404,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body",
                                "body": json.dumps({"ok": ok}).encode()})
                    return
                if len(seg) != 3 or seg[2] != "toasts" or not seg[1].isdigit():
                    return await self._deny(send, 404, "POST /events/<id>/toasts oder /events/chat-reply erwartet")
                body, _msgs = await _buffer_body(receive)
                try:
                    toasts = (json.loads(body or b"{}") or {}).get("toasts", [])
                except Exception:
                    return await self._deny(send, 400, "ungueltiges JSON")
                ok = await sync_to_async(_submit_worker_toasts)(int(seg[1]), toasts)
                await send({"type": "http.response.start", "status": 200 if ok else 404,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body",
                            "body": json.dumps({"ok": ok, "request_id": int(seg[1]),
                                                "anzahl_toasts": len(toasts) if ok else 0}).encode()})
                return
            return await self._events_stream(scope, receive, send, url_project, url_scope)

        # SSE-Endpoint-Rewrite: der Client bekommt den messages-Pfad MIT
        # Projekt/Scope (und optionalem Pfad-Präfix), sonst posten Tool-Aufrufe
        # ins Leere. Präfix PRO VERBINDUNG: Header `X-Forwarded-Prefix` (von nginx
        # gesetzt bzw. vom on-box-Worker leer mitgegeben) hat Vorrang; sonst das
        # globale MCP_PATH_PREFIX (Default ""). So braucht der lokale MCP-Client-
        # Worker keinen nginx-Umweg (Präfix ""), während nginx-Clients "/mcp" sehen.
        if rest.startswith("/sse"):
            _hdrs = {k.decode().lower(): v.decode()
                     for k, v in scope.get("headers", [])}
            _fwd = _hdrs.get("x-forwarded-prefix")
            base_prefix = _fwd if _fwd is not None else os.getenv("MCP_PATH_PREFIX", "")
            prefix = (base_prefix + f"/{url_project}/{url_scope}").encode()
            _send = send
            async def send(message, _send=_send, _prefix=prefix):
                if message.get("type") == "http.response.body":
                    b = message.get("body", b"")
                    if b"data: /messages/" in b:
                        message = {**message,
                                   "body": b.replace(b"data: /messages/",
                                                     b"data: " + _prefix + b"/messages/")}
                await _send(message)

        # Tool-Aufrufe (JSON-RPC-POST an .../messages/) gegen den Token sperren:
        #   1. READ-Token darf keine Schreib-Tools aufrufen.
        #   2. project_key/Phase müssen zum Token passen (ALL darf alles).
        if scope.get("method") == "POST" and rest.startswith(("/messages", "/mcp")):
            body, msgs = await _buffer_body(receive)
            if tok.access != "WRITE" and _is_write_call(body):
                return await self._deny(
                    send, 403, "READ-Token: Schreib-Tool nicht erlaubt (access=WRITE noetig)")
            violation = _scope_violation(body, tok)
            if violation:
                return await self._deny(send, 403, violation)
            i = {"n": 0}
            _orig_receive = receive      # NICHT `receive` selbst: replay ersetzt es unten
            async def replay():
                if i["n"] < len(msgs):
                    m = msgs[i["n"]]; i["n"] += 1; return m
                return await _orig_receive()
            receive = replay

        # Projekt+Scope abtrennen -> innere App sieht /sse bzw. /messages/.
        scope = dict(scope)
        scope["path"] = rest
        scope["raw_path"] = rest.encode()
        await self.app(scope, receive, send)


def _sse_enabled() -> bool:
    from django.conf import settings
    return bool(getattr(settings, "MCP_SSE_ENABLED", True))


def _health_body() -> bytes:
    transports = ["streamable-http"] + (["sse"] if _sse_enabled() else [])
    return json.dumps({"status": "ok", "transports": transports}).encode()


class _Transports:
    """Verteilt auf die Transporte: /mcp = Streamable HTTP (immer), /sse und
    /messages/ = SSE (veraltet, per MCP_SSE_ENABLED abschaltbar). Der Lifespan
    (Session-Manager) gehört der Streamable-HTTP-App."""

    def __init__(self, sse_app, http_app, sse_enabled):
        self.sse_app, self.http_app, self.sse_enabled = sse_app, http_app, sse_enabled

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.http_app(scope, receive, send)
        if scope.get("path", "").startswith(("/sse", "/messages")):
            if not self.sse_enabled:
                body = json.dumps({"error": "SSE-Transport ist deaktiviert "
                                   "(MCP_SSE_ENABLED=false) – bitte Streamable HTTP "
                                   "unter /<projekt>/<scope>/mcp verwenden."}).encode()
                await send({"type": "http.response.start", "status": 410,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
                return
            return await self.sse_app(scope, receive, send)
        return await self.http_app(scope, receive, send)


def build_app():
    """ASGI-App mit Bearer-Token-Schutz: Streamable HTTP plus (optional) SSE."""
    return BearerASGIMiddleware(_Transports(
        mcp.sse_app(), mcp.streamable_http_app(), _sse_enabled()))


app = build_app()


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8765"))
    print(f"MCP-Server: http://{host}:{port}/<projekt>/<scope>/mcp"
          + ("  (+ SSE …/sse, veraltet)" if _sse_enabled() else "")
          + "  (Bearer-Token erforderlich)")
    uvicorn.run(app, host=host, port=port)
