"""
Projektverwaltung (Mandanten).

'Alle sehen alle Projekte': jeder eingeloggte Nutzer kann Projekte anlegen,
auswählen und archivieren. Das aktive Projekt steckt in der Session und
begrenzt WorkItems, Spezifikationen und Chats. Normen sind global geteilt.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from app import projects as proj
from app.forms import ProjectForm
from app.models import Project, Customer
from app.permissions import pm_or_admin_required


@login_required
@pm_or_admin_required
def project_list(request):
    # Nur zugängliche Projekte (Mitgliedschaft; Admin sieht alle).
    items = (
        proj.accessible_projects(request.user).select_related("customer")
        .annotate(n_items=Count("work_items", distinct=True),
                  n_chats=Count("chat_sessions", distinct=True))
    )
    return render(request, "projects.html", {
        "active_tab": "projects",
        "projects": items,
        "customers": Customer.objects.filter(archived=False),
    })


@login_required
@pm_or_admin_required
def project_form(request, pk=None):
    """CRUD: Anlegen oder Bearbeiten eines Projekts (Update)."""
    project = get_object_or_404(Project, pk=pk) if pk else None
    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            obj = form.save(commit=False)
            if not obj.key:
                base = (slugify(obj.name) or "projekt")[:32]
                key, i = base, 1
                while Project.objects.filter(key=key).exclude(pk=obj.pk).exists():
                    i += 1
                    key = f"{base}-{i}"[:32]
                obj.key = key
            obj.save()
            if project is None:
                # Ersteller wird Projektleitung (Mitglied) → Zugriff + REQ-Edit.
                from app.models import ProjectMembership, Role
                ProjectMembership.objects.get_or_create(
                    project=obj, user=request.user,
                    defaults={"role": Role.PROJECT_MANAGER})
                proj.ensure_project_chat(obj)   # Default-Projekt-Chat
                proj.set_active_project(request, obj)
                messages.success(request, f"Projekt „{obj.name}“ angelegt und aktiviert.")
            else:
                messages.success(request, f"Projekt „{obj.name}“ gespeichert.")
            return redirect("projects")
    else:
        form = ProjectForm(instance=project)
    from app import languages as langs
    lang_list = []
    if project:
        for l in langs.expand(project.languages):
            lang_list.append({**l,
                              "normative": project.is_normative(l["code"]),
                              "is_primary": l["code"] == project.primary_language})
    return render(request, "project_form.html", {
        "active_tab": "projects", "form": form, "project": project,
        "lang_list": lang_list,
        "all_languages": langs.all_choices(),
    })


@login_required
@require_POST
def project_create(request):
    """Schnellanlage aus der Listenseite (Inline-Formular)."""
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.warning(request, "Bitte einen Projektnamen angeben.")
        return redirect("projects")
    key = (request.POST.get("key") or slugify(name))[:32]
    base, i = key, 1
    while Project.objects.filter(key=key).exists():
        i += 1
        key = f"{base}-{i}"[:32]
    customer = None
    cid = request.POST.get("customer")
    if cid:
        customer = Customer.objects.filter(pk=cid, archived=False).first()
    project = Project.objects.create(
        key=key, name=name, customer=customer,
        description=request.POST.get("description", ""))
    proj.set_active_project(request, project)
    messages.success(request, f"Projekt „{project.name}“ angelegt und aktiviert.")
    return redirect("home")


@login_required
@require_POST
def project_switch(request, pk):
    project = get_object_or_404(Project, pk=pk, archived=False)
    if proj.set_active_project(request, project):
        messages.info(request, f"Aktives Projekt: {project.name}")
    else:
        messages.error(request, f"Kein Zugriff auf „{project.name}“ – "
                       "du bist dort kein Mitglied.")
    return redirect(request.POST.get("next") or "home")


@login_required
@pm_or_admin_required
@require_POST
def project_archive(request, pk):
    project = get_object_or_404(Project, pk=pk)
    project.archived = True
    project.save(update_fields=["archived"])
    messages.info(request, f"Projekt „{project.name}“ archiviert.")
    return redirect("projects")


@login_required
@require_POST
def project_delete(request, pk):
    """CRUD: endgültiges Löschen (inkl. WorkItems/Chats via CASCADE)."""
    project = get_object_or_404(Project, pk=pk)
    name = project.name
    # Aktives Projekt der Session ggf. zurücksetzen.
    if request.session.get(proj.SESSION_KEY) == project.pk:
        request.session.pop(proj.SESSION_KEY, None)
    project.delete()
    messages.warning(request, f"Projekt „{name}“ endgültig gelöscht.")
    return redirect("projects")


# ── Mehrsprachigkeit: Projektsprachen + aktive Anzeigesprache ──────────────

@login_required
@pm_or_admin_required
@require_POST
def project_lang_add(request, pk):
    """Sprache zum Projekt hinzufügen (Typable-Combobox in den Projektsettings)."""
    p = get_object_or_404(Project, pk=pk)
    code = (request.POST.get("language") or "").strip().lower()[:8]
    if code and code not in (p.languages or []):
        p.languages = (p.languages or []) + [code]
        # Primärsprache muss eine echte Projektsprache sein: ist die aktuelle
        # Primär (z. B. der Default) nicht in der Liste, wird die erste die Primär.
        if p.primary_language not in p.languages:
            p.primary_language = code
        p.save(update_fields=["languages", "primary_language"])
        messages.success(request, f"Sprache „{code}“ hinzugefügt.")
    return redirect("project-edit", pk=pk)


@login_required
@pm_or_admin_required
@require_POST
def project_lang_remove(request, pk):
    p = get_object_or_404(Project, pk=pk)
    code = (request.POST.get("language") or "").strip().lower()
    p.languages = [l for l in (p.languages or []) if l != code]
    if p.primary_language == code:
        p.primary_language = p.languages[0] if p.languages else ""
    p.normative_languages = [l for l in (p.normative_languages or []) if l != code]
    p.save(update_fields=["languages", "primary_language", "normative_languages"])
    return redirect("project-edit", pk=pk)


@login_required
@pm_or_admin_required
@require_POST
def project_lang_mode(request, pk):
    """Es gibt GENAU EINE normative Sprache = die Primär-/Projektsprache; alle
    anderen sind informativ (übersetzbar). „Normativ" auf eine Sprache setzen
    macht sie zur Primärsprache (exklusiv – die bisherige wird damit informativ).
    „informativ" auf der Primärsprache ist unzulässig (es muss eine normative
    geben). Normative Sprachen sind nie Ziel einer Übersetzung."""
    p = get_object_or_404(Project, pk=pk)
    code = (request.POST.get("language") or "").strip().lower()
    mode = request.POST.get("mode")
    if code not in (p.languages or []):
        return redirect("project-edit", pk=pk)
    if mode == "normative":
        if code != p.primary_language:
            p.primary_language = code              # exklusiv: genau eine normative
            p.normative_languages = []             # Normativ = Primär (Liste ungenutzt)
            p.save(update_fields=["primary_language", "normative_languages"])
            messages.success(request, f"„{code}“ ist jetzt die normative (Projekt-)Sprache.")
    elif code == p.primary_language:               # informativ auf der Primärsprache
        messages.error(request, "Es gibt genau EINE normative Sprache (die "
                       "Projektsprache). Mache zuerst eine ANDERE Sprache normativ.")
    return redirect("project-edit", pk=pk)


@login_required
def set_language(request):
    """
    Umschalter in der Menüzeile: setzt die Inhaltssprache (Items) und die
    UI-Sprache. Hat die gewählte Sprache KEINE UI-Übersetzung, fällt die
    Oberfläche auf Englisch zurück (LANGUAGE_FALLBACK); der Inhalt bleibt aber
    in der gewählten Sprache.
    """
    from django.conf import settings as dj
    from django.utils import translation
    code = (request.GET.get("lang") or "").strip().lower()
    request.session["lang"] = code                          # Inhaltssprache
    ui = code if code in dj.UI_LANGUAGES else dj.LANGUAGE_FALLBACK
    translation.activate(ui)
    response = redirect(request.META.get("HTTP_REFERER") or "home")
    response.set_cookie(dj.LANGUAGE_COOKIE_NAME, ui,
                        max_age=dj.LANGUAGE_COOKIE_AGE)
    return response
