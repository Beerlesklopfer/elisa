"""
Beratungs-Chat (RAG-gestützt) — CLAUDE.md Regel 3, dritte Kategorie.

GUARDRAILS (nicht aufweichen):
  - Beratend & persistiert, aber NIE Quelle der Wahrheit.
  - Kein Endpoint schreibt aus dem Chat in WorkItem.body oder ein anderes
    verbindliches Feld. Übernahme in eine Spezifikation ist immer manuelles,
    menschliches Einfügen.
  - Jede Assistenten-Nachricht trägt Provenienz (generated_by_llm, llm_model)
    und die verwendeten Norm-Klauseln (cited_clauses).

Der Chat ist RAG-gestützt: durch das Norm-RAG kann Ollama normative Auskünfte
(IEC 61508) geben — geerdet an abgerufenen Klauseln, mit Quellenangabe.
"""
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import ChatSession, ChatMessage, ChatRole
from .projects import get_active_project, is_project_member
from .permissions import pm_or_admin_required, is_pm_or_admin
from . import rag_service

CHAT_SYSTEM = """Du bist ein beratender Assistent für funktionale Sicherheit
nach IEC 61508. Du gibst Auskünfte und Einschätzungen, geerdet am
mitgegebenen Norm-Kontext. Wenn du den Kontext nutzt, nenne die Quelle
(Norm, Seite). Steht etwas nicht im Kontext, sage das ehrlich.

HARTE REGEL — keine erfundenen Normen: Erfinde NIEMALS Normen, Klauseln oder
Ausgabedaten. Wenn nach „welche Normen sind bekannt/verfügbar" gefragt wird,
nenne AUSSCHLIESSLICH die Einträge aus der unten mitgegebenen Liste
„VERFÜGBARE NORMEN". Steht eine Norm nicht in dieser Liste, existiert sie im
System nicht — sage das klar. Rate nicht.

WICHTIG: Du bist beratend, nicht verbindlich. Du verfasst KEINE freizugebende
Spezifikation und forderst den Nutzer nicht auf, deinen Text unverändert zu
übernehmen — der Mensch bleibt der Autor."""


def _visible_sessions(request):
    """Sichtbare Chats im aktiven Projekt: GETEILTE Projekt-Chats (alle Mitglieder)
    + die EIGENEN persönlichen Chats. Keine Item-Chats."""
    project = get_active_project(request)
    qs = (ChatSession.objects.filter(project=project, related_item__isnull=True)
          .filter(Q(shared=True) | Q(owner=request.user)))
    return project, qs


def _accessible_session(request, pk):
    """Session, wenn der Nutzer sie sehen darf: geteilt → Projektmitglied,
    persönlich → Eigentümer. Sonst 404."""
    project = get_active_project(request)
    s = get_object_or_404(ChatSession, pk=pk, project=project)
    if (s.shared and is_project_member(request.user, project)) or s.owner_id == request.user.id:
        return s
    raise Http404()


@login_required
def chat_index(request):
    project, sessions = _visible_sessions(request)
    # Default: der (geteilte) Projekt-Chat, sonst der neueste.
    active = sessions.filter(shared=True).first() or sessions.first()
    return _render_chat(request, active, sessions)


@login_required
def chat_session(request, pk):
    session = _accessible_session(request, pk)
    _, sessions = _visible_sessions(request)
    return _render_chat(request, session, sessions)


def _render_chat(request, active, sessions):
    from .participants import chat_participants, slug_handle
    me = slug_handle(request.user.first_name) or slug_handle(request.user.username)
    return render(request, "chat.html", {
        "active_tab": "chat",
        "sessions": sessions,
        "session": active,
        "messages": active.messages.all() if active else [],
        "participants": chat_participants(get_active_project(request)),
        "mention_token": f"@{me}" if me else "",
        "can_new_project_chat": is_pm_or_admin(request.user),
    })


# Kurze Aufgaben-Erklärung je System-Persona (Handle → Beschreibung). Andere
# (projekt-zugeteilte) LLMs bekommen eine generische Erklärung.
_PERSONA_BLURB = {
    "esra": "Normenrecherche – findet die passenden Normen, geerdet an den im "
               "System vorhandenen Norm-Dokumenten (nie frei erfunden).",
    "tertius": "Übersetzer – überträgt Items in die Sekundärsprachen des Projekts "
                "(informativ; die normative Quellsprache bleibt maßgeblich).",
    "nathan": "Externes Audit – prüft kritisch und kann bei Findings genau eine "
               "Stufe zurückstufen.",
}


def _welcome_intro_text(project):
    """Begrüßung eines NEUEN RAG-Chats: Lukas stellt sich und alle Personas mit
    ihrem Akronym vor (mit kurzer Aufgaben-Erklärung), damit man weiß, wen man
    per @-Handle wofür adressiert. Sprache = Sprache der anlegenden Person; die
    Akronyme bleiben englisch (international einheitlich)."""
    from django.utils.translation import gettext as _
    from app.participants import chat_participants
    from app.personas import SYSTEM_PERSONAS, VMODEL_PERSONAS, rag_persona
    rag = settings.RAG_PERSONA_NAME
    me = rag_persona(rag)
    lines = [_("Willkommen! Ich bin **%(name)s**%(acronym)s, dein RAG-gestützter "
               "Norm-Assistent (IEC 61508). Stell deine Frage zu den Normen — ich "
               "antworte geerdet an den vorhandenen Dokumenten und bin nie Quelle "
               "der Wahrheit.") % {"name": rag,
                                   "acronym": f" — {me['acronym']}" if me else ""},
             "", _("**System-Personas (per @-Handle ansprechbar):**")]
    connected = {p["handle"].lower(): p for p in chat_participants(project)
                 if p.get("kind") == "llm" and p.get("handle")}
    for p in SYSTEM_PERSONAS:
        if p is SYSTEM_PERSONAS[0]:      # Lukas stellt sich oben selbst vor
            continue
        state = "" if p["handle"] in connected else " " + _("*(derzeit nicht verbunden)*")
        lines.append(f"- **{p['name']}** (@{p['handle']}) — {p['acronym']}. "
                     f"{p['role']}{state}")
    lines += ["", _("**V-Modell-Personas (je Schritt):**")]
    for p in VMODEL_PERSONAS:
        lines.append(f"- **{p['name']}** — {p['step']} ({p['code']}): {p['acronym']}")
    known = {p["handle"] for p in SYSTEM_PERSONAS if p["handle"]}
    others = [p for h, p in connected.items() if h not in known]
    if others:
        lines += ["", _("**Weitere verbundene LLMs:**")]
    for p in others:
        label = (p.get("label") or "").strip()
        prov = (p.get("provider") or "").title()
        blurb = (_("beratendes LLM") + (f" ({prov})" if prov else "")
                 + (f" – {label}" if label else "") + ".")
        lines.append(f"- **@{p['handle']}** — {blurb}")
    return "\n".join(lines)


@login_required
@require_POST
def chat_new(request):
    """Persönlichen RAG-Chat anlegen (nur für mich sichtbar) – mit Begrüßung durch
    Lukas, die die ansprechbaren System-Personas vorstellt."""
    project = get_active_project(request)
    session = ChatSession.objects.create(owner=request.user, project=project)
    ChatMessage.objects.create(
        session=session, role=ChatRole.ASSISTANT, content=_welcome_intro_text(project),
        author_label=settings.RAG_PERSONA_NAME,     # Absender = Lukas (nicht Esra)
        # Sentinel: markiert die Auto-Begrüßung, damit ihre @-Handle-Liste KEINE
        # Persona-Antworten auslöst (siehe server.py INTRO_MARKER). Persona↔Persona
        # ohne Mensch bleibt dadurch weiterhin möglich.
        generated_by_llm=True, llm_model="rag/welcome")
    return redirect("chat-session", pk=session.pk)


@login_required
@pm_or_admin_required
@require_POST
def chat_new_project(request):
    """Neuen ÜBERGREIFENDEN Projekt-Chat anlegen (geteilt; nur Admin/PM)."""
    title = (request.POST.get("title") or "Projekt-Chat").strip()[:255] or "Projekt-Chat"
    session = ChatSession.objects.create(
        project=get_active_project(request), shared=True, owner=None, title=title)
    return redirect("chat-session", pk=session.pk)


def _editable_session(request, pk):
    """Session, die der Nutzer umbenennen/löschen darf: geteilte Projekt-Chats nur
    Admin/PM, persönliche nur der Eigentümer. Sonst 404."""
    project = get_active_project(request)
    session = get_object_or_404(ChatSession, pk=pk, project=project)
    if session.shared:
        if not is_pm_or_admin(request.user):
            raise Http404()
    elif session.owner_id != request.user.id:
        raise Http404()
    return session


@login_required
@require_POST
def chat_delete(request, pk):
    """Chat löschen: geteilte Projekt-Chats nur Admin/PM, persönliche nur der
    Eigentümer."""
    _editable_session(request, pk).delete()
    return redirect("chat")


@login_required
@require_POST
def chat_rename(request, pk):
    """Chat umbenennen (gleiche Rechte wie Löschen). AJAX → JSON, sonst Redirect."""
    session = _editable_session(request, pk)
    title = (request.POST.get("title") or "").strip()[:255]
    if not title:
        return HttpResponseBadRequest("empty title")
    session.title = title
    session.save(update_fields=["title", "updated_at"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "title": title})
    return redirect("chat-session", pk=session.pk)


@login_required
@require_POST
def chat_send(request, pk):
    """
    Nimmt eine menschliche Nachricht, holt Norm-Kontext (RAG), fragt Ollama
    mit der gesamten Historie und persistiert beide Nachrichten.
    """
    session = _accessible_session(request, pk)
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")

    text = (payload.get("message") or "").strip()
    if not text:
        return HttpResponseBadRequest("empty message")

    # 1) Menschliche Nachricht speichern.
    user_msg = ChatMessage.objects.create(
        session=session, role=ChatRole.USER, content=text, author=request.user,
    )
    if not session.title:
        session.title = text[:60]
        session.save(update_fields=["title", "updated_at"])

    # Direkt per @handle angesprochene Personas/Teilnehmer? Dann SCHWEIGT der
    # generische RAG-LLM – die @-erwähnten Persona-Worker antworten (auch mehrere;
    # Erkennung per Regex). Der Chat lädt deren Antworten per Poll nach.
    import re as _re
    mentioned = {m.lower() for m in _re.findall(r"@([\w\-äöüÄÖÜß]+)", text)}
    if mentioned:
        from app.participants import chat_participants
        handles = {(p.get("handle") or "").lstrip("@").lower()
                   for p in chat_participants(session.project)}
        if mentioned & handles:
            session.save(update_fields=["updated_at"])
            return JsonResponse({"user": {"id": user_msg.id, "content": user_msg.content},
                                 "assistant": None})

    # 2) Kontext via RAG: Normen (global) + Projektdokumente (projekt-skopiert).
    from app import project_index
    hits = rag_service.retrieve_norm_context(text)
    proj_hits = project_index.retrieve_project_context(session.project, text)
    context = rag_service.format_context(hits)
    if proj_hits:
        context += ("\n\nProjektdokumente:\n"
                    + rag_service.format_context(proj_hits))

    # 3) Historie + System + Kontext an Ollama.
    history = [{"role": "system", "content": CHAT_SYSTEM}]
    # Rollenbeschreibung (falls Item bezogen) + Projektbeschreibung mitgeben.
    from app import llm_roles
    role_ctx = llm_roles.context_for(project=session.project,
                                     item=session.related_item)
    if role_ctx:
        history.append({"role": "system", "content": role_ctx})
    # Fragende Person mit adressierbarem @-Handle nennen, damit Lukas sie direkt
    # anspricht (nie generisch „@Mensch"), wie es die Personas auch tun.
    from app.participants import slug_handle
    _ah = slug_handle(request.user.first_name) or slug_handle(request.user.get_username())
    _aname = request.user.get_full_name() or request.user.get_username()
    _ahandle = ("@" + _ah) if _ah else _aname
    history.append({"role": "system", "content": (
        f"Die fragende Person ist {_aname} (Handle {_ahandle}). Sprich sie in deiner "
        f"Antwort mit {_ahandle} an – nie generisch '@Mensch'.")})
    # Deterministische Liste der wirklich vorhandenen Normen (gegen Halluzination).
    # Kanonisch gruppiert: eine Zeile je Norm, mit verfügbaren Sprachen/Ausgaben.
    from app import norm_refs
    groups = norm_refs.available_norms_grouped()
    if groups:
        norm_list = "\n".join(
            f"- {g['label']} (Sprachen: {', '.join(g['langs'])}; "
            f"{len(g['files'])} Ausgabe(n))" for g in groups)
    else:
        norm_list = "(noch keine Norm indexiert)"
    history.append({
        "role": "system",
        "content": f"VERFÜGBARE NORMEN (vollständig, nur diese existieren):\n{norm_list}",
    })
    # Schlagwortkatalog (kompakter Doku-Index) – spart Kontext-Breite.
    from app import keywords
    kw_cat = keywords.catalog_text(session.project)
    if kw_cat:
        history.append({"role": "system", "content": kw_cat})
    if context:
        history.append({
            "role": "system",
            "content": f"Norm-Kontext (Auszüge):\n{context}",
        })
    for m in session.messages.all():
        role = "assistant" if m.role == ChatRole.ASSISTANT else "user"
        history.append({"role": role, "content": m.content})

    try:
        from app import local_llm
        answer = local_llm.chat(history)
    except Exception as exc:
        from app import local_llm
        answer = f"({local_llm.backend_label()} nicht erreichbar: {exc})"

    # Zitierte Quellen dedupen (je Datei der erste Treffer).
    seen = {}
    for _, m in hits + proj_hits:
        q = m.get("quelle")
        if q and q not in seen:
            seen[q] = m.get("seite")
    cited = [{"quelle": q, "seite": p} for q, p in seen.items()]

    # 4) Assistenten-Antwort mit Provenienz speichern (nie Quelle der Wahrheit).
    assistant_msg = ChatMessage.objects.create(
        session=session, role=ChatRole.ASSISTANT, content=answer,
        generated_by_llm=True, llm_model=settings.LOCAL_CHAT_MODEL,
        author_label=settings.RAG_PERSONA_NAME,     # „Lukas" statt „llama3.1"
        cited_sources=cited,
    )
    session.save(update_fields=["updated_at"])

    return JsonResponse({
        "user": {"id": user_msg.id, "content": user_msg.content},
        "assistant": {
            "id": assistant_msg.id,
            "content": assistant_msg.content,
            "model": assistant_msg.llm_model,
            "sender": assistant_msg.sender_label(),
            "sources": cited,
        },
    })


@login_required
def chat_poll(request, pk):
    """Neue Nachrichten einer Session seit `after` (für den Live-Nachzug der
    asynchronen Persona-/Inter-Persona-Antworten im Chat)."""
    session = _accessible_session(request, pk)
    try:
        after = int(request.GET.get("after") or 0)
    except ValueError:
        after = 0
    out = [{"id": m.id, "role": m.role.lower(), "content": m.content,
            "sender": m.sender_label(), "sources": m.cited_sources or []}
           for m in session.messages.filter(id__gt=after).order_by("id")]
    return JsonResponse({"messages": out})
