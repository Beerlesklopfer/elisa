"""Persona "Salinar" heißt jetzt "Esra" (Esra, der Schriftgelehrte und Gesetzeskundige).

Benennt Modell, Rollenbeschreibung, MCP-Token und Worker-Backend um. Der Token-Wert
bleibt erhalten, laufende Worker brauchen keinen neuen Schlüssel.
"""
from django.db import migrations, models


def rename_persona(apps, schema_editor):
    MCPToken = apps.get_model("app", "MCPToken")
    WorkerBackend = apps.get_model("app", "WorkerBackend")
    LLMRoleDescription = apps.get_model("app", "LLMRoleDescription")
    for t in MCPToken.objects.filter(name__startswith="Salinar"):
        t.name = t.name.replace("Salinar", "Esra", 1)
        t.save(update_fields=["name"])
    for b in WorkerBackend.objects.filter(handle="salinar"):
        b.handle = "esra"
        if b.name.startswith("Salinar"):
            b.name = b.name.replace("Salinar", "Esra", 1)
        b.save(update_fields=["handle", "name"])
    old = LLMRoleDescription.objects.filter(role="SALINAR").first()
    if old:
        if LLMRoleDescription.objects.filter(role="ESRA").exists():
            old.delete()
        else:
            old.role = "ESRA"
            old.save(update_fields=["role"])


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0050_workitem_verifies_alter_workitem_phase"),
    ]

    operations = [
        migrations.RenameModel(old_name="SalinarTask", new_name="EsraTask"),
        migrations.AlterField(
            model_name="esratask",
            name="project",
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="esra_tasks", to="app.project"),
        ),
        migrations.AlterField(
            model_name="llmroledescription",
            name="role",
            field=models.CharField(choices=[('REQ', 'Software-Sicherheitsanforderungen'), ('SPEC', 'Software-Systementwurf'), ('ARCH', 'Software-Architektur'), ('MOD', 'Software-Modulentwurf'), ('MODTEST', 'Software-Modultest'), ('INTTEST', 'Integrationstest (HW/SW)'), ('SYSTEST', 'Software-Integrationstest'), ('ACCTEST', 'Software-Sicherheitsvalidierung'), ('ESRA', 'Esra – Normenrecherche'), ('DRAGOMAN', 'Dragoman – Übersetzer'), ('AUDITOR', 'Auditor – externes Audit')], max_length=8, unique=True),
        ),
        migrations.RunPython(rename_persona, migrations.RunPython.noop),
    ]
