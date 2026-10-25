"""
Dokumentgenerierung: WorkItem-Baum → Markdown → Word (ELISA-Design).

Deterministisch, reines Django/Python + Pandoc — kein LLM beteiligt
(CLAUDE.md, Regel 5: Dokumentgenerierung ist reine Mechanik). Der Markdown
entsteht ausschließlich aus den menschlich geschriebenen Feldern der DB
(WorkItem.body, .title, .rationale); nichts wird vom LLM ergänzt.

Das ELISA-Design kommt aus der Pandoc-Referenzdatei
(settings.ELISA_REFERENCE_DOCX): Kopf-/Fußzeile, Logo, Schriften und die
benannten Word-Styles (Title, Heading1–6, Normal …) werden übernommen.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from django.conf import settings


# ── WorkItem-Baum → Markdown ───────────────────────────────────────────────

# Markdown-Überschriftsebene je V-Modell-Phase (deterministisches Mapping).
_PHASE_LEVEL = {"REQ": 1, "SPEC": 2, "ARCH": 3, "MOD": 4}


def workitem_to_markdown(root, *, include_rationale: bool = True) -> str:
    """
    Erzeugt Markdown aus einem WorkItem und seinen abgeleiteten Items.

    Nutzt ausschließlich menschlich gepflegte Felder. `refined_to` ist die
    Gegenrichtung von `derived_from` (siehe models.WorkItem).
    """
    lines: list[str] = []
    _emit(root, lines, include_rationale)
    return "\n".join(lines).strip() + "\n"


def _emit(item, lines: list[str], include_rationale: bool) -> None:
    level = _PHASE_LEVEL.get(item.phase, 1)
    hashes = "#" * level
    lines.append(f"{hashes} {item.identifier} — {item.title}")
    lines.append("")
    if item.body:
        lines.append(item.body.strip())
        lines.append("")
    if include_rationale and item.rationale:
        lines.append(f"> **Begründung:** {item.rationale.strip()}")
        lines.append("")
    # Bestätigte Norm-Bezüge als nachvollziehbare Liste (nur confirmed=True).
    confirmed = item.norm_links.filter(confirmed=True).select_related("clause")
    if confirmed:
        lines.append("**Normbezug:**")
        for link in confirmed:
            lines.append(f"- {link.clause.standard} {link.clause.clause}")
        lines.append("")
    for child in item.refined_to.all().order_by("identifier"):
        _emit(child, lines, include_rationale)


def document_frontmatter(title: str, *, author: str = "ELISA",
                         date: str | None = None) -> str:
    """Pandoc-Titelblock (% title / % author / % date)."""
    from datetime import date as _date
    date = date or _date.today().isoformat()
    return f"% {title}\n% {author}\n% {date}\n\n"


# ── Markdown → Word via Pandoc ─────────────────────────────────────────────

def markdown_to_docx(markdown: str, out_path: str | Path,
                     *, reference_docx: str | None = None) -> Path:
    """
    Rendert Markdown nach .docx im ELISA-Design.

    Übernimmt Styles/Header/Footer/Logo aus der Referenzdatei. Wirft
    CalledProcessError, wenn Pandoc fehlschlägt, und FileNotFoundError, wenn
    die Referenzdatei fehlt.
    """
    out_path = Path(out_path)
    reference = Path(reference_docx or settings.ELISA_REFERENCE_DOCX)
    if not reference.is_file():
        raise FileNotFoundError(f"Referenzdokument fehlt: {reference}")

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as tmp:
        tmp.write(markdown)
        md_path = tmp.name

    try:
        subprocess.run(
            [
                settings.PANDOC_BIN,
                md_path,
                f"--reference-doc={reference}",
                "--toc",
                "-o", str(out_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        Path(md_path).unlink(missing_ok=True)
    return out_path


def render_workitem_document(root, out_path: str | Path,
                             *, title: str | None = None) -> Path:
    """Komfort: WorkItem-Baum direkt als .docx rendern."""
    title = title or f"{root.identifier} — {root.title}"
    markdown = document_frontmatter(title) + workitem_to_markdown(root)
    return markdown_to_docx(markdown, out_path)


def _emit_flat(item, lines: list[str], include_rationale: bool) -> None:
    """Ein Item als ein Abschnitt – OHNE Rekursion (eine V-Phase = ein Dokument)."""
    level = _PHASE_LEVEL.get(item.phase, 1)
    lines.append(f"{'#' * level} {item.identifier} — {item.title}")
    lines.append("")
    if item.body:
        lines.append(item.body.strip())
        lines.append("")
    if include_rationale and item.rationale:
        lines.append(f"> **Begründung:** {item.rationale.strip()}")
        lines.append("")
    confirmed = item.norm_links.filter(confirmed=True).select_related("clause")
    if confirmed:
        lines.append("**Normbezug:**")
        for link in confirmed:
            lines.append(f"- {link.clause.standard} {link.clause.clause}")
        lines.append("")


def render_phase_document(items, title: str, out_path: str | Path,
                          *, include_rationale: bool = True) -> Path:
    """Vollständiges Dokument aus ALLEN Items einer V-Phase (je Item ein
    Abschnitt) – keine Teilabschnitt-Einzeldokumente."""
    lines: list[str] = []
    for it in items:
        _emit_flat(it, lines, include_rationale)
    markdown = document_frontmatter(title) + ("\n".join(lines).strip() + "\n")
    return markdown_to_docx(markdown, out_path)
