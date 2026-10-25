"""
Backfill: jedes bestehende Projekt bekommt einen Default-Projekt-Chat (geteilt,
ohne owner/Item), in dem die Projektmitglieder allgemeine Themen besprechen.
Idempotent: legt nur an, wenn noch kein geteilter Chat existiert.
"""
from django.db import migrations


def create_chats(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    ChatSession = apps.get_model("app", "ChatSession")
    for p in Project.objects.all():
        if not ChatSession.objects.filter(project=p, shared=True).exists():
            ChatSession.objects.create(project=p, shared=True, owner=None,
                                       title="Projekt-Chat")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0034_chatsession_shared"),
    ]
    operations = [
        migrations.RunPython(create_chats, noop),
    ]
