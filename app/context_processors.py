"""Template-Kontext für das Corporate-Identity."""
from django.conf import settings


def projects(request):
    """Aktives Projekt + zugängliche Projektliste + Menü-Flags (nur eingeloggt)."""
    if not request.user.is_authenticated:
        return {}
    from app import projects as proj, permissions as perm
    return {
        "current_project": proj.get_active_project(request),
        "all_projects": proj.accessible_projects(request.user),  # nur Mitgliedsprojekte
        "is_admin": perm.is_admin(request.user),
        "is_pm_or_admin": perm.is_pm_or_admin(request.user),
    }


def languages(request):
    """Sprachen des aktiven Projekts + aktive Anzeigesprache (Menüzeilen-Umschalter)."""
    if not request.user.is_authenticated:
        return {}
    from app import projects as proj, languages as langs
    project = proj.get_active_project(request)
    codes = (project.languages if project and project.languages else [])
    primary = project.primary_language if project else ""
    active = request.session.get("lang") or primary
    # Hotkey-Reihenfolge: Primärsprache zuerst (ALT-1), dann Sekundärsprachen
    # (ALT-2 … ALT-0 = 10.). 0-basiert: ordered[0] = Primär.
    ordered = ([primary] if primary and primary in codes else []) \
        + [c for c in codes if c != primary]
    return {
        "project_languages": langs.expand(codes),
        "active_language": langs.info(active) if active else None,
        "lang_hotkeys": langs.expand(ordered),
        "lang_hotkey_codes": ordered,
    }


def branding(request):
    """Stellt Markendaten & Navigation für base.html bereit."""
    return {
        "company": {"product": "ELISA"},
        "ollama_chat_model": settings.OLLAMA_CHAT_MODEL,
    }
