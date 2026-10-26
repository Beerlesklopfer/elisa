from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0054_alter_llmroledescription_lukas"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="reply_to",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="replies", to="app.chatmessage"),
        ),
    ]
