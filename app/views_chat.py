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
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseBadRequest, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import ChatSession, ChatMessage, ChatRole
from .projects import get_active_project, is_project_member
from .permissions import pm_or_admin_required, is_pm_or_admin, is_admin
from . import rag_service
from .templatetags.chat_extras import chat_render

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
    other_chats = []
    if is_admin(request.user):
        # Nur Verwaltungsdaten (Eigentümer, Datum, Anzahl) – der Inhalt fremder
        # persönlicher Chats wird nicht angezeigt.
        other_chats = list(
            ChatSession.objects.filter(project=get_active_project(request),
                                       related_item__isnull=True, shared=False)
            .exclude(owner=request.user).select_related("owner")
            .annotate(n_messages=Count("messages")).order_by("-updated_at"))
    return render(request, "chat.html", {
        "active_tab": "chat",
        "other_chats": other_chats,
        "sessions": sessions,
        "session": active,
        "messages": active.messages.all() if active else [],
        "participants": chat_participants(get_active_project(request)),
        "mention_token": f"@{me}" if me else "",
        "can_new_project_chat": is_pm_or_admin(request.user),
        "can_delete_all": _can_delete_all(request.user, active),
        "chat_target": _current_target(active, chat_participants(get_active_project(request)))
                       if active else "",
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
             "", _("Mit **@all** sprichst du alle Teilnehmer auf einmal an."),
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
        state = "" if p["handle"] in connected else " " + _("*(derzeit nicht verbunden)*")
        lines.append(f"- **{p['name']}** (@{p['handle']}) — {p['step']} ({p['code']}): "
                     f"{p['acronym']}{state}")
    known = {p["handle"] for p in SYSTEM_PERSONAS if p["handle"]} | \
        {p["handle"] for p in VMODEL_PERSONAS}
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
    Eigentümer. ADMINISTRATOREN dürfen jeden Chat des Projekts löschen (auch die
    persönlichen anderer Nutzer – ohne ihn zu öffnen; Item-Chats bleiben tabu)."""
    if is_admin(request.user):
        get_object_or_404(ChatSession, pk=pk, project=get_active_project(request),
                          related_item__isnull=True).delete()
    else:
        _editable_session(request, pk).delete()
    return redirect("chat")


def _current_target(session, parts):
    """Aktuell gemeinte Persona (zuletzt per @ angesprochener LLM-Teilnehmer)."""
    from app.chat_addressing import implicit_addressees
    llm = {(p.get("handle") or "").lstrip("@").lower() for p in parts if p.get("kind") == "llm"}
    hit = sorted(implicit_addressees(session.messages.order_by("id")) & llm)
    return "@" + hit[0] if len(hit) == 1 else (", ".join("@" + h for h in hit) if hit else "")


def _reply_ref(m):
    """Kurzbezug auf die Nachricht, auf die m antwortet (oder None)."""
    r = m.reply_to
    if not r:
        return None
    return {"id": r.id, "sender": r.sender_label(),
            "text": (r.content or "").replace("\n", " ")[:90]}


@login_required
@require_POST
def chat_message_delete(request, pk):
    """Einzelne Chat-Nachricht löschen. Rechte: Administratoren jede Nachricht des
    Projekts; im persönlichen Chat der Eigentümer jede; im geteilten Projekt-Chat
    Projektleitung jede, Mitglieder nur ihre eigenen. Item-Chats bleiben tabu."""
    msg = get_object_or_404(ChatMessage.objects.select_related("session"), pk=pk,
                            session__project=get_active_project(request),
                            session__related_item__isnull=True)
    if not _can_delete_message(request.user, msg):
        raise Http404()
    msg.delete()
    return JsonResponse({"ok": True})


def _can_delete_all(user, session):
    """Darf der Nutzer in dieser Session JEDE Nachricht löschen?"""
    if session is None:
        return False
    if is_admin(user):
        return True
    if session.shared:
        return is_pm_or_admin(user)
    return session.owner_id == user.id


def _can_delete_message(user, msg):
    s = msg.session
    if _can_delete_all(user, s):
        return True
    return bool(s.shared and msg.author_id and msg.author_id == user.id)


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
    from app.chat_addressing import mentions as _mentions, implicit_addressees
    from app.participants import chat_participants
    mentioned = _mentions(text)
    parts = chat_participants(session.project)
    llm_handles = {(p.get("handle") or "").lstrip("@").lower()
                   for p in parts if p.get("kind") == "llm"}
    if not mentioned:
        # Keine @-Erwähnung: gemeint ist, wer zuletzt angesprochen wurde (solange der
        # Mensch niemand anderen anspricht). Nur LLM-Teilnehmer lösen Antworten aus.
        prior = list(session.messages.exclude(pk=user_msg.pk).order_by("id"))
        mentioned = implicit_addressees(prior) & llm_handles
    if mentioned:
        handles = {(p.get("handle") or "").lstrip("@").lower() for p in parts}
        handles.add("all")          # @all = alle Teilnehmer
        if mentioned & handles:
            session.save(update_fields=["updated_at"])
            return JsonResponse({"user": {"id": user_msg.id, "content": user_msg.content,
                                          "html": str(chat_render(user_msg.content))},
                                 "assistant": None})

    # 2) Kontext via RAG: Normen (global) + Projektdokumente (projekt-skopiert).
    from app import project_index
    hits = rag_service.retrieve_norm_context(text)
    proj_hits = project_index.retrieve_project_context(session.project, text)
    context = rag_service.format_context(hits)
    if proj_hits:
        context += ("\n\nProjektdokumente:\n"
                    + rag_service.format_context(proj_hits))

    # QUELLENPFLICHT (app/grounding.py): nur belegte Aussagen, nummerierte Quellen mit
    # klickbaren Links; ohne relevante Quelle antwortet das Modell gar nicht.
    from app import grounding
    from app.personas import tooltip
    g_sources = grounding.numbered(query=text, hits=
        [{"source": m.get("quelle"), "page": m.get("seite"), "text": doc,
          "distance": m.get("distanz"), "kind": "norm"} for doc, m in hits]
        + [{"source": m.get("quelle"), "page": m.get("seite"), "text": doc,
            "distance": m.get("distanz"), "kind": "doc"} for doc, m in proj_hits])
    pre = None
    if grounding.is_smalltalk(text):
        head, _, task = tooltip("lukas").partition("\n")
        pre = (f"Ich bin **{head}**. {task}. Stell mir eine Frage – ich antworte nur mit "
               f"Aussagen, die ich im RAG belegen kann (mit Quellenlinks).")
    elif not g_sources:
        pre = grounding.NO_SOURCE
    if pre is not None:
        assistant_msg = ChatMessage.objects.create(
            session=session, role=ChatRole.ASSISTANT, content=pre, generated_by_llm=False,
            llm_model="rag/grounding", author_label=settings.RAG_PERSONA_NAME,
            reply_to=user_msg, cited_sources=[])
        session.save(update_fields=["updated_at"])
        return JsonResponse({
            "user": {"id": user_msg.id, "content": user_msg.content,
                     "html": str(chat_render(user_msg.content))},
            "assistant": {"id": assistant_msg.id, "content": pre,
                          "html": str(chat_render(pre)), "model": "rag/grounding",
                          "sender": assistant_msg.sender_label(), "sources": []}})

    # 3) Schlanke Anfrage: Persona + Quellenpflicht + NUR die belegbaren Quellen und der
    #    Gesprächsverlauf (keine ungeprüften Zusatzlisten – die würden Erfundenes erlauben).
    from app.participants import slug_handle
    _ah = slug_handle(request.user.first_name) or slug_handle(request.user.get_username())
    _aname = request.user.get_full_name() or request.user.get_username()
    _ahandle = ("@" + _ah) if _ah else _aname
    recent = [f"{('Assistent' if m.role == ChatRole.ASSISTANT else _aname)}: {(m.content or '')[:300]}"
              for m in session.messages.exclude(pk=user_msg.pk).order_by("-id")[:4][::-1]]
    history = [
        {"role": "system", "content": (
            "Du bist LUKAS, der RAG-Assistent für Normen und Projektdokumente (IEC 61508 u. a.). "
            "Antworte knapp auf Deutsch. Du berätst nur; verbindliche Inhalte trägt der Mensch im "
            f"Editor ein. Sprich die fragende Person ({_aname}) mit {_ahandle} an.\n\n"
            + grounding.RULES)},
        {"role": "user", "content": (
            grounding.sources_block(g_sources)
            + ("\n\nBisheriger Verlauf:\n" + "\n".join(recent) if recent else "")
            + f"\n\nFrage von {_aname}: {text}")},
    ]

    try:
        from app import local_llm
        raw = local_llm.chat(history)
        answer, used, _ok = grounding.finalize(raw, g_sources)
        cited = grounding.cited_payload(used, g_sources)
    except Exception as exc:
        from app import local_llm
        answer = f"({local_llm.backend_label()} nicht erreichbar: {exc})"
        cited = []

    # 4) Assistenten-Antwort mit Provenienz speichern (nie Quelle der Wahrheit).
    assistant_msg = ChatMessage.objects.create(
        session=session, role=ChatRole.ASSISTANT, content=answer,
        generated_by_llm=True, llm_model=settings.LOCAL_CHAT_MODEL,
        author_label=settings.RAG_PERSONA_NAME,     # „Lukas" statt „llama3.1"
        reply_to=user_msg, cited_sources=cited,
    )
    session.save(update_fields=["updated_at"])

    return JsonResponse({
        "user": {"id": user_msg.id, "content": user_msg.content,
                 "html": str(chat_render(user_msg.content))},
        "assistant": {
            "id": assistant_msg.id,
            "content": assistant_msg.content,
            "html": str(chat_render(assistant_msg.content)),
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
    from app.templatetags.chat_extras import chat_render
    out = [{"id": m.id, "role": m.role.lower(), "content": m.content,
            "html": str(chat_render(m.content)), "reply": _reply_ref(m),
            "sender": m.sender_label(), "sources": m.cited_sources or []}
           for m in session.messages.filter(id__gt=after).order_by("id")]
    return JsonResponse({"messages": out})
