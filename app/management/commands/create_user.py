"""
Benutzer per Kommandozeile anlegen – mit der Nomenklatur Vorname.Nachname.

Beispiele:
    python manage.py create_user --first Jörg --last Bernau --superuser
    python manage.py create_user --first Thomas --last Holm --email t.holm@... --password geheim
Ohne --password wird interaktiv (verdeckt) gefragt.
"""
import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app.views_users import login_name


class Command(BaseCommand):
    help = "Legt einen Benutzer an (Login = vorname.nachname)."

    def add_arguments(self, parser):
        parser.add_argument("--first", required=True, help="Vorname")
        parser.add_argument("--last", required=True, help="Nachname")
        parser.add_argument("--email", default="", help="E-Mail (sonst login@example.com)")
        parser.add_argument("--password", default="", help="Passwort (sonst interaktive Abfrage)")
        parser.add_argument("--superuser", action="store_true", help="Superuser-Rechte")
        parser.add_argument("--staff", action="store_true", help="Admin-/Staff-Zugang")

    def handle(self, *args, **opts):
        User = get_user_model()
        first, last = opts["first"].strip(), opts["last"].strip()
        if not first or not last:
            raise CommandError("Vor- und Nachname erforderlich.")

        username = login_name(first, last)
        email = opts["email"].strip() or f"{username}@example.com"

        password = opts["password"]
        if not password:
            password = getpass.getpass("Passwort: ")
            if password != getpass.getpass("Passwort (Wiederholung): "):
                raise CommandError("Passwörter stimmen nicht überein.")
        if not password:
            raise CommandError("Leeres Passwort nicht zulässig.")

        is_super = opts["superuser"]
        user = User.objects.create_user(
            username=username, password=password, email=email,
            first_name=first, last_name=last,
        )
        user.is_superuser = is_super
        user.is_staff = is_super or opts["staff"]
        user.save()

        self.stdout.write(self.style.SUCCESS(
            f"Benutzer angelegt: {username}  (E-Mail {email}"
            f"{', Superuser' if is_super else ''}"
            f"{', Staff' if user.is_staff and not is_super else ''})"))
