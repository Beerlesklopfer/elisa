"""
Seiten-Views für ELISA.

Die Oberfläche folgt der IEC 61508 (Leitnorm): die V-Modell-Phasen bilden das
gesamte V-Modell ab – links spezifizierend (REQ→SPEC→ARCH→MOD), rechts
verifizierend (MODTEST/INTTEST/SYSTEST/ACCTEST, Verifikation über `verifies`);
der Normbezug läuft über das RAG auf die IEC-61508-PDFs. Inhalt schreibt immer
der Mensch (CLAUDE.md).
"""
import json
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import WorkItem, Phase, VModelRole, ItemStatus
from . import docgen, lifecycle, llm_roles
from .projects import get_active_project
from .permissions import project_member_required


@login_required
def home(request):
    """Übersicht: Abdeckung, Orphans, Statusverteilung."""
    project = get_active_project(request)
    items = WorkItem.objects.filter(project=project)
    orphans = [i for i in items if i.is_orphan]
    counts = {p.value: items.filter(phase=p.value).count() for p in Phase}
    phase_stats = [
        {"code": p.value, "label": p.label, "count": counts[p.value]}
        for p in Phase
    ]
    # Die 8 Punkte des V-Modells: links die 4 (automatisierten) Spezifikations-
    # ebenen, rechts die 4 Verifikationsebenen als Gegenstücke. Die Stufennamen
    # kommen ausschließlich aus Phase/VModelRole (IEC 61508-3 §7) – eine Quelle.
    PHASE_COLORS = {"REQ": "13,110,253", "SPEC": "25,135,84",
                    "ARCH": "253,126,20", "MOD": "102,16,242"}
    # Verifikations-Gegenstück je linker Ebene (rechte Seite des V):
    VERIFIES = [(Phase.REQUIREMENT, VModelRole.ACCTEST),
                (Phase.SPECIFICATION, VModelRole.SYSTEST),
                (Phase.ARCHITECTURE, VModelRole.INTTEST),
                (Phase.MODULE, VModelRole.MODTEST)]

    def wrap_name(label):
        """Lange Normnamen 2-zeilig: 'Software-' bleibt in Zeile 1."""
        if label.startswith("Software-"):
            return "Software-", label[len("Software-"):]
        return label, ""

    def left_node(phase):
        """Outline = Fortschritt: 0 Items -> outline (noch offen), sonst gefüllt."""
        count = counts[phase.value]
        started = count > 0
        color = PHASE_COLORS[phase.value]
        l1, l2 = wrap_name(phase.label)
        return {
            "code": phase.value, "label": phase.label, "l1": l1, "l2": l2,
            "count": count, "color": color, "started": started,
            "box_fill": f"rgb({color})" if started else "#fff",
            "box_stroke": "none" if started else f"rgb({color})",
            "txt_fill": "#fff" if started else f"rgb({color})",
            "sub_fill": "#fff" if started else "#6c757d",
        }

    def right_node(phase, role):
        l1, l2 = wrap_name(role.label)
        vs = phase.label[len("Software-"):] if phase.label.startswith("Software-") else phase.label
        return {"label": role.label, "l1": l1, "l2": l2, "vs": vs,
                "color": PHASE_COLORS[phase.value]}

    vmodel = {
        "left": [left_node(p) for p, _ in VERIFIES],
        # label = normativer Testname; vs = die Ebene, die er verifiziert.
        "right": [right_node(phase, role) for phase, role in VERIFIES],
    }
    context = {
        "active_tab": "home",
        "phase_stats": phase_stats,
        "vmodel": vmodel,
        "orphans": orphans,
        "total": items.count(),
        "approved": items.filter(status=ItemStatus.APPROVED).count(),
    }
    return render(request, "home.html", context)


@login_required
@project_member_required
def documents(request):
    """Dokumente werden je V-Phase aus den AKTUELLEN Items zusammengesetzt (eine
    Phase = ein vollständiges Dokument, keine Teilabschnitt-Einzeldokumente).
    Es zählt immer der aktuelle Stand jedes Items; frühere Stände (Historie)
    werden verworfen."""
    project = get_active_project(request)
    items = WorkItem.objects.filter(project=project)
    docs = []
    for p in Phase:
        cnt = items.filter(phase=p.value).count()
        if cnt:
            docs.append({"phase": p.value, "label": p.label, "count": cnt})
    return render(request, "documents.html", {
        "active_tab": "documents", "documents": docs, "project": project,
    })


@login_required
@project_member_required
def generate_document(request, phase):
    """Setzt das vollständige Dokument einer V-Phase aus allen aktuellen Items
    zusammen (.docx)."""
    project = get_active_project(request)
    try:
        ph = Phase(phase)
    except ValueError:
        raise Http404("unbekannte Phase")
    items = list(WorkItem.objects.filter(project=project, phase=ph.value)
                 .order_by("identifier"))
    if not items:
        raise Http404("keine Items in dieser Phase")
    out = Path(tempfile.gettempdir()) / f"{project.key}-{ph.value}.docx"
    title = f"{ph.label} — {project.name}"
    try:
        docgen.render_phase_document(items, title, out)
    except FileNotFoundError as exc:
        raise Http404(str(exc))
    return FileResponse(open(out, "rb"), as_attachment=True,
                        filename=f"{ph.label}.docx")


# ── Item-Arbeitsfläche: scrollbares Popup (Text · Referenzen · Normen · Chat) ──

def _item_chat(item):
    """Geteilter Item-Chat (alle Projektbeteiligten + LLM), owner-los."""
    from .models import ChatSession
    s = ChatSession.objects.filter(related_item=item, owner__isnull=True).first()
    if not s:
        s = ChatSession.objects.create(
            related_item=item, owner=None, project=item.project,
            title=f"Item-Chat {item.identifier}")
    return s


def _creator_label(item):
    """Ersteller eines Items – Mensch (created_by) oder, falls vom LLM erzeugt,
    dessen Provenienz (sonst '—')."""
    if item.created_by_id:
        return item.created_by.get_full_name() or item.created_by.get_username()
    if item.generated_by_llm:
        return f"LLM ({item.llm_model})" if item.llm_model else "LLM"
    return "—"


def _local(dt):
    """Lokale Zeit für die Anzeige (konsistent zum Django-`date`-Filter im Template).
    Der ROHE (UTC-)Wert wird separat für den Vergleich genutzt – hier nur Anzeige."""
    from django.utils import timezone
    return timezone.localtime(dt) if timezone.is_aware(dt) else dt


def _item_history(item):
    """Vereinte, absteigend sortierte Item-Historie (Änderungen + Statuswechsel)."""
    from .models import WorkItemHistory
    hist = []
    for h in item.history.all():
        det = (f"{h.field}: „{h.old_value}“ → „{h.new_value}“" if h.field
               else (h.note or h.get_kind_display()))
        # Ersteller-Eintrag (CREATED) ohne `by`: auf die Provenienz zurückfallen.
        if h.by_id:
            who = h.by.get_username()
        elif h.kind == WorkItemHistory.Kind.CREATED:
            who = _creator_label(item)
        else:
            who = "—"
        hist.append((h.at, f"{_local(h.at):%d.%m.%y %H:%M} · {h.get_kind_display()} · {who}", det))
    for e in item.lifecycle_events.all():
        who = e.by.get_username() if e.by_id else "—"
        hist.append((e.at, f"{_local(e.at):%d.%m.%y %H:%M} · Status {e.from_state or '—'}→{e.to_state} · {who}",
                     e.note or f"Iteration {e.iteration}"))
    hist.sort(key=lambda x: x[0], reverse=True)
    return [{"label": l, "detail": d, "at": t.isoformat()} for t, l, d in hist]


_VERSIONED = ["title", "body", "rationale", "identifier", "phase"]


def _state_at(item, when):
    """Rekonstruiert den Item-Zustand zu einem Zeitpunkt aus der append-only
    Feld-Historie (alt→neu). Liefert {feld: wert} – der Nachweisstand „damals"."""
    hist = list(item.history.all())   # nach -at (neu → alt)
    state = {}
    for f in _VERSIONED:
        changes = [h for h in hist if h.field == f]
        applied = next((h for h in changes if h.at <= when), None)
        if applied:
            state[f] = applied.new_value          # letzter Stand ≤ Zeitpunkt
        elif changes:
            state[f] = changes[-1].old_value      # Urwert vor erster Änderung
        else:
            state[f] = getattr(item, f)           # nie geändert → aktueller Wert
    ev = next((e for e in sorted(item.lifecycle_events.all(),
                                 key=lambda x: x.at, reverse=True) if e.at <= when), None)
    state["status"] = ev.to_state if ev else item.status
    return state


def _entry_meta_at(item, when):
    """Person/Art des Historieneintrags genau zu `when` (für die Banner-Zeile)."""
    from .models import WorkItemHistory
    for h in item.history.all():
        if h.at == when:
            if h.by_id:
                who = h.by.get_username()
            elif h.kind == WorkItemHistory.Kind.CREATED:
                who = _creator_label(item)
            else:
                who = "—"
            return (who, h.get_kind_display())
    for e in item.lifecycle_events.all():
        if e.at == when:
            return (e.by.get_username() if e.by_id else "—",
                    f"Status {e.from_state or '—'}→{e.to_state}")
    return ("—", "")


def can_edit_req(user, project):
    """Planänderung: Admin (Staff/Superuser) und Projektleitung (PM) dürfen
    Anforderungen (REQ) DIREKT ändern. Alle anderen Rollen/das LLM: REQ ändern
    sich nur über reimport_requirements."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    from .models import ProjectMembership, Role
    return ProjectMembership.objects.filter(
        project=project, user=user, role=Role.PROJECT_MANAGER).exists()


def _render_text(request, item, at=None, status_error="", notice="", translation=None,
                 translation_pending=None):
    from django.utils.dateparse import parse_datetime
    historical = None
    when = parse_datetime(at) if at else None
    if when:
        state = _state_at(item, when)
        who, kind = _entry_meta_at(item, when)
        try:
            status_disp = ItemStatus(state["status"]).label
        except ValueError:
            status_disp = state["status"]
        historical = {"at_iso": when.isoformat(), "when": when, "who": who,
                      "kind": kind, "state": state, "status_display": status_disp}
    refs_up = list(item.derived_from.all())
    refs_down = list(item.refined_to.all())
    related = list(item.related.all())
    blocks_out = list(item.blocks.all())
    blocked_by = list(item.blocked_by.all())
    verifies = list(item.verifies.all())          # rechts: was DIESES Test-Item prüft
    verified_by = list(item.verified_by.all())    # links: prüfende Test-Items
    norms = list(item.norm_links.select_related("clause").all())
    # Anforderungen (REQ) ändern sich grundsätzlich nur über den Reimport –
    # AUSSER für Admin/PM (Planänderung), die REQ direkt bearbeiten dürfen.
    is_req = item.phase == Phase.REQUIREMENT
    req_locked = is_req and not can_edit_req(request.user, item.project)
    # Edit-Recht (Bearbeiten-Button UND Referenz-„+"/„×" hängen daran):
    # REQ → nur Admin/PM; SPEC/ARCH/MOD → change_workitem-Recht; nie historisch.
    _can_edit = (not historical and (
        can_edit_req(request.user, item.project) if is_req
        else request.user.has_perm("app.change_workitem")))
    # Übersetzen: Sprachmenü schaltet die Anzeige um. In einer SEKUNDÄRSPRACHE
    # (≠ Primärsprache, im Projekt vorhanden) bekommt das Item den „Übersetzen"-
    # Button — ABER nie in eine NORMATIVE Sprache (Wortlaut ist maßgeblich).
    from . import languages as langs
    _active_lang = request.session.get("lang") or item.project.primary_language
    _is_secondary = (bool(_active_lang) and _active_lang != item.project.primary_language
                     and _active_lang in (item.project.languages or []))
    translate_lang = _active_lang if (_is_secondary and not historical
                                      and not item.project.is_normative(_active_lang)) else ""
    translate_blocked = _active_lang if (_is_secondary and item.project.is_normative(_active_lang)) else ""
    # Freigabe-Workflow (ab SPEC): erlaubte Folgezustände. REQ-Status bleibt vom
    # Reimport gesetzt (APPROVED) – hier kein Statuswechsel.
    next_states = []
    if not historical and not is_req:
        next_states = [(c, ItemStatus(c).label) for c in lifecycle.next_states_for(item)]
    # Referenz-Gruppen für die UI (Traceability + Querverweise + Blocker).
    ref_groups = [
        {"label": "Leitet sich ab aus (oben)", "icon": "fa-arrow-up", "dir": "up", "items": refs_up},
        {"label": "Verfeinert zu (unten)", "icon": "fa-arrow-down", "dir": "down", "items": refs_down},
        {"label": "Querverweise ↔", "icon": "fa-arrows-left-right", "dir": "related", "items": related},
        {"label": "Blockiert →", "icon": "fa-ban", "dir": "blocks", "items": blocks_out},
        {"label": "Wartet auf / blockiert von ←", "icon": "fa-hourglass-half", "dir": "blocked_by", "items": blocked_by},
        {"label": "Verifiziert (rechte Seite)", "icon": "fa-circle-check", "dir": "verifies", "items": verifies},
        {"label": "Verifiziert durch (Tests)", "icon": "fa-vial-circle-check", "dir": "verified_by", "items": verified_by},
    ]
    # Markdown-Rendering der Bodies (bes. hilfreich für REQ).
    from . import markdown_render, norm_refs
    _ref_ids = set(item.project.work_items.values_list("identifier", flat=True))
    body_html = _link_item_refs(markdown_render.render(item.body), _ref_ids)
    hist_body_html = _link_item_refs(
        markdown_render.render(historical["state"]["body"]), _ref_ids) if historical else ""
    # Body nur zeigen, wenn er vom Titel abweicht (sonst sinnlose Wiederholung).
    _bt = (item.body or "").strip()
    show_body = bool(_bt) and _bt != (item.title or "").strip()
    # ── Mehrsprachigkeit: in einer SEKUNDÄRSPRACHE zeigt das Item seinen Inhalt IN
    # dieser Sprache (informativ, ERSETZT den Primär-Body); fehlt die Übersetzung,
    # wird sie automatisch angestoßen → folgt der Sprachwahl.
    showing_lang = ""
    if translate_lang and not historical:
        from .models import ItemTranslation
        tr = ItemTranslation.objects.filter(work_item=item, lang=translate_lang).first()
        if tr and tr.status == ItemTranslation.Status.DONE and (tr.text or "").strip():
            body_html = _link_item_refs(markdown_render.render(tr.text), _ref_ids)
            showing_lang = translate_lang
        elif tr and tr.status in (ItemTranslation.Status.PENDING,
                                  ItemTranslation.Status.RUNNING):
            translation_pending = translate_lang
        elif tr is None and _bt:
            ItemTranslation.objects.create(work_item=item, lang=translate_lang,
                                           status=ItemTranslation.Status.PENDING)
            translation_pending = translate_lang
    show_hist_body = False
    if historical:
        _hb = (historical["state"]["body"] or "").strip()
        show_hist_body = bool(_hb) and _hb != (historical["state"]["title"] or "").strip()
    # Zitierte Normen/Regelwerke aus dem Text erkennen (+ Direktlink, falls vorhanden).
    cited_norms = norm_refs.cited_norms(historical["state"]["body"] if historical else item.body)
    # Informative Übersetzung (Dragoman) – nie normativ.
    translation_html, translation_name = "", ""
    if translation:
        _tlang, _ttext = translation
        translation_html = markdown_render.render(_ttext)
        translation_name = langs.name(_tlang)
    return render(request, "partials/item_text.html", {
        "item": item, "refs_up": refs_up, "refs_down": refs_down,
        "related": related, "blocks_out": blocks_out, "blocked_by": blocked_by,
        "ref_groups": ref_groups,
        "refs_count": (len(refs_up) + len(refs_down) + len(related)
                       + len(blocks_out) + len(blocked_by)
                       + len(verifies) + len(verified_by)), "norms": norms,
        "body_html": body_html, "hist_body_html": hist_body_html,
        "show_body": show_body, "show_hist_body": show_hist_body,
        "cited_norms": cited_norms,
        "history": _item_history(item), "historical": historical,
        "req_locked": req_locked, "is_req": is_req, "next_states": next_states,
        "status_error": status_error,
        "edit_data": {"identifier": item.identifier,
                      "title": item.title or "", "body": item.body or "",
                      "rationale": item.rationale or ""},
        "translate_lang": translate_lang,
        "translate_lang_name": langs.name(translate_lang) if translate_lang else "",
        "translate_blocked_name": langs.name(translate_blocked) if translate_blocked else "",
        "translation_html": translation_html, "translation_name": translation_name,
        "translation_pending": translation_pending,
        "translation_pending_name": langs.name(translation_pending) if translation_pending else "",
        "showing_lang": showing_lang,
        "showing_lang_name": langs.name(showing_lang) if showing_lang else "",
        # Anhang (Abbildungen/Tabellen) am Dokumentende. table_html ist autoren-/
        # MCP-geliefert → über markdown_render bleach-sanitisiert (kein rohes |safe).
        "exhibits": [] if historical else [
            {"kind": ex.kind, "label": ex.label, "number": ex.number,
             "caption": ex.caption, "attribution": ex.attribution,
             "data_uri": ex.data_uri,
             "table_html": markdown_render.render(ex.table_html) if ex.table_html else ""}
            for ex in item.exhibits.all()],
        "can_delete_rev": (not historical and can_edit_req(request.user, item.project)
                           and item.history.filter(kind="EDITED").exists()),
        "notice": notice,
        "can_approve": request.user.has_perm("app.approve_workitem"),
        "can_audit": request.user.has_perm("app.audit_workitem"),
        "audit_down_name": (ItemStatus(lifecycle.audit_step_down_target(item)).label
                            if lifecycle.audit_step_down_target(item) else ""),
        "can_edit": _can_edit,
        # Kreuzreferenzen folgen exakt der Edit-Berechtigung (bei REQ: nur Admin/PM).
        "can_ref": _can_edit,
    })


def _render_chat_pane(request, item):
    from .participants import chat_participants, slug_handle
    from .models import ChatRole
    import re
    chat = _item_chat(item)
    me = slug_handle(request.user.first_name) or slug_handle(request.user.username)
    parts = chat_participants(item.project)
    msgs = list(chat.messages.all())
    # „tippt…": ist die LETZTE Nachricht ein @-Mention an ein LLM, dann wird gerade
    # geantwortet → Tipp-Welle anzeigen, bis die Antwort kommt.
    awaiting = []
    if msgs and msgs[-1].role == ChatRole.USER:
        mentioned = set(re.findall(r"@([\w\-äöüß]+)", (msgs[-1].content or "").lower()))
        llm = {p["handle"] for p in parts if p.get("kind") == "llm"}
        awaiting = sorted(mentioned & llm)
    active_llm = "@ollama" if chat.messages.filter(
        role=ChatRole.ASSISTANT, author_label="@ollama").exists() else ""
    return render(request, "partials/item_chat.html", {
        "item": item, "chat_messages": msgs, "participants": parts,
        "mention_token": f"@{me}" if me else "", "active_llm": active_llm,
        "awaiting": awaiting,
    })


@login_required
@project_member_required
def online_presence(request):
    """who-is-online: JSON {handle: online?} für das aktive Projekt (Poll-Ziel
    aller Chat-Systeme)."""
    from django.http import JsonResponse
    from .participants import chat_participants
    data = {p["handle"]: p["online"] for p in chat_participants(get_active_project(request))}
    return JsonResponse(data)


# ── 3-Spalten-Arbeitsbereich: Baum | Text | Chat ───────────────────────────

def _natkey(s):
    """Natürliche Sortierung über die Identifier-Segmente (S4.10 nach S4.2)."""
    return [t.zfill(8) if t.isdigit() else t for t in s.split(".")]


def _item_tree(phase_items):
    """Schachtelt Items REKURSIV nach den Punkt-Segmenten des Identifiers
    (S4 › S4.1 › S4.1.1). Ein Knoten kann ein eigenes Item UND Kinder haben;
    Zwischenstufen ohne eigenes Item (z. B. „S4") werden als Ordner erzeugt."""
    nodes, top = {}, {}

    def node(prefix):
        n = nodes.get(prefix)
        if n is None:
            n = {"key": prefix, "item": None, "_ch": {}}
            nodes[prefix] = n
        return n

    for it in phase_items:
        parts = it.identifier.split(".")
        for d in range(len(parts)):
            prefix = ".".join(parts[:d + 1])
            n = node(prefix)
            if d == 0:
                top.setdefault(prefix, n)
            else:
                nodes[".".join(parts[:d])]["_ch"].setdefault(prefix, n)
        nodes[it.identifier]["item"] = it

    def finalize(n):
        children = [finalize(c) for _, c in
                    sorted(n["_ch"].items(), key=lambda kv: _natkey(kv[0]))]
        count = (1 if n["item"] else 0) + sum(c["count"] for c in children)
        return {"key": n["key"], "item": n["item"], "children": children, "count": count}

    return [finalize(n) for _, n in sorted(top.items(), key=lambda kv: _natkey(kv[0]))]


def _link_item_refs(html, identifiers):
    """Verlinkt im gerenderten Body die Identifier EXISTIERENDER Items (z. B.
    S4.2.3 → klickbar). Nur echte Treffer (keine Falschpositiven wie „IP40"),
    nicht innerhalb bestehender <a>-Links/Tags. Läuft NACH bleach."""
    import re
    ids = [i for i in identifiers if i]
    if not ids:
        return html
    ids.sort(key=len, reverse=True)        # längste zuerst: S4.1.1 vor S4.1
    pat = re.compile(r"\b(" + "|".join(re.escape(i) for i in ids) + r")\b")
    out, in_a = [], False
    for p in re.split(r"(<[^>]+>)", html):
        if p[:1] == "<":
            low = p.lower()
            if low.startswith("<a"):
                in_a = True
            elif low.startswith("</a"):
                in_a = False
            out.append(p)
        elif in_a:
            out.append(p)
        else:
            out.append(pat.sub(
                r'<a href="#" class="item-ref" data-ref="\1">\1</a>', p))
    return "".join(out)


@login_required
@project_member_required
def workspace(request):
    """Explorer-artiger Arbeitsbereich über alle 8 V-Modell-Stufen. Oben Stufen-
    Buttons (links spezifizierend, rechts verifizierend); nur bei „Alle" erscheinen
    die Stufen als Ordner im Baum, sonst nur die Items der gewählten Stufe.
    `?sel=<identifier>` wählt ein Item vor (für Sprünge aus anderen Ansichten)."""
    project = get_active_project(request)
    current = request.GET.get("phase", "all")
    # Vorauswahl: explizit per ?sel=, sonst das in der Session getaggte Item
    # (bleibt so über die Sprachumschaltung hinweg geöffnet).
    sel = request.GET.get("sel") or request.session.get("current_item", "")
    items = list(WorkItem.objects.filter(project=project).order_by("identifier"))
    # Alle 8 V-Modell-Punkte: links die 4 spezifizierenden (= WorkItem-Phasen),
    # rechts die 4 verifizierenden (Modul-/Integrations-/System-/Abnahmetest).
    left = {p.value for p in Phase}
    # Farben wie in der Übersicht: je V-Stufe eine Farbe; die rechte (verifizierende)
    # Seite spiegelt ihren linken Partner (MODTEST↔MOD, INTTEST↔ARCH, SYSTEST↔SPEC,
    # ACCTEST↔REQ).
    _STAGE_COLORS = {"REQ": "13,110,253", "SPEC": "25,135,84", "ARCH": "253,126,20",
                     "MOD": "102,16,242", "MODTEST": "102,16,242", "INTTEST": "253,126,20",
                     "SYSTEST": "25,135,84", "ACCTEST": "13,110,253"}
    stages = [{"value": r.value, "label": r.label,
               "side": "left" if r.value in left else "right",
               "color": _STAGE_COLORS.get(r.value, "108,117,125"),
               "count": sum(1 for i in items if i.phase == r.value)} for r in VModelRole]
    valid = {s["value"] for s in stages}
    if current != "all" and current not in valid:
        current = "all"

    def grp(value, label, side):
        phase_items = [i for i in items if i.phase == value]
        # Volle Gliederung: rekursive Schachtelung nach allen Identifier-Segmenten
        # (S4 › S4.1 › S4.1.1), nicht nur die erste Stufe.
        tree = _item_tree(phase_items) if any("." in i.identifier
                                              for i in phase_items) else None
        return {"phase": value, "label": label, "side": side,
                "items": phase_items, "tree": tree}

    if current == "all":
        groups = [grp(s["value"], s["label"], s["side"]) for s in stages]
    else:
        s = next(s for s in stages if s["value"] == current)
        groups = [grp(s["value"], s["label"], s["side"])]
    all_items = [{"id": i.identifier, "title": i.title, "phase": i.phase}
                 for i in items]
    # Rechte (verifizierende) Stufen INVERS, damit jede Teststufe senkrecht unter
    # ihrem Entwicklungspartner steht (REQ↔ACCTEST … MOD↔MODTEST).
    right_stages = [s for s in stages if s["side"] == "right"][::-1]
    return render(request, "workspace.html", {
        "active_tab": "workspace", "project": project,
        "stages": stages, "right_stages": right_stages,
        "current_phase": current, "sel": sel,
        "groups": groups, "show_folders": current == "all",
        "all_items_json": json.dumps(all_items),
    })


@login_required
@project_member_required
def workitem_text(request, identifier):
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    # Aktuelles Item in der Session taggen → bleibt bei Sprachumschaltung gewählt.
    request.session["current_item"] = item.identifier
    # REQ ändern sich normalerweise nur über den Reimport – AUSSER Admin/PM
    # (Planänderung) dürfen sie direkt bearbeiten; SPEC/ARCH/MOD wie gehabt.
    is_req = item.phase == Phase.REQUIREMENT
    may_save = (can_edit_req(request.user, item.project) if is_req
                else request.user.has_perm("app.change_workitem"))
    if request.method == "POST" and may_save:
        from . import history as hist_mod
        before = hist_mod.snapshot(item)
        item.title = request.POST.get("title", item.title)
        item.body = request.POST.get("body", item.body)
        item.rationale = request.POST.get("rationale", item.rationale)
        item.save()
        hist_mod.record_changes(item, before, by=request.user,
                                note="REQ direkt geändert (Admin/PM)" if is_req
                                else "Bearbeitung im Arbeitsbereich")
    return _render_text(request, item, at=request.GET.get("at"))


@login_required
@project_member_required
def workitem_revision_delete(request, identifier):
    """Admin/PM dürfen die AKTUELLE (jüngste) Inhalts-Revision löschen → Rollback
    auf den vorigen Stand. Sicherheitsabfrage erfolgt im Frontend."""
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    if not can_edit_req(request.user, item.project):
        return _render_text(request, item,
                            status_error="Nur Admin/PM dürfen die Revision löschen.")
    if request.method == "POST":
        from . import history as hist_mod
        if hist_mod.delete_current_revision(item, by=request.user):
            return _render_text(request, item,
                                notice="Aktuelle Revision gelöscht – auf den vorigen Stand zurückgerollt.")
        return _render_text(request, item, notice="Keine löschbare Inhalts-Revision vorhanden.")
    return _render_text(request, item)


@login_required
@project_member_required
def workitem_add(request):
    """Worktree-Gliederung: neues Item auf GLEICHER Ebene (mode=sibling) ODER als
    SUBITEM (mode=child), automatisch nummeriert relativ zu `ref`. Nur SPEC/ARCH/MOD
    (REQ entstehen über den Reimport). DRAFT, vom Menschen angelegt."""
    if request.method != "POST":
        return JsonResponse({"error": "POST erwartet"}, status=405)
    project = get_active_project(request)
    ref = (request.POST.get("ref") or "").strip()
    mode = request.POST.get("mode", "child")
    if mode not in ("child", "sibling"):
        mode = "child"
    from . import outline
    title = (request.POST.get("title") or "").strip()
    if not ref:
        # Leeres Projekt / leere Stufe → erstes Top-Level-Item der Phase.
        phase = (request.POST.get("phase") or "").upper()
        # Alle V-Ebenen anlegbar AUSSER REQ (Anforderungen kommen über den Reimport).
        if phase == Phase.REQUIREMENT or phase not in Phase.values:
            return JsonResponse(
                {"error": "Erstes Item für jede Ebene außer REQ (REQ über Reimport)."}, status=400)
        if not request.user.has_perm("app.add_workitem"):
            return JsonResponse({"error": "Keine Berechtigung zum Anlegen."}, status=403)
        derived = None
    else:
        phase, derived = outline.resolve_ref(project, ref)
        if phase is None:
            return JsonResponse({"error": f"Referenz {ref} nicht gefunden."}, status=404)
        if phase == Phase.REQUIREMENT:
            return JsonResponse(
                {"error": "Anforderungen (REQ) entstehen nur über den Reimport."}, status=400)
        if not request.user.has_perm("app.add_workitem"):
            return JsonResponse({"error": "Keine Berechtigung zum Anlegen."}, status=403)

    # Atomar: schlägt etwas NACH dem create() fehl, wird das halbe Item zurückgerollt
    # (kein Geister-Item). Und JEDER Fehler kommt als JSON zurück – nie als HTML-500,
    # sonst scheitert das Frontend an JSON.parse.
    import logging
    from django.db import transaction
    try:
        with transaction.atomic():
            if not ref:
                new = outline.create_top_item(project, phase, title=title, by=request.user)
            else:
                new = outline.create_outline_item(
                    project, ref, mode, phase, title=title, by=request.user, derived=derived)
    except Exception as exc:                       # pragma: no cover – Diagnose ins Log
        logging.getLogger("app").exception("workitem_add fehlgeschlagen (ref=%r mode=%r)", ref, mode)
        return JsonResponse({"error": f"Anlegen fehlgeschlagen: {exc}"}, status=500)
    return JsonResponse({"identifier": new.identifier, "phase": new.phase})


@login_required
@project_member_required
def workitem_editor(request, identifier):
    """Eigenständige Editor-SEITE – wird als abdockbares Fenster (window.open)
    geöffnet und ist damit frei über mehrere Monitore verschiebbar. WYSIWYG-
    Markdown-Editor (Mermaid-fähig) für Titel/Body/Begründung; speichert per POST
    an workitem-text (gleiche menschliche Freigabe-/Historie-Regeln)."""
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    is_req = item.phase == Phase.REQUIREMENT
    may_save = (can_edit_req(request.user, item.project) if is_req
                else request.user.has_perm("app.change_workitem"))
    return render(request, "editor_popup.html", {"item": item, "may_save": may_save})


@login_required
@project_member_required
def workitem_chat_pane(request, identifier):
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    if request.method == "POST":
        msg = (request.POST.get("message") or "").strip()
        if msg:
            from .models import ChatMessage, ChatRole
            ChatMessage.objects.create(session=_item_chat(item),
                                       role=ChatRole.USER, content=msg,
                                       author=request.user)
            # LLM-Antworten liefert der MCP-Worker (Persona/Provider je WorkerBackend),
            # der die @-Erwähnung über den MCP-/SSE-Kanal abholt — kein synchroner Ollama.
    return _render_chat_pane(request, item)


@login_required
@project_member_required
def workitem_status(request, identifier):
    """Status-Übergang im Freigabe-Workflow (ab SPEC: Autor → Review → Freigabe).
    Drei-Personen-Regel + Reihenfolge erzwingt lifecycle.transition; REQ ist
    ausgenommen (reimport-verwaltet, per Default APPROVED)."""
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    err = ""
    if request.method == "POST" and item.phase != Phase.REQUIREMENT:
        new = request.POST.get("status", "")
        if new == ItemStatus.APPROVED and not request.user.has_perm("app.approve_workitem"):
            err = "Nur Projektleitung/FSM dürfen freigeben (APPROVED)."
        else:
            try:
                lifecycle.transition(item, new, request.user,
                                     note=request.POST.get("note", ""))
            except lifecycle.TransitionError as exc:
                err = str(exc)
    return _render_text(request, item, status_error=err)


@login_required
@project_member_required
def workitem_audit(request, identifier):
    """Audit-Rückstufung (TÜV/Kunde/Sub): GENAU EINE Stufe herunter, mit Finding-
    Notiz. Nur mit audit_workitem-Recht; Freigabe nach oben bleibt menschlich."""
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    err = ""
    if request.method == "POST":
        if not request.user.has_perm("app.audit_workitem"):
            err = "Kein Audit-Recht (nur Auditor/Projektleitung)."
        else:
            try:
                lifecycle.audit_downgrade(item, request.user,
                                          note=request.POST.get("note", ""))
            except lifecycle.TransitionError as exc:
                err = str(exc)
    return _render_text(request, item, status_error=err)


@login_required
@project_member_required
def workitem_ref(request, identifier):
    """Kreuzreferenzen pflegen (M2M): direction = up (leitet sich ab aus / setzt
    derived_from), down (verfeinert zu / setzt derived_from des Ziels), related
    (symmetrischer Querverweis). op = add|remove. Recht = wie Bearbeiten
    (REQ: nur Admin/PM; sonst change_workitem)."""
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    may_ref = (can_edit_req(request.user, item.project)
               if item.phase == Phase.REQUIREMENT
               else request.user.has_perm("app.change_workitem"))
    if request.method == "POST" and may_ref:
        target = WorkItem.objects.filter(
            project=item.project,
            identifier=(request.POST.get("target") or "").strip()).first()
        direction = request.POST.get("direction")
        op = request.POST.get("op", "add")
        if target and target.pk != item.pk:
            rel = {"up": item.derived_from, "down": target.derived_from,
                   "related": item.related, "blocks": item.blocks,
                   "blocked_by": target.blocks,
                   "verifies": item.verifies,        # self (Test) verifiziert target
                   "verified_by": target.verifies,   # target (Test) verifiziert self
                   }.get(direction)
            tgt = item if direction in ("down", "blocked_by", "verified_by") else target
            if rel is not None:
                (rel.remove if op == "remove" else rel.add)(tgt)
    return _render_text(request, item)


@login_required
@project_member_required
def workitem_translate(request, identifier):
    """„Übersetzen"-Button: Ziel = aktive Anzeige-Sprache (Sprachmenü). GUARD:
    in eine NORMATIVE Sprache wird NIE übersetzt (der Wortlaut ist maßgeblich) →
    Fehlermeldung. Das automatische Übersetzungs-Werkzeug folgt separat; die
    Sperre greift aber schon hier. (Chats sind sprachagnostisch, hier nicht relevant.)"""
    from . import languages as langs
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    target = request.session.get("lang") or item.project.primary_language
    if (not target or target == item.project.primary_language
            or target not in (item.project.languages or [])):
        notice = "Keine Sekundärsprache aktiv — oben im Sprachmenü eine Zielsprache wählen."
    elif item.project.is_normative(target):
        notice = (f"⛔ Übersetzung nach {langs.name(target)} unzulässig: normative "
                  "Sprache — der Wortlaut ist maßgeblich und wird nie übersetzt.")
    else:
        # ASYNC über MCP: nur PENDING anlegen. Der Dragoman-Worker holt die Aufgabe
        # per MCP (next_translation_task), fragt sein LLM und schreibt das Ergebnis
        # per complete_translation zurück. Die UI pollt.
        from .models import ItemTranslation
        ItemTranslation.objects.update_or_create(
            work_item=item, lang=target,
            defaults={"status": ItemTranslation.Status.PENDING, "text": ""})
        return _render_text(request, item, translation_pending=target)
    return _render_text(request, item, notice=notice)


def _start_translation(item_pk, lang):
    """Übersetzt im HINTERGRUND-Thread (CPU-Ollama ist langsam → kein Request-
    Timeout). Schreibt das Ergebnis in die ItemTranslation."""
    import threading

    def run():
        from django.db import connection
        from .models import WorkItem, ItemTranslation
        from . import translate as _tr, languages as _L
        try:
            it = WorkItem.objects.get(pk=item_pk)
            ok, result = _tr.translate_text(it.body, _L.name(lang))
            ItemTranslation.objects.filter(work_item_id=item_pk, lang=lang).update(
                status=(ItemTranslation.Status.DONE if ok else ItemTranslation.Status.ERROR),
                text=result)
        except Exception as exc:
            ItemTranslation.objects.filter(work_item_id=item_pk, lang=lang).update(
                status=ItemTranslation.Status.ERROR, text=str(exc))
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True).start()


@login_required
@project_member_required
def workitem_translation_poll(request, identifier):
    """Poll-Endpoint für die Async-Übersetzung. Liefert Status + (bei DONE) das
    gerenderte, informativ markierte Übersetzungs-HTML."""
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from .models import ItemTranslation
    from . import markdown_render, languages as _L
    item = get_object_or_404(WorkItem, identifier=identifier,
                             project=get_active_project(request))
    lang = (request.GET.get("lang") or "").strip()
    tr = ItemTranslation.objects.filter(work_item=item, lang=lang).first()
    if not tr:
        return JsonResponse({"status": "NONE"})
    html = ""
    if tr.status == ItemTranslation.Status.DONE:
        body = _link_item_refs(markdown_render.render(tr.text),
                               set(item.project.work_items.values_list("identifier", flat=True)))
        html = render_to_string("partials/item_translation.html",
                                {"translation_html": body,
                                 "translation_name": _L.name(lang)})
    elif tr.status == ItemTranslation.Status.ERROR:
        html = f'<div class="alert alert-warning small">⚠ {tr.text}</div>'
    return JsonResponse({"status": tr.status, "html": html})
