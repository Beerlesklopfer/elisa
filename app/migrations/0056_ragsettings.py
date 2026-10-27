from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0055_chatmessage_reply_to"),
    ]

    operations = [
        migrations.CreateModel(
            name="RagSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ocr_model", models.CharField(blank=True, help_text="Modell-Key aus Eliezers Allowlist mit OCR/Vision (z. B. allenai/olmocr-2-7b). Leer = kein OCR; Scans ergeben dann keinen Text.", max_length=128, verbose_name="OCR-/Vision-Modell")),
                ("ocr_min_chars", models.PositiveIntegerField(default=25, help_text="Hat eine Seite weniger Text, wird sie per OCR gelesen.", verbose_name="OCR ab weniger Zeichen je Seite")),
                ("ocr_dpi", models.PositiveIntegerField(default=150, help_text="Höher = genauer, aber langsamer und speicherhungriger (100–300).", verbose_name="Auflösung (dpi)")),
            ],
            options={"verbose_name": "RAG-Einstellung (OCR)", "verbose_name_plural": "RAG-Einstellungen (OCR)"},
        ),
    ]
