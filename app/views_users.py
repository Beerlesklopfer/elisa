"""
Userverwaltung und Rollenmanagement.

- Userverwaltung (nur Staff/Admin): Django-Benutzer anlegen, (de)aktivieren,
  Passwort zurücksetzen.
- Rollen je Projekt: ProjectMembership ordnet Nutzer einem Projekt mit einer
  Rolle zu (Projektleitung, Sicherheitsverantwortung, Entwicklung, Review, Gast).
"""
import re
import unicodedata

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Project, ProjectMembership, Role
from .projects import get_active_project

User = get_user_model()
staff_required = user_passes_test(lambda u: u.is_staff)

_UMLAUT = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def _translit(s: str) -> str:
    s = (s or "").strip().lower()
    for k, v in _UMLAUT.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s)


def sync_user_groups(user):
    """
    Spiegelt die Projektrollen eines Nutzers in die festen IEC-61508-Gruppen
    (Vereinigung über alle Projekte). Hält die fest verdrahteten Gruppen aktuell.
    """
    from django.contrib.auth.models import Group
    labels = dict(Role.choices)
    wanted = {f"IEC61508:{labels[r]}"
              for r in user.project_memberships.values_list("role", flat=True)
              if r in labels}
    iec_groups = Group.objects.filter(name__startswith="IEC61508:")
    user.groups.remove(*[g for g in user.groups.filter(name__startswith="IEC61508:")])
    user.groups.add(*[g for g in iec_groups if g.name in wanted])


def login_name(first: str, last: str) -> str:
    """Anmeldename nach Nomenklatur 'vorname.nachname' (eindeutig)."""
    base = f"{_translit(first)}.{_translit(last)}".strip(".")
    name, i = base, 1
    while User.objects.filter(username__iexact=name).exists():
        i += 1
        name = f"{base}{i}"
    return name


# ── Userverwaltung ─────────────────────────────────────────────────────────

@login_required
@staff_required
def user_list(request):
    return render(request, "users.html", {
        "active_tab": "users",
        "users": (User.objects.all().select_related("profile")
                  .prefetch_related("project_memberships").order_by("username")),
    })


@login_required
@staff_required
@require_POST
def user_create(request):
    first = (request.POST.get("first_name") or "").strip()
    last = (request.POST.get("last_name") or "").strip()
    password = request.POST.get("password") or ""
    if not first or not last or not password:
        messages.warning(request, "Vorname, Nachname und Passwort erforderlich.")
        return redirect("users")
    # Anmeldename folgt der Nomenklatur Vorname.Nachname.
    username = login_name(first, last)
    # E-Mail: angegebene nutzen, sonst aus dem Login ableiten.
    email = (request.POST.get("email") or "").strip() or f"{username}@example.com"
    u = User.objects.create_user(
        username=username, password=password, email=email,
        first_name=first, last_name=last,
    )
    u.is_staff = bool(request.POST.get("is_staff"))
    u.save()
    # Jeder Benutzer ist Mitglied im Standard-/Testprojekt.
    from .projects import enroll_in_standard_project
    enroll_in_standard_project(u)
    from .models import mark_password_changed
    mark_password_changed(u)
    messages.success(request, f"Benutzer „{username}“ angelegt (Login: {username}).")
    return redirect("users")


@login_required
@staff_required
@require_POST
def user_toggle(request, pk):
    u = get_object_or_404(User, pk=pk)
    u.is_active = not u.is_active
    u.save(update_fields=["is_active"])
    messages.info(request, f"„{u.username}“ ist jetzt {'aktiv' if u.is_active else 'inaktiv'}.")
    return redirect("users")


@login_required
@staff_required
@require_POST
def user_set_password(request, pk):
    u = get_object_or_404(User, pk=pk)
    pw = request.POST.get("password") or ""
    if pw:
        u.set_password(pw)
        u.save()
        from .models import mark_password_changed
        mark_password_changed(u)
        messages.success(request, f"Passwort für „{u.username}“ gesetzt.")
    return redirect("users")


@login_required
@staff_required
@require_POST
def user_edit(request, pk):
    """UPDATE: Name/E-Mail/Admin-Recht ändern. Login (vorname.nachname) wird
    bei Namensänderung angeglichen (eindeutig, außer dem Nutzer selbst)."""
    u = get_object_or_404(User, pk=pk)
    first = (request.POST.get("first_name") or u.first_name).strip()
    last = (request.POST.get("last_name") or u.last_name).strip()
    u.first_name, u.last_name = first, last
    u.email = (request.POST.get("email") or "").strip() or u.email
    u.is_staff = bool(request.POST.get("is_staff"))
    base = f"{_translit(first)}.{_translit(last)}".strip(".")
    if base and base != u.username.lower():
        name, i = base, 1
        while User.objects.filter(username__iexact=name).exclude(pk=u.pk).exists():
            i += 1
            name = f"{base}{i}"
        u.username = name
    u.save()
    messages.success(request, f"„{u.username}“ aktualisiert.")
    return redirect("users")


@login_required
def profile(request):
    """Selbstbedienung: eigene Profildaten (Name, E-Mail, optional neues Passwort).
    Login-Name (username) bleibt stabil; keine Rechte-Änderung."""
    u = request.user
    if request.method == "POST":
        u.first_name = (request.POST.get("first_name") or "").strip()
        u.last_name = (request.POST.get("last_name") or "").strip()
        u.email = (request.POST.get("email") or u.email).strip()
        u.save(update_fields=["first_name", "last_name", "email"])
        pw = (request.POST.get("password") or "").strip()
        pw2 = (request.POST.get("password2") or "").strip()
        if pw or pw2:
            # Zweiteingabe vergleichen, um Tippfehler auszuschließen.
            if pw != pw2:
                messages.error(request, "Die Passwörter stimmen nicht überein – "
                               "Passwort NICHT geändert (Profildaten gespeichert).")
                return redirect("profile")
            from django.contrib.auth import update_session_auth_hash
            from .models import mark_password_changed
            u.set_password(pw)
            u.save()
            mark_password_changed(u)
            update_session_auth_hash(request, u)   # Session aktiv halten
            messages.success(request, "Profil und Passwort aktualisiert.")
        else:
            messages.success(request, "Profil aktualisiert.")
        return redirect("profile")
    return render(request, "profile.html", {"active_tab": "", "user_obj": u})


@login_required
@staff_required
@require_POST
def user_delete(request, pk):
    """DELETE – mit Schutz: nicht sich selbst, Superuser nur durch Superuser."""
    u = get_object_or_404(User, pk=pk)
    if u == request.user:
        messages.warning(request, "Du kannst dich nicht selbst löschen.")
    elif u.is_superuser and not request.user.is_superuser:
        messages.warning(request, "Einen Superuser darf nur ein Superuser löschen.")
    else:
        name = u.username
        u.delete()
        messages.success(request, f"Benutzer „{name}“ gelöscht.")
    return redirect("users")


# ── Rollen je Projekt (Team) ───────────────────────────────────────────────

@login_required
def team(request):
    project = get_active_project(request)
    members = project.memberships.select_related("user")
    member_ids = members.values_list("user_id", flat=True)
    return render(request, "team.html", {
        "active_tab": "team",
        "project": project,
        "members": members,
        "roles": Role.choices,
        "available_users": User.objects.filter(is_active=True).exclude(pk__in=member_ids),
    })


@login_required
@require_POST
def team_add(request):
    project = get_active_project(request)
    user = get_object_or_404(User, pk=request.POST.get("user"))
    role = request.POST.get("role", Role.DESIGNER)
    ProjectMembership.objects.update_or_create(
        project=project, user=user, defaults={"role": role})
    sync_user_groups(user)
    messages.success(request, f"„{user.username}“ als {dict(Role.choices).get(role)} hinzugefügt.")
    return redirect("team")


@login_required
@require_POST
def team_update(request, pk):
    m = get_object_or_404(ProjectMembership, pk=pk, project=get_active_project(request))
    m.role = request.POST.get("role", m.role)
    m.save(update_fields=["role"])
    sync_user_groups(m.user)
    messages.info(request, f"Rolle von „{m.user.username}“ aktualisiert.")
    return redirect("team")


@login_required
@require_POST
def team_remove(request, pk):
    m = get_object_or_404(ProjectMembership, pk=pk, project=get_active_project(request))
    name = m.user.username
    user = m.user
    m.delete()
    sync_user_groups(user)
    messages.info(request, f"„{name}“ aus dem Projekt entfernt.")
    return redirect("team")
