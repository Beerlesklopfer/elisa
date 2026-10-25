"""
Legt für jeden bestehenden Benutzer ein UserProfile an (damit `user.profile`
immer existiert). first_login/password_changed_at bleiben leer (unbekannt).
"""
from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("app", "UserProfile")
    for u in User.objects.all():
        UserProfile.objects.get_or_create(user=u)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0039_userprofile"),
    ]
    operations = [
        migrations.RunPython(backfill, noop),
    ]
