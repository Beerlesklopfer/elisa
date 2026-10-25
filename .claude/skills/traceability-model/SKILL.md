---
name: traceability-model
description: Arbeit am V-Modell-Datenmodell (WorkItem, NormClause, NormLink), an Traceability-Relationen, Statusautomat oder Invarianten. Nutze diesen Skill IMMER, wenn es um Anforderungen, Spezifikationen, Architektur- oder Modul-Items, derived_from-Verknüpfungen, Orphan-Erkennung, Abdeckungsprüfung oder den Freigabe-Status (DRAFT/PROPOSED/APPROVED) geht – auch wenn der Begriff "Datenmodell" nicht ausdrücklich fällt.
---

# Traceability-Datenmodell

Bildet das gesamte V-Modell als selbstreferenzierende Hierarchie ab – links
spezifizierend, rechts verifizierend. Die Datenbank ist die einzige verbindliche
Quelle der Wahrheit.

## Entitäten (siehe `app/models.py`)

- `WorkItem` – ein Knoten auf einer der acht V-Ebenen (`phase`): links
  REQ/SPEC/ARCH/MOD, rechts MODTEST/INTTEST/SYSTEST/ACCTEST.
  - Verfeinerung nach unten über `derived_from` (ManyToMany auf sich selbst).
  - **Verifikation** (rechte Seite) über `verifies`: ein Test-Item verifiziert
    Entwicklungs-Items seiner Partnerebene (`VERIFY_PARTNER`: MOD↔MODTEST,
    ARCH↔INTTEST, SPEC↔SYSTEST, REQ↔ACCTEST). Gegenrichtung `verified_by`.
  - Abdeckung: `is_orphan` (links: kein `derived_from`; rechts: prüft nichts) und
    `is_unverified` (Entwicklungs-Item ohne prüfendes Test-Item).
- `NormClause` – eine Norm-Klausel (Standard + Klauselnummer + Text).
- `NormLink` – Verknüpfung WorkItem ↔ NormClause, `confirmed`-Flag.

## Harte Invarianten – nie aufweichen

1. `body` wird ausschließlich von Menschen geschrieben. Kein Code-Pfad mit
   LLM-Beteiligung darf `body` setzen.
2. `status == APPROVED` ist nur mit gesetztem `approved_by` (Mensch) zulässig.
   Diese Prüfung sitzt in `WorkItem.save()`.
3. Zustandsautomat: `DRAFT → PROPOSED → APPROVED` (letzter Schritt menschlich)
   und `* → OBSOLETE`.

## Häufige Aufgaben

**Offene Knoten für den nächsten Iterationsschritt finden** (reines ORM, kein LLM):

```python
from app.models import WorkItem, Phase

# Items unterhalb der Anforderungsebene ohne Verbindung nach oben
orphans = [w for w in WorkItem.objects.exclude(phase=Phase.REQUIREMENT)
           if not w.derived_from.exists()]

# Anforderungen, die in keiner tieferen Ebene verfeinert wurden
uncovered = WorkItem.objects.filter(phase=Phase.REQUIREMENT, refined_to__isnull=True)
```

„Abgearbeitet" heißt: keine Orphans und keine uncovered-Anforderungen mehr.
Diese Bedingung ist das Abbruchkriterium der Iteration – als DB-Abfrage, nicht
als Prompt.

**Eine Verfeinerung anlegen** (Inhalt kommt vom Menschen, hier nur die Kante):

```python
spec = WorkItem.objects.create(phase=Phase.SPECIFICATION, identifier="SPEC-031",
                               title=..., body=<menschlicher_text>, created_by=user)
spec.derived_from.add(parent_requirement)
```

## Vorsicht

- Invarianten gehören in Modell/DB-Constraints, nicht in Prompts oder Views.
- Beim Hinzufügen von Feldern, die das LLM befüllt: prüfen, dass sie nie
  inhaltlich verbindlich sind (Vorschlag/Provenienz ja, Inhalt nein).
