from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0051_rename_salinar_to_esra"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workerbackend",
            name="provider",
            field=models.CharField(choices=[("CLAUDE", "Anthropic Claude"), ("OPENAI", "OpenAI / ChatGPT"), ("DEEPSEEK", "DeepSeek"), ("OLLAMA", "Ollama (lokal)"), ("LMSTUDIO", "LM Studio (lokal)"), ("ELIEZER", "Eliezer (lokal)"), ("CUSTOM", "OpenAI-kompatibel (custom)")], default="CLAUDE", max_length=10),
        ),
        migrations.AlterField(
            model_name="workerbackend",
            name="base_url",
            field=models.CharField(blank=True, help_text="Leer = Anbieter-Default. Für Ollama/LM Studio/Eliezer/DeepSeek/custom.", max_length=255, verbose_name="Base-URL"),
        ),
        migrations.AlterField(
            model_name="workerbackend",
            name="api_key",
            field=models.CharField(blank=True, help_text="Geheim. Claude: ANTHROPIC-Key. Eliezer: sk-… aus `eliezer --new-key`. Ollama/LM Studio: beliebig.", max_length=255, verbose_name="API-Key"),
        ),
    ]
