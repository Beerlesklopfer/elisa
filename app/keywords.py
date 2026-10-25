"""
Schlagwortkatalog als KOMPAKTER Kontext für das lokale Modell (Ollama).

Statt Volltext-Chunks bekommt Ollama einen knappen Index „Dokument/Item →
Schlagworte". Das spart Kontext-Breite und erdet die Suche an den (vom großen
MCP-LLM vorgeschlagenen, vom Menschen bestätigten) Schlagworten. Nie verbindlich
(CLAUDE.md Regel 3) – reine Orientierung/Retrieval-Hilfe.
"""


def catalog_text(project, max_lines: int = 200) -> str:
    """Kompakter „Ziel → Schlagworte"-Index des Projekts (oder ''), für den
    System-Kontext eines lokalen Chat-/Feedback-Modells."""
    from .models import KeywordLink
    by = {}
    qs = KeywordLink.objects.select_related("keyword", "document", "work_item")
    for l in qs:
        if l.document_id and l.document and l.document.project_id == project.id:
            name = l.document.original_name or f"Doc#{l.document_id}"
        elif l.work_item_id and l.work_item and l.work_item.project_id == project.id:
            name = l.work_item.identifier
        else:
            continue
        by.setdefault(name, set()).add(l.keyword.text)
    if not by:
        return ""
    lines = [f"- {name}: {', '.join(sorted(kws))}"
             for name, kws in sorted(by.items())][:max_lines]
    return ("SCHLAGWORTKATALOG (kompakter Index der Projektdokumente/-items — "
            "nutze diese Schlagworte zur Orientierung statt Volltext; das spart "
            "Kontext):\n" + "\n".join(lines))
