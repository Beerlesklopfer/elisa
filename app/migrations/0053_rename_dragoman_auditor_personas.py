"""Personas umbenannt: Dragoman -> Tertius, Auditor -> Nathan (biblische Namen).

Benennt Token, Worker-Backends, Rollenbeschreibungen und die Absender alter
Chat-Nachrichten um (auch Wendelin -> Lukas, Salinar -> Esra). Die menschliche
Projektrolle "Auditor" bleibt unverändert.
"""
from django.db import migrations, models

PERSONAS = [("Dragoman", "dragoman", "DRAGOMAN", "Tertius", "tertius", "TERTIUS"),
            ("Auditor", "auditor", "AUDITOR", "Nathan", "nathan", "NATHAN")]


def rename(apps, schema_editor):
    MCPToken = apps.get_model("app", "MCPToken")
    WorkerBackend = apps.get_model("app", "WorkerBackend")
    LLMRoleDescription = apps.get_model("app", "LLMRoleDescription")
    ChatMessage = apps.get_model("app", "ChatMessage")
    for old_n, old_h, old_r, new_n, new_h, new_r in PERSONAS:
        for t in MCPToken.objects.filter(name__startswith=old_n + " (System)"):
            t.name = t.name.replace(old_n, new_n, 1)
            t.save(update_fields=["name"])
        for b in WorkerBackend.objects.filter(handle=old_h):
            b.handle = new_h
            if b.name.startswith(old_n):
                b.name = b.name.replace(old_n, new_n, 1)
            b.save(update_fields=["handle", "name"])
        old = LLMRoleDescription.objects.filter(role=old_r).first()
        if old:
            if LLMRoleDescription.objects.filter(role=new_r).exists():
                old.delete()
            else:
                old.role = new_r
                old.save(update_fields=["role"])
        ChatMessage.objects.filter(author_label="@" + old_h).update(author_label="@" + new_h)
        ChatMessage.objects.filter(author_label=old_n).update(author_label=new_n)
    ChatMessage.objects.filter(author_label="Wendelin").update(author_label="Lukas")
    ChatMessage.objects.filter(author_label="@salinar").update(author_label="@esra")
    ChatMessage.objects.filter(author_label="Salinar").update(author_label="Esra")


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0052_workerbackend_provider_eliezer"),
    ]

    operations = [
        migrations.AlterField(
            model_name="llmroledescription",
            name="role",
            field=models.CharField(choices=[('REQ', 'Software-Sicherheitsanforderungen'), ('SPEC', 'Software-Systementwurf'), ('ARCH', 'Software-Architektur'), ('MOD', 'Software-Modulentwurf'), ('MODTEST', 'Software-Modultest'), ('INTTEST', 'Integrationstest (HW/SW)'), ('SYSTEST', 'Software-Integrationstest'), ('ACCTEST', 'Software-Sicherheitsvalidierung'), ('ESRA', 'Esra – Normenrecherche'), ('TERTIUS', 'Tertius – Übersetzer'), ('NATHAN', 'Nathan – externes Audit')], max_length=8, unique=True),
        ),
        migrations.RunPython(rename, migrations.RunPython.noop),
    ]
