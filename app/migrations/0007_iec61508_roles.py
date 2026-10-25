"""Bestehende ProjectMembership-Rollen auf die IEC-61508-Codes umstellen."""
from django.db import migrations

REMAP = {"LEAD": "PM", "SAFETY": "FSM", "DEV": "DESIGN",
         "REVIEW": "VERIF", "GUEST": "DESIGN"}


def remap_roles(apps, schema_editor):
    PM = apps.get_model("app", "ProjectMembership")
    for old, new in REMAP.items():
        PM.objects.filter(role=old).update(role=new)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("app", "0006_mcptoken")]
    operations = [migrations.RunPython(remap_roles, noop)]
