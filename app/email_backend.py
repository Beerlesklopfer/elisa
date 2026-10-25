"""
E-Mail-Backend, das die im Admin gepflegten SMTP-Einstellungen nutzt.

Liest die aktive EmailSettings-Zeile aus der DB und überschreibt damit die
Verbindungsparameter; fehlt sie (oder die DB ist nicht bereit), gilt die
env-Konfiguration aus settings.py.
"""
from django.core.mail.backends.smtp import EmailBackend


class DBEmailBackend(EmailBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            from app.models import EmailSettings
            s = EmailSettings.objects.filter(active=True).order_by("-updated_at").first()
            if s:
                self.host = s.host or self.host
                self.port = s.port or self.port
                self.username = s.username or self.username
                self.password = s.password or self.password
                # TLS und SSL schließen sich gegenseitig aus.
                self.use_ssl = bool(s.use_ssl)
                self.use_tls = bool(s.use_tls) and not self.use_ssl
                self.timeout = s.timeout or self.timeout
        except Exception:
            # DB noch nicht migriert o. Ä. -> env-Defaults behalten.
            pass

    @staticmethod
    def active_from_email(default: str) -> str:
        try:
            from app.models import EmailSettings
            s = EmailSettings.objects.filter(active=True).first()
            if s and s.from_email:
                return s.from_email
        except Exception:
            pass
        return default
