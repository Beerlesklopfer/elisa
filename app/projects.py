"""
Aktives Projekt (Mandant) je Session — MIT Berechtigungssystem.

Zugriff ist auf **Projektmitglieder** beschränkt (`ProjectMembership`): nur wer im
Projekt Mitglied ist (oder Admin/PM) sieht dessen Dokumente/Items. AUSNAHME: das
**Standard-/Testprojekt** (`key='standard'`) hat JEDER Benutzer – so ist niemand
ohne Arbeitsumgebung. Das aktive Projekt steckt in der Session und wird bei jedem
Zugriff gegen die Mitgliedschaft geprüft.
"""
from app.models import Project

SESSION_KEY = "active_project_id"
STANDARD_KEY = "standard"


def standard_project():
    """Das Standard-/Testprojekt (für ALLE Benutzer). Wird bei Bedarf angelegt."""
    proj, _ = Project.objects.get_or_create(
        key=STANDARD_KEY, defaults={"name": "Standardprojekt (Test)"})
    return proj


def ensure_default_project():
    """Garantiert das Standard-/Testprojekt (Bootstrap)."""
    return standard_project()


def enroll_in_standard_project(user, role=None):
    """Trägt einen Benutzer als Mitglied im Standard-/Testprojekt ein (idempotent).
    Beim Anlegen eines Users aufrufen; Backfill via Migration."""
    from app.models import ProjectMembership, Role
    if not getattr(user, "pk", None):
        return None
    m, _ = ProjectMembership.objects.get_or_create(
        project=standard_project(), user=user,
        defaults={"role": role or Role.DESIGNER})
    return m


def ensure_project_chat(project):
    """Stellt den Default-Projekt-Chat (geteilt, ohne owner/Item) eines Projekts
    sicher und liefert ihn. Beim Anlegen eines Projekts aufrufen."""
    from app.models import ChatSession
    if project is None:
        return None
    chat = (ChatSession.objects.filter(project=project, shared=True)
            .order_by("created_at").first())
    if chat is None:
        chat = ChatSession.objects.create(project=project, shared=True, owner=None,
                                          title="Projekt-Chat")
    return chat


def _is_admin(user):
    return bool(getattr(user, "is_authenticated", False)
                and (user.is_superuser or user.is_staff))


def is_project_member(user, project):
    """Zugriff: Standard-/Testprojekt (alle), Admin/PM (alles) ODER Mitglied."""
    if project is None or not getattr(user, "is_authenticated", False):
        return False
    if project.key == STANDARD_KEY:
        return True
    from app.permissions import is_pm_or_admin
    if is_pm_or_admin(user):
        return True
    from app.models import ProjectMembership
    return ProjectMembership.objects.filter(project=project, user=user).exists()


def accessible_projects(user):
    """Sichtbare Projekte: SEINE (Mitgliedsprojekte) + immer das Standard-/Test-
    projekt; Ausnahme Admin/PM sehen alle."""
    qs = Project.objects.filter(archived=False)
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    from app.permissions import is_pm_or_admin
    if is_pm_or_admin(user):
        return qs
    from django.db.models import Q
    return qs.filter(Q(memberships__user=user) | Q(key=STANDARD_KEY)).distinct()


def get_active_project(request):
    """Aktives Projekt der Session – nur wenn Mitglied; sonst erstes zugängliches;
    sonst das Standard-/Testprojekt (jeder Benutzer hat es)."""
    user = getattr(request, "user", None)
    pid = request.session.get(SESSION_KEY)
    if pid:
        proj = Project.objects.filter(pk=pid, archived=False).first()
        if proj and is_project_member(user, proj):
            return proj
    proj = accessible_projects(user).first()
    if proj is None and getattr(user, "is_authenticated", False):
        proj = standard_project()        # niemand bleibt ohne Projekt
    if proj is not None:
        request.session[SESSION_KEY] = proj.pk
    else:
        request.session.pop(SESSION_KEY, None)
    return proj


def set_active_project(request, project):
    """Setzt das aktive Projekt – nur wenn der Nutzer dort Mitglied ist."""
    if is_project_member(getattr(request, "user", None), project):
        request.session[SESSION_KEY] = project.pk
        return True
    return False
