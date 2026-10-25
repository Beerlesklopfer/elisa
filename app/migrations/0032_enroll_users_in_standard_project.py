"""
Backfill: jeder bestehende Benutzer wird Mitglied im Standard-/Testprojekt
(`key='standard'`). Idempotent; legt das Standardprojekt bei Bedarf an.
"""
from django.db import migrations


def enroll_all(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    User = apps.get_model("auth", "User")
    ProjectMembership = apps.get_model("app", "ProjectMembership")
    std, _ = Project.objects.get_or_create(
        key="standard", defaults={"name": "Standardprojekt (Test)"})
    for u in User.objects.all():
        ProjectMembership.objects.get_or_create(
            project=std, user=u, defaults={"role": "DESIGN"})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0031_workitem_blocks_workitem_related"),
    ]
    operations = [
        migrations.RunPython(enroll_all, noop),
    ]
