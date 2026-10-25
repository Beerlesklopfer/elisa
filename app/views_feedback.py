"""
Write-time feedback endpoint.

WICHTIG: Dieser Endpoint SCHREIBT KEINEN INHALT. Er bekommt den gerade
getippten Text, laesst ihn von Ollama beurteilen und gibt ephemere
Hinweise (Toasts) als JSON zurueck. Der Inhalt bleibt ausschliesslich
beim Menschen; das LLM kommentiert und schlaegt Referenzen vor -- mehr nicht.

Das Bestaetigen einer vorgeschlagenen Norm-Verknuepfung ist bewusst ein
SEPARATER Endpoint, den nur ein Mensch ausloest.
"""

import json
from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

# Fenster, in dem ein MCP-Token als „Team online" gilt (zuletzt benutzt).
TEAM_ONLINE_SECONDS = int(getattr(settings, "FEEDBACK_TEAM_WINDOW", 120))
# Wartet der Editor länger als dies auf das Team, springt der Ollama-Notnagel an.
OLLAMA_FALLBACK_AFTER = 20  # Sekunden

FEEDBACK_SYSTEM = """Du bist ein Lektor fuer technische Spezifikationen nach
IEC 61508. Du schreibst NIEMALS Inhalt und formulierst NICHTS fuer den Autor um.
Du gibst nur kurze, pruefbare Hinweise zum vorliegenden Text:
- Mehrdeutigkeit ("schnell", "robust", "soll" ohne messbares Kriterium)
- fehlende Pruefbarkeit / fehlendes Akzeptanzkriterium
- Widerspruch zu den mitgegebenen Nachbar-Items
- Vorschlag passender Norm-Klauseln (NUR die Klauselnummer, kein Text)

Antworte AUSSCHLIESSLICH mit JSON, ohne Markdown, in dieser Form:
{"toasts": [{"type":"notice|radio|checkbox|form","severity":"info|warn|conflict",
"message":"...","options":["..."],"fields":[{"name":"...","label":"..."}],
"action":"norm-link|completeness|append-criterion"}]}
options/fields/action nur bei den interaktiven Typen setzen.
Wenn alles in Ordnung ist: {"toasts": []}"""


def _team_online() -> bool:
    """True, wenn zuletzt ein MCP-Team-Token aktiv war (= Reviewer verbunden)."""
    from .models import MCPToken
    since = timezone.now() - timedelta(seconds=TEAM_ONLINE_SECONDS)
    return MCPToken.objects.filter(active=True, last_used__gte=since).exists()


def _ollama_toasts(draft: str, neighbours: list, role_ctx: str) -> list:
    """Notnagel-Hinweise vom lokalen Ollama – in der Persona des V-Schritts."""
    import ollama
    context = "\n".join(f"[{n.get('id')}] {n.get('body','')}" for n in neighbours)
    user_msg = f"Nachbar-Items:\n{context}\n\nZu pruefender Text:\n{draft}"
    messages = [{"role": "system", "content": FEEDBACK_SYSTEM}]
    if role_ctx:
        messages.append({"role": "system", "content": role_ctx})
    messages.append({"role": "user", "content": user_msg})
    try:
        client = ollama.Client(host=settings.OLLAMA_HOST, timeout=settings.OLLAMA_TIMEOUT)
        resp = client.chat(model=settings.OLLAMA_CHAT_MODEL, messages=messages,
                           format="json")
        toasts = json.loads(resp["message"]["content"]).get("toasts", [])
    except Exception:
        toasts = []
    # Notnagel klar kennzeichnen (lokal/unsicher).
    return [{"type": "notice", "severity": "warn",
             "message": "⚠ Lokaler Notnagel (Ollama) – kein Reviewer verbunden. "
                        "Hinweise unsicher, bitte selbst prüfen."}] + toasts


def _role_context(request, item):
    from app import llm_roles
    from app.projects import get_active_project
    return llm_roles.context_for(project=get_active_project(request), item=item)


@login_required
@require_POST
def writing_feedback(request):
    """
    Legt eine Feedback-Anfrage an. Toasts liefert das MCP-Team (in der Persona
    des V-Schritts); ist kein Team verbunden, springt der Ollama-Notnagel an.
    Speichert NIE Inhalt (Toast-Vertrag).
    """
    from .models import FeedbackRequest, FeedbackStatus, WorkItem
    from app.projects import get_active_project

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")

    draft = (payload.get("draft") or "").strip()
    if not draft:
        return JsonResponse({"toasts": [], "request_id": None})

    neighbours = payload.get("neighbours", [])
    project = get_active_project(request)
    item = None
    ident = payload.get("item")
    if ident:
        item = WorkItem.objects.filter(identifier=ident, project=project).first()

    req = FeedbackRequest.objects.create(
        project=project, item=item, draft=draft, neighbours=neighbours)

    if _team_online():
        # Asynchron: das Team holt die Anfrage per MCP und antwortet.
        return JsonResponse({"request_id": req.id, "pending": True,
                             "source": "team", "toasts": []})

    # Notnagel: sofort lokal (Persona des V-Schritts).
    toasts = _ollama_toasts(draft, neighbours, _role_context(request, item))
    req.toasts = toasts
    req.source = "ollama"
    req.status = FeedbackStatus.ANSWERED
    req.answered_by = settings.OLLAMA_CHAT_MODEL
    req.answered_at = timezone.now()
    req.save()
    return JsonResponse({"request_id": req.id, "pending": False,
                         "source": "ollama", "toasts": toasts})


@login_required
def feedback_poll(request):
    """Editor pollt: liefert die Toasts, sobald Team/Ollama geantwortet haben."""
    from .models import FeedbackRequest, FeedbackStatus
    rid = request.GET.get("id")
    req = FeedbackRequest.objects.filter(pk=rid).first()
    if not req:
        return JsonResponse({"ready": True, "toasts": []})
    if req.status == FeedbackStatus.ANSWERED:
        return JsonResponse({"ready": True, "toasts": req.toasts,
                             "source": req.source})
    # Team hat zu lange nicht geantwortet -> Ollama-Notnagel.
    age = (timezone.now() - req.created_at).total_seconds()
    if age >= OLLAMA_FALLBACK_AFTER:
        toasts = _ollama_toasts(req.draft, req.neighbours,
                                _role_context(request, req.item))
        req.toasts = toasts
        req.source = "ollama"
        req.status = FeedbackStatus.ANSWERED
        req.answered_by = settings.OLLAMA_CHAT_MODEL
        req.answered_at = timezone.now()
        req.save()
        return JsonResponse({"ready": True, "toasts": toasts, "source": "ollama"})
    return JsonResponse({"ready": False})


@login_required
@require_POST
def toast_action(request):
    """
    Menschlich angestossener Aktions-Endpoint fuer interaktive Toasts.

    NUR hier wird etwas persistiert -- und zwar ausschliesslich nicht-
    inhaltliche Metadaten: bestaetigte Norm-Bezuege (NormLink, confirmed=True).
    Das LLM schreibt hier nichts; der Mensch hat geklickt.
    """
    from .models import WorkItem, NormClause, NormLink

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")

    action = payload.get("action")
    item_id = payload.get("item")
    values = payload.get("values", {})

    item = WorkItem.objects.filter(identifier=item_id).first()
    if item is None:
        return HttpResponseBadRequest("unknown item")

    if action == "norm-link":
        # values["t-norm-link"] = ["IEC 61508-3 6.4.1", ...] -- vom Menschen gewaehlt.
        confirmed = []
        for raw in values.get("t-norm-link", []):
            standard, _, clause = raw.rpartition(" ")
            if not standard:
                continue
            clause_obj, _ = NormClause.objects.get_or_create(
                standard=standard.strip(), clause=clause.strip(),
                defaults={"text": ""},
            )
            link, _ = NormLink.objects.get_or_create(item=item, clause=clause_obj)
            link.confirmed = True          # menschliche Bestaetigung
            link.save(update_fields=["confirmed"])
            confirmed.append(str(clause_obj))
        return JsonResponse({"ok": True, "confirmed": confirmed})

    # append-criterion / completeness: bewusst NICHT serverseitig in body
    # geschrieben. Der Mensch uebernimmt Inhalt selbst im Editor.
    return JsonResponse({"ok": True, "note": "Kein Inhalt geschrieben (regelkonform)."})
