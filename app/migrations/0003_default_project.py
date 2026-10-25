"""Standardprojekt anlegen und bestehende WorkItems/Chats zuordnen."""
from django.db import migrations


def create_default_project(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    WorkItem = apps.get_model("app", "WorkItem")
    ChatSession = apps.get_model("app", "ChatSession")

    if WorkItem.objects.filter(project__isnull=True).exists() or \
       ChatSession.objects.filter(project__isnull=True).exists() or \
       not Project.objects.exists():
        project, _ = Project.objects.get_or_create(
            key="standard", defaults={"name": "Standardprojekt"})
        WorkItem.objects.filter(project__isnull=True).update(project=project)
        ChatSession.objects.filter(project__isnull=True).update(project=project)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0002_customer_alter_workitem_identifier_project_and_more"),
    ]
    operations = [migrations.RunPython(create_default_project, noop)]
