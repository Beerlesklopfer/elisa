"""
Heilt bestehende Projekte: die Primärsprache MUSS eine echte Projektsprache sein.
Zeigt sie ins Leere (z. B. Default „de", obwohl „de" nicht in `languages`), wird
die erste vorhandene Sprache zur Primärsprache. Räumt zugleich die (ungenutzte)
normative_languages-Liste auf — es gibt genau EINE normative Sprache = die Primär.
"""
from django.db import migrations


def heal(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    for p in Project.objects.all():
        langs = p.languages or []
        changed = False
        if langs and p.primary_language not in langs:
            p.primary_language = langs[0]
            changed = True
        if p.normative_languages:
            p.normative_languages = []   # Normativ = Primärsprache (Liste ungenutzt)
            changed = True
        if changed:
            p.save(update_fields=["primary_language", "normative_languages"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0037_alter_project_primary_language"),
    ]
    operations = [
        migrations.RunPython(heal, noop),
    ]
