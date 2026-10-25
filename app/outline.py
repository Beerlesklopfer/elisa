"""Gliederung: Identifier-Nummerierung + Item-Anlage für die Worktree-Struktur.

Reine Mechanik (deterministisch): aus einem Referenz-Identifier (z. B. „S4.1") und
einem Modus das nächste FREIE Identifier ableiten und ein DRAFT-Item anlegen:
  • child   → Subitem    (S4.1   → S4.1.<n>)
  • sibling → gleiche Ebene (S4.1 → S4.<n>)
Die Freigabe bleibt menschlich (Statusautomat); hier wird nur strukturiert.
"""
import re

_SPLIT = re.compile(r"^\s*([A-Za-z]+)\s*(.*)$")

# Identifier-Präfix je (anlegbarer) Phase – für das ERSTE/neue Top-Level-Item.
# Links 1-stellig (R/S/A/M), rechts 2-stellig (MT/IT/ST/AT) – kollidiert NICHT
# mit den linken Präfixen (split_ident trennt „S1" vs. „ST1" sauber).
PHASE_PREFIX = {"REQ": "R", "SPEC": "S", "ARCH": "A", "MOD": "M",
                "MODTEST": "MT", "INTTEST": "IT", "SYSTEST": "ST", "ACCTEST": "AT"}


def split_ident(ident):
    """'S4.1.1' → ('S', [4,1,1]); Unpassendes → ('', [])."""
    m = _SPLIT.match(ident or "")
    if not m:
        return "", []
    return m.group(1), [int(x) for x in re.findall(r"\d+", m.group(2))]


def join_ident(prefix, nums):
    return prefix + ".".join(str(n) for n in nums)


def next_identifier(project, ref_identifier, mode):
    """Nächstes freies Identifier relativ zu ref. mode ∈ {'child','sibling'}."""
    prefix, nums = split_ident(ref_identifier)
    if not prefix or not nums:
        return ref_identifier
    parent = list(nums) if mode == "child" else list(nums[:-1])
    depth = len(parent) + 1
    used = []
    for ident in project.work_items.values_list("identifier", flat=True):
        p, ns = split_ident(ident)
        if p == prefix and len(ns) == depth and ns[:len(parent)] == parent:
            used.append(ns[-1])
    return join_ident(prefix, parent + [(max(used) + 1) if used else 1])


def create_outline_item(project, ref_identifier, mode, phase, *, title="", body="",
                        rationale="", by=None, generated_by_llm=False, llm_model="",
                        derived=None):
    """Legt ein Gliederungs-Item (DRAFT) an, auto-nummeriert relativ zu
    `ref_identifier` (String – darf auch ein reiner Ordner-Schlüssel ohne eigenes
    Item sein, z. B. „S4"). `phase` + `derived` (Traceability) gibt der Aufrufer."""
    from app.models import WorkItem, ItemStatus
    from app import history as hist_mod
    ident = next_identifier(project, ref_identifier, mode)
    new = WorkItem.objects.create(
        project=project, phase=phase, identifier=ident,
        title=(title or ident)[:160], body=body, rationale=rationale,
        status=ItemStatus.DRAFT,
        created_by=(by if not generated_by_llm else None),
        generated_by_llm=generated_by_llm, llm_model=llm_model)
    if derived:
        new.derived_from.set(derived)
    hist_mod.record_created(new, by=by)
    return new


def next_top_identifier(project, phase):
    """Nächstes freies Top-Level-Identifier einer Phase (z. B. erstes SPEC-Item → S1)."""
    prefix = PHASE_PREFIX.get(phase, (phase or "X")[:1].upper())
    used = []
    for ident in project.work_items.values_list("identifier", flat=True):
        p, ns = split_ident(ident)
        if p == prefix and len(ns) == 1:
            used.append(ns[0])
    return f"{prefix}{(max(used) + 1) if used else 1}"


def create_top_item(project, phase, *, title="", by=None, generated_by_llm=False,
                    llm_model=""):
    """Legt ein neues TOP-LEVEL-Item (DRAFT) einer Phase an – auch im leeren Projekt."""
    from app.models import WorkItem, ItemStatus
    from app import history as hist_mod
    ident = next_top_identifier(project, phase)
    new = WorkItem.objects.create(
        project=project, phase=phase, identifier=ident, title=(title or ident)[:160],
        status=ItemStatus.DRAFT, created_by=(by if not generated_by_llm else None),
        generated_by_llm=generated_by_llm, llm_model=llm_model)
    hist_mod.record_created(new, by=by)
    return new


def resolve_ref(project, ref_identifier):
    """Löst eine Referenz auf: (phase, derived_parents). Echtes Item → dessen Phase
    + Traceability; reiner Ordner-Schlüssel → Phase aus einem Kind, keine Eltern.
    Liefert (None, None), wenn nichts passt."""
    item = project.work_items.filter(identifier=ref_identifier).first()
    if item:
        return item.phase, list(item.derived_from.all())
    child = project.work_items.filter(identifier__startswith=ref_identifier + ".").first()
    if child:
        return child.phase, []
    return None, None
