"""Backfill: original_name für bestehende Dokumente aus dem bisherigen Pfad-Basename."""
import os

from django.db import migrations


def backfill(apps, schema_editor):
    PD = apps.get_model("app", "ProjectDocument")
    for d in PD.objects.filter(original_name="").exclude(file=""):
        name = os.path.basename(d.file.name or "")
        if name:
            d.original_name = name
            d.save(update_fields=["original_name"])


class Migration(migrations.Migration):
    dependencies = [("app", "0026_projectdocument_original_name")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
