"""
Aufzeichnung der lückenlosen WorkItem-Historie (deterministisch, append-only).

Reine Mechanik: vergleicht einen Vorher-Snapshot mit dem aktuellen Zustand und
schreibt je geändertem Feld einen `WorkItemHistory`-Eintrag mit Person + Zeit +
alt→neu. Status-Übergänge laufen separat über `lifecycle.transition`
(`LifecycleEvent`); hier werden Inhalts-/Metadatenfelder erfasst.
"""
from __future__ import annotations

from app.models import WorkItemHistory

# Felder, deren Änderung nachvollziehbar sein muss.
TRACKED = ["phase", "identifier", "title", "body", "rationale", "status"]


def snapshot(item) -> dict:
    """Zustand der nachverfolgten Felder VOR einer Änderung festhalten."""
    return {f: getattr(item, f) for f in TRACKED}


def record_created(item, by=None, note="") -> None:
    WorkItemHistory.objects.create(item=item, kind=WorkItemHistory.Kind.CREATED,
                                   by=by, note=note)


_ROLLBACK_FIELDS = ["title", "body", "rationale", "identifier", "phase"]


def delete_current_revision(item, by=None) -> bool:
    """Rollt das JÜNGSTE Inhalts-Edit (EDITED-Batch) zurück und LÖSCHT diese
    Historieneinträge → die aktuelle Revision verschwindet, das Item steht auf dem
    vorigen Stand. Liefert True, wenn etwas zurückgerollt wurde, sonst False.
    Statusübergänge (LifecycleEvent) bleiben unberührt."""
    from datetime import timedelta
    edits = list(item.history.filter(kind=WorkItemHistory.Kind.EDITED).order_by("-at"))
    if not edits:
        return False
    latest = edits[0].at
    batch = [h for h in edits if latest - h.at <= timedelta(seconds=3)]
    for h in batch:
        if h.field in _ROLLBACK_FIELDS:
            setattr(item, h.field, h.old_value)
    item.save()
    WorkItemHistory.objects.filter(id__in=[h.id for h in batch]).delete()
    return True


def record_changes(item, before: dict, by=None, note="", chat_message=None) -> int:
    """
    Schreibt je geändertem Feld einen Historieneintrag. Liefert die Anzahl.
    `before` ist ein Snapshot von vor der Änderung (siehe `snapshot`).
    """
    n = 0
    for f in TRACKED:
        old = before.get(f)
        new = getattr(item, f)
        if old == new:
            continue
        kind = (WorkItemHistory.Kind.STATUS if f == "status"
                else WorkItemHistory.Kind.EDITED)
        WorkItemHistory.objects.create(
            item=item, kind=kind, field=f,
            old_value="" if old is None else str(old),
            new_value="" if new is None else str(new),
            by=by, note=note, chat_message=chat_message)
        n += 1
    return n
