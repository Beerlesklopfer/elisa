"""
Iterativer Lebenszyklus (gemeinsam für WorkItem und ProjectDocument).

Zustände: Entwurf (DRAFT) → In Prüfung (PROPOSED) → Überarbeitung (REWORK ↺)
→ Freigegeben (APPROVED) → bei Änderung neue Revision → Entwurf;  + Überholt.

Jeder Übergang wird als LifecycleEvent protokolliert (Nachweis nach IEC 61508).
Beim Wiederöffnen eines freigegebenen Objekts (APPROVED → DRAFT/REWORK) wird der
Iterations-/Versionszähler hochgezählt (neue Revision).
"""
from django.utils import timezone

from app.models import ItemStatus, LifecycleEvent, WorkItem, ProjectDocument, Phase

# STRIKTE Reihenfolge – es darf NICHTS übersprungen werden. Klassischer Fluss
# (REQ + ProjectDocument): Entwurf → In Prüfung → (Überarbeitung ↺) → Freigegeben.
ALLOWED = {
    ItemStatus.DRAFT:    {ItemStatus.PROPOSED},                     # nur weiter zur Prüfung
    ItemStatus.PROPOSED: {ItemStatus.REWORK, ItemStatus.APPROVED},  # Prüfung: zurück oder frei
    ItemStatus.REWORK:   {ItemStatus.PROPOSED},                     # nach Überarb. ZWINGEND re-prüfen
    ItemStatus.APPROVED: {ItemStatus.DRAFT, ItemStatus.OBSOLETE, ItemStatus.SIGNED},
    ItemStatus.SIGNED:   {ItemStatus.DRAFT, ItemStatus.OBSOLETE},
    ItemStatus.OBSOLETE: set(),                                     # terminal
}

# Ab SPEC (WorkItem ≠ REQ): zusätzlicher REVIEW-Schritt vor der Freigabe –
# Autor → Review (zweite Person) → Freigabe (dritte Person). Vier-/Sechs-Augen
# nach IEC 61508 (Unabhängigkeit). Drei verschiedene Personen erzwungen.
ALLOWED_SPEC = {
    ItemStatus.DRAFT:    {ItemStatus.PROPOSED},
    ItemStatus.PROPOSED: {ItemStatus.REWORK, ItemStatus.REVIEWED},  # → Review (2. Person)
    ItemStatus.REWORK:   {ItemStatus.PROPOSED},
    ItemStatus.REVIEWED: {ItemStatus.REWORK, ItemStatus.APPROVED},  # → Freigabe (3. Person)
    ItemStatus.APPROVED: {ItemStatus.DRAFT, ItemStatus.OBSOLETE, ItemStatus.SIGNED},
    ItemStatus.SIGNED:   {ItemStatus.DRAFT, ItemStatus.OBSOLETE},
    ItemStatus.OBSOLETE: set(),
}


def _map_for(obj):
    """SPEC/ARCH/MOD-WorkItems nutzen den Review-Fluss; REQ + Dokumente klassisch."""
    if isinstance(obj, WorkItem) and obj.phase != Phase.REQUIREMENT:
        return ALLOWED_SPEC
    return ALLOWED


def next_states_for(obj):
    """Erlaubte Folgezustände für DIESES Objekt (Review-Fluss ab SPEC)."""
    return sorted(_map_for(obj).get(obj.status, set()))

# Wiederöffnen aus 'Freigegeben'/'Signiert' startet eine neue Revision (Zähler +1).
REOPEN = {ItemStatus.DRAFT}
# Übergänge IN/AUS diesem Zustand sind admin-pflichtig (eingefroren).
ADMIN_ONLY_STATES = {ItemStatus.SIGNED}


def can_transition(frm: str, to: str) -> bool:
    return to in ALLOWED.get(frm, set())


def next_states(frm: str):
    """Erlaubte Folgezustände (für UI – nur diese dürfen angeboten werden)."""
    return sorted(ALLOWED.get(frm, set()))


def counter_field(obj) -> str:
    return "version" if isinstance(obj, WorkItem) else "iteration"


class TransitionError(ValueError):
    """Unerlaubter Zustandsübergang (Reihenfolge verletzt / übersprungen)."""


def transition(obj, to_state: str, user=None, note: str = ""):
    """
    Führt einen Zustandsübergang aus, protokolliert ihn, liefert das Event.
    Erzwingt die strikte Reihenfolge – Überspringen wirft TransitionError.
    """
    frm = obj.status
    if to_state == frm:
        return None
    if to_state not in _map_for(obj).get(frm, set()):
        raise TransitionError(
            f"Übergang {frm} → {to_state} nicht erlaubt – die Reihenfolge "
            f"darf nicht übersprungen werden.")
    # Eingefroren: nur Admins dürfen IN oder AUS einem signierten Zustand.
    if (frm in ADMIN_ONLY_STATES or to_state in ADMIN_ONLY_STATES) \
            and not (user and user.is_staff):
        raise TransitionError(
            "Signierte/eingefrorene Dokumente darf nur ein Admin (de)signieren.")

    # Drei-Personen-Freigabe ab SPEC: Autor ≠ Reviewer ≠ Freigeber (IEC 61508).
    spec_wi = isinstance(obj, WorkItem) and obj.phase != Phase.REQUIREMENT
    if spec_wi and user:
        if to_state == ItemStatus.REVIEWED and obj.created_by_id == user.id:
            raise TransitionError(
                "Das Review muss durch eine ANDERE Person als den Autor erfolgen.")
        if to_state == ItemStatus.APPROVED:
            if obj.created_by_id == user.id:
                raise TransitionError("Die Freigabe darf nicht durch den Autor erfolgen.")
            if obj.reviewed_by_id == user.id:
                raise TransitionError(
                    "Die Freigabe muss durch eine DRITTE Person erfolgen (nicht den Reviewer).")

    cfield = counter_field(obj)
    # Wiederöffnen aus 'Freigegeben'/'Signiert' = neue Revision/Iteration.
    if frm in (ItemStatus.APPROVED, ItemStatus.SIGNED) and to_state in REOPEN:
        setattr(obj, cfield, getattr(obj, cfield, 1) + 1)
        if isinstance(obj, WorkItem):
            obj.approved_by = None
            obj.reviewed_by = None                # Review verfällt mit neuer Revision
    obj.status = to_state
    if to_state == ItemStatus.REVIEWED and isinstance(obj, WorkItem):
        obj.reviewed_by = user                    # zweite Person
    if to_state == ItemStatus.APPROVED:
        if isinstance(obj, WorkItem):
            obj.approved_by = user                # dritte Person (Regel 2)
        if hasattr(obj, "processed_at"):
            obj.processed_at = timezone.now()
    obj.save()

    ev = LifecycleEvent(
        from_state=frm, to_state=to_state,
        iteration=getattr(obj, cfield, 1), by=user, note=note[:255])
    if isinstance(obj, WorkItem):
        ev.work_item = obj
    else:
        ev.document = obj
    ev.save()
    return ev


# ── Audit-Rückstufung (externer Auditor: GENAU EINE Stufe herunter) ──────────
# Lineare Stufenordnung je Phase. Der Auditor stuft NUR herunter (Rückweisung);
# die Freigabe nach oben bleibt menschlich (3-Personen-Regel, IEC 61508).
_AUDIT_ORDER_SPEC = [ItemStatus.DRAFT, ItemStatus.PROPOSED, ItemStatus.REVIEWED,
                     ItemStatus.APPROVED, ItemStatus.SIGNED]
_AUDIT_ORDER_STD = [ItemStatus.DRAFT, ItemStatus.PROPOSED,
                    ItemStatus.APPROVED, ItemStatus.SIGNED]


def audit_step_down_target(obj):
    """Die Stufe GENAU eine Ebene tiefer (oder None, wenn schon unten/unbekannt)."""
    spec = isinstance(obj, WorkItem) and obj.phase != Phase.REQUIREMENT
    order = _AUDIT_ORDER_SPEC if spec else _AUDIT_ORDER_STD
    try:
        i = order.index(obj.status)
    except ValueError:
        return None
    return order[i - 1] if i > 0 else None


def audit_downgrade(obj, user, note=""):
    """Externer Auditor stuft ein Item um GENAU EINE Stufe herunter (Rückweisung),
    NIE hinauf. Betroffene Freigaben verfallen, Revision/Iteration +1, Event mit
    Auditor + Finding. Die Freigabe nach oben bleibt rein menschlich."""
    to_state = audit_step_down_target(obj)
    if not to_state:
        raise TransitionError("Bereits auf der untersten Stufe — keine Rückstufung möglich.")
    frm = obj.status
    cfield = counter_field(obj)
    setattr(obj, cfield, getattr(obj, cfield, 1) + 1)   # neue Revision/Iteration
    if isinstance(obj, WorkItem):
        if to_state != ItemStatus.APPROVED:             # Freigabe verfällt
            obj.approved_by = None
        if to_state in (ItemStatus.DRAFT, ItemStatus.PROPOSED, ItemStatus.REWORK):
            obj.reviewed_by = None                      # Review verfällt
    obj.status = to_state
    obj.save()
    ev = LifecycleEvent(from_state=frm, to_state=to_state,
                        iteration=getattr(obj, cfield, 1), by=user,
                        note=("[Audit-Rückstufung] " + (note or ""))[:255])
    if isinstance(obj, WorkItem):
        ev.work_item = obj
    else:
        ev.document = obj
    ev.save()
    return ev
