"""
Zentrale Zugriffsregeln + Decorators.

- **Admin** = Django Staff/Superuser.
- **PM** = Projektleitung (`Role.PROJECT_MANAGER`) in mindestens einem Projekt.
- **Projektzugriff** = Mitglied im Projekt (oder Admin) – siehe `projects.py`.

Verwendung an Views:  `@pm_or_admin_required`, `@admin_required`.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied


def is_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)
                and (user.is_superuser or user.is_staff))


def is_pm_or_admin(user) -> bool:
    """Admin ODER Projektleitung (PM) in irgendeinem Projekt."""
    if not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    from app.models import Role
    return user.project_memberships.filter(role=Role.PROJECT_MANAGER).exists()


def admin_required(view):
    """Nur Admin (Staff/Superuser) – sonst 403."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied("Nur für Administratoren.")
        return view(request, *args, **kwargs)
    return _wrapped


def pm_or_admin_required(view):
    """Nur Projektleitung (PM) oder Admin – sonst 403."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not is_pm_or_admin(request.user):
            raise PermissionDenied("Nur für Projektleitung oder Administratoren.")
        return view(request, *args, **kwargs)
    return _wrapped


def project_member_required(view):
    """Zugriff nur, wenn der Nutzer im AKTIVEN Projekt Mitglied ist (oder Admin).
    Schützt projekt-skopierte Views (Eingangsdokumente, Arbeitsbereich …)."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        from app import projects as proj
        project = proj.get_active_project(request)
        if project is None or not proj.is_project_member(request.user, project):
            raise PermissionDenied("Kein Zugriff – du bist keinem zugänglichen "
                                   "Projekt zugeordnet.")
        return view(request, *args, **kwargs)
    return _wrapped
