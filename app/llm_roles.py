"""
Zusammenstellung des LLM-Kontexts je Rolle + Projekt.

Liefert die im Admin gepflegte Rollenbeschreibung (eine der 8 V-Modell-Rollen)
zusammen mit der PROJEKTBESCHREIBUNG, damit das LLM bei jedem Item weiß, in
welcher Rolle es agiert und in welchem Projekt.
"""
from __future__ import annotations

# WorkItem-Phase -> V-Modell-Rolle. Für die Teststufen (rechte Seite) ist der
# Phasen-Code identisch mit dem Rollen-Code → die Aufrufer nutzen
# PHASE_TO_ROLE.get(phase, phase), die Identität deckt MODTEST/INTTEST/… ab.
PHASE_TO_ROLE = {"REQ": "REQ", "SPEC": "SPEC", "ARCH": "ARCH", "MOD": "MOD"}


def iec_reference_for(phase_or_role: str) -> str:
    """IEC-61508-Bezug für eine WorkItem-Phase bzw. V-Modell-Rolle (über die DB)."""
    from app.models import LLMRoleDescription
    role = PHASE_TO_ROLE.get(phase_or_role, phase_or_role)
    rd = LLMRoleDescription.objects.filter(role=role).first()
    return rd.iec_reference if rd else ""


def role_description(role: str) -> str:
    from app.models import LLMRoleDescription
    rd = LLMRoleDescription.objects.filter(role=role).first()
    if not rd:
        return ""
    ref = f" (Bezug: {rd.iec_reference})" if rd.iec_reference else ""
    return f"{rd.description}{ref}"


# Für JEDEN V-Schritt gleich – die strikte Ableitungs-/Governance-Regel steht
# bewusst HIER (Persona) statt in der generischen Tool-Description, damit sie
# phasengerecht ist (in ARCH nicht mit REQ-Beispielen „mitgeschleppt").
DERIVATION_RULES = (
    "ABLEITUNG (bindend, für deinen V-Schritt):\n"
    "• Du verfasst KEINEN verbindlichen Inhalt und ERFINDEST NICHTS – du leitest "
    "strikt aus der ÜBERGEORDNETEN Ebene ab (deine derived_from-Items).\n"
    "• GLIEDERUNG der übergeordneten Ebene übernehmen (Struktur, Reihenfolge, "
    "Benennung) – KEINE eigene Gliederung/Nummerierung.\n"
    "• LÜCKEN MELDEN statt füllen (kurzer Vermerk 'nicht spezifiziert').\n"
    "• Sprache der Quelle beibehalten – NICHT übersetzen.\n"
    "• Vorschläge bleiben DRAFT; Freigabe ist menschlich."
)


def context_for(project=None, role: str | None = None, item=None) -> str:
    """
    Baut den System-Kontext: Rollenbeschreibung (falls Rolle/Item bekannt)
    + generische Ableitungsregeln + Projektbeschreibung. Leere Teile entfallen.
    """
    parts = []
    if item is not None and role is None:
        _ph = getattr(item, "phase", None)
        role = PHASE_TO_ROLE.get(_ph, _ph)          # Teststufen: Phase == Rolle
        project = project or getattr(item, "project", None)
    if role:
        desc = role_description(role)
        if desc:
            parts.append(f"DEINE ROLLE ({role}):\n{desc}")
        # Generische Ableitungsregeln nur ergänzen, wenn die Persona sie nicht
        # bereits selbst enthält (vermeidet Doppelung bei ausführlichen Personas).
        if "KEINE FANTASIE" not in (desc or ""):
            parts.append(DERIVATION_RULES)
    if project is not None:
        pdesc = (project.description or "").strip()
        header = f"PROJEKT: {project.name}"
        parts.append(header + (f"\nProjektbeschreibung:\n{pdesc}" if pdesc else ""))
    return "\n\n".join(parts)
