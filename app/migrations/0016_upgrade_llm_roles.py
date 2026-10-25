"""Bestehende LLM-Rollen auf die langen Beschreibungen + IEC-Klarnamen heben."""
from django.db import migrations


def upgrade(apps, schema_editor):
    LLM = apps.get_model("app", "LLMRoleDescription")
    from app.apps import _LLM_ROLE_DEFAULTS, _LLM_ROLE_IEC
    for role, desc in _LLM_ROLE_DEFAULTS.items():
        LLM.objects.update_or_create(
            role=role,
            defaults={"description": desc, "iec_reference": _LLM_ROLE_IEC.get(role, "")})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("app", "0015_llmroledescription_iec_reference")]
    operations = [migrations.RunPython(upgrade, noop)]
