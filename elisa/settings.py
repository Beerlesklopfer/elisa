"""
Django-Settings für ELISA.

Aufbau analog zu CrystalKey: env-getrieben mit FHS-Erkennung. Läuft im
Quell-Checkout (Entwicklung) komplett unter BASE_DIR; ein Debian-Paket würde
Code nach /usr/share/elisa und Konfig/Daten/Logs nach FHS-Pfade legen.

Quelle der Wahrheit ist die relationale DB (siehe CLAUDE.md). Das LLM
(Ollama oder Eliezer) läuft beratend daneben; sein Host ist nur eine Adresse.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(key: str, default: str = "False") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes", "on")


# ── FHS-Erkennung (Debian-/Service-Deploy) ────────────────────────────────
# Nur aktiv, wenn der laufende Prozess /etc/elisa/env wirklich LESEN darf
# (z. B. der www-data-Dienst). Ein Dev-Start als anderer Nutzer (640 root:www-data
# nicht lesbar) bleibt im Dev-Modus statt zu crashen.
FHS_CONF = Path("/etc/elisa/env")
FHS_MODE = FHS_CONF.is_file() and os.access(FHS_CONF, os.R_OK)

if FHS_MODE:
    # /etc/elisa/env in die Prozess-Umgebung laden (niedrige Priorität:
    # bereits gesetzte Variablen – z. B. via systemd – gewinnen).
    try:
        from dotenv import dotenv_values
        for key, value in dotenv_values(FHS_CONF).items():
            os.environ.setdefault(key, value)
    except Exception:
        pass
    DATA_DIR = Path("/var/lib/elisa")
    LOG_DIR = Path("/var/log/elisa")
else:
    # Entwicklung: optional eine .env neben manage.py laden.
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass
    DATA_DIR = BASE_DIR
    LOG_DIR = BASE_DIR / "logs"

# ── Sicherheit ────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-CHANGE-ME-elisa-dev-only-do-not-use-in-prod",
)
DEBUG = _env_bool("DJANGO_DEBUG", "True")

# Bind-Adresse des Servers (siehe elisa.service). Auch in ALLOWED_HOSTS.
BIND_ADDRESS = os.getenv("ELISA_BIND_ADDRESS", "127.0.0.1")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1",
    ).split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        f"http://{BIND_ADDRESS}:8000,http://{BIND_ADDRESS},"
        "http://localhost:8088,http://127.0.0.1:8088,"
        "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if o.strip()
]

# Hinter nginx (HTTPS-Terminierung): X-Forwarded-Proto auswerten, damit Django
# die Verbindung als sicher erkennt (sonst CSRF-403 trotz https-Origin).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = _env_bool("USE_X_FORWARDED_HOST", "True")
# Cookies nur über HTTPS senden (im Produktivbetrieb hinter TLS).
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", "False")
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", "False")

# ── Apps ──────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",   # nötig für HnswIndex (pgvector-Embeddings)
    "app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "app.nocache_middleware.NoCacheHTMLMiddleware",   # HTML revalidieren → ?v=-Asset-Busting greift sofort
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",   # UI-Sprache je Request (i18n)
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "app.db_middleware.DBSelectMiddleware",   # Mandanten-DB aus der Session (vor Auth)
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "app.presence_middleware.PresenceMiddleware",   # who-is-online (nach Auth)
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "elisa.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "app.context_processors.branding",
                "app.context_processors.projects",
                "app.context_processors.languages",
            ],
        },
    },
]

WSGI_APPLICATION = "elisa.wsgi.application"
ASGI_APPLICATION = "elisa.asgi.application"

# ── Datenbank ─────────────────────────────────────────────────────────────
# SQLite für Einzelplatz/Entwicklung (CLAUDE.md: läuft auf einem Laptop).
# Über DB_ENGINE=postgres und DB_* auf PostgreSQL umstellbar.
if os.getenv("DB_ENGINE", "sqlite").lower().startswith("postgres"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "elisa"),
            "USER": os.getenv("DB_USER", "elisa"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "elisa.sqlite3",
        }
    }

# ── Mandanten-/Mehr-DB-Auswahl am Login (ERP-Stil) ─────────────────────────
# DB_EXTRA = JSON {"alias": {"NAME": "...", "LABEL": "..."}}; erbt
# USER/PW/HOST/PORT/ENGINE von 'default'. Ohne DB_EXTRA = unverändert Single-DB.
SELECTABLE_DATABASES = [("default", os.getenv("DB_LABEL", "Standard"))]
try:
    import json as _json
    for _alias, _cfg in _json.loads(os.getenv("DB_EXTRA", "{}")).items():
        DATABASES[_alias] = {**DATABASES["default"], "NAME": _cfg["NAME"]}
        SELECTABLE_DATABASES.append((_alias, _cfg.get("LABEL", _alias)))
except Exception:
    pass

DATABASE_ROUTERS = ["app.dbrouter.TenantRouter"]

# ── Ollama (beratend, danebenlaufend) ─────────────────────────────────────
# Einzelplatz: localhost. Für mehrere Nutzer nur diese Host-Adresse auf eine
# Workstation/Server mit GPU zeigen lassen (CLAUDE.md).
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
# Anzeigename des RAG-Chat-Assistenten (der „Normen-Bücherwurm") statt „llama3.1".
RAG_PERSONA_NAME = os.getenv("RAG_PERSONA_NAME", "Wendelin")
# CPU-Ollama ist langsam → großzügiger Client-Timeout (Sekunden), sonst brechen
# Generierungen ab. Über die Umgebung anpassbar.
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))

# ── Lokale Inferenz: Ollama ODER Eliezer (GPU-Modellmanager, OpenAI-Dialekt) ─
# Umschalter für Chat/Embeddings/Notnagel-Toasts. Beratend wie bisher; nichts
# Verbindliches (CLAUDE.md). Eliezer: Modell-Keys stehen auf dessen Allowlist.
LOCAL_LLM_BACKEND = os.getenv("LOCAL_LLM_BACKEND", "ollama").strip().lower()
ELIEZER_BASE_URL = os.getenv("ELIEZER_BASE_URL", "http://127.0.0.1:1234")
ELIEZER_API_KEY = os.getenv("ELIEZER_API_KEY", "")   # nur aus der Umgebung, nie im Repo
ELIEZER_CHAT_MODEL = os.getenv("ELIEZER_CHAT_MODEL", "")
ELIEZER_EMBED_MODEL = os.getenv("ELIEZER_EMBED_MODEL", "")
ELIEZER_TRANSLATE_MODEL = os.getenv("ELIEZER_TRANSLATE_MODEL", "")   # leer = Chat-Modell
ELIEZER_TIMEOUT = int(os.getenv("ELIEZER_TIMEOUT", "300"))
if LOCAL_LLM_BACKEND == "eliezer":
    LOCAL_CHAT_MODEL, LOCAL_EMBED_MODEL = ELIEZER_CHAT_MODEL, ELIEZER_EMBED_MODEL
    LOCAL_LLM_HOST = ELIEZER_BASE_URL
else:
    LOCAL_CHAT_MODEL, LOCAL_EMBED_MODEL = OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL
    LOCAL_LLM_HOST = OLLAMA_HOST

# ── Incoming-Ablage (bewusst über das Dateisystem erreichbar) ─────────────
# Ablageordner für Norm-PDFs: kann auf eine Netzwerkfreigabe (Samba/NFS) zeigen,
# sodass Mitarbeiter Dateien direkt per Dateisystem ablegen. Wird vom RAG-Index
# (manage.py build_rag_index) und der Normen-Seite gelesen.
from pathlib import Path as _Path  # noqa: E402
INCOMING_DIR = _Path(os.getenv("ELISA_INCOMING_DIR", str(BASE_DIR / "incoming")))
try:
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass  # Verzeichnis wird ggf. vom Deploy angelegt; Import nie crashen lassen.

# Supervisor: Unix-Socket NUR für Nachrichten der MCP-Client-Worker UNTEREINANDER
# (Register + Relay). Die eigentliche Arbeit läuft über MCP-Chat (Primärkanal).
SUPERVISOR_SOCKET = os.getenv("ELISA_SUPERVISOR_SOCKET", str(DATA_DIR / "supervisor.sock"))
SUPERVISOR_STATUS = DATA_DIR / "supervisor_status.json"
# MCP-Basis für die Worker (Client-Verbindung). Default lokal hinter nginx-Präfix.
MCP_PUBLIC_BASE = os.getenv("MCP_PUBLIC_BASE", "http://127.0.0.1:8765")

# Archiv für indexierte (aus incoming entfernte) Norm-PDFs. Im Produktivbetrieb
# (Code unter /usr/share, read-only) auf /var/lib zeigen lassen.
RAG_ARCHIVE_DIR = _Path(os.getenv(
    "ELISA_ARCHIVE_DIR", str(BASE_DIR / "rag" / "indexed_pdfs")))

# ── Dokumentgenerierung (Markdown → Word, ELISA-Design) ────────────────────
PANDOC_BIN = os.getenv("PANDOC_BIN", "pandoc")
# Word-Vorlage als Pandoc-Referenzdokument (Header/Footer/Logo/Styles).
ELISA_REFERENCE_DOCX = os.getenv(
    "ELISA_REFERENCE_DOCX", str(BASE_DIR / "docs_templates" / "elisa-reference.docx")
)

# ── Passwörter / I18N ─────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "de"
TIME_ZONE = os.getenv("TZ", "Europe/Berlin")
USE_I18N = True

# Oberflächen-Lokalisierung (gettext). Quellsprache ist Deutsch.
# UI_LANGUAGES = Sprachen mit gepflegter UI-Übersetzung (Katalog unter
# locale/<lang>/LC_MESSAGES/). Wählt jemand eine Sprache OHNE UI-Katalog, fällt
# die Oberfläche auf Englisch zurück (der Inhalt/Items bleibt in der Sprache).
from django.utils.translation import gettext_lazy as _  # noqa: E402
UI_LANGUAGES = [c.strip() for c in os.getenv("UI_LANGUAGES", "de,en").split(",") if c.strip()]
_UI_NAMES = {"de": _("Deutsch"), "en": _("English"), "fr": _("Français"),
             "es": _("Español"), "it": _("Italiano"), "zh": _("中文")}
LANGUAGES = [(c, _UI_NAMES.get(c, c)) for c in UI_LANGUAGES]
LANGUAGE_FALLBACK = "en"   # UI-Fallback, wenn die gewählte Sprache nicht übersetzt ist
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_TZ = True

# ── Statische & Medien-Dateien ────────────────────────────────────────────
# Optional: Static ohne vorgeschalteten nginx ausliefern (Standard: nginx liefert
# STATIC_ROOT aus). ELISA_SERVE_STATIC=true aktiviert WhiteNoise.
if _env_bool("ELISA_SERVE_STATIC", "False"):
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = DATA_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = DATA_DIR / "media"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"   # nach Abmelden zur Login-Seite

# Case-insensitiver Anmeldename (Joerg.Bernau == joerg.bernau).
AUTHENTICATION_BACKENDS = ["app.auth_backends.CaseInsensitiveModelBackend"]

# ── E-Mail (lokaler Mailserver) ─────────────────────────────
# Für Passwort-Zurücksetzen u. a. Benachrichtigungen. Env-überschreibbar.
# DB-gestütztes Backend: nutzt die im Admin gepflegten SMTP-Settings,
# fällt sonst auf die env-Werte unten zurück.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "app.email_backend.DBEmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", "False")
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL", "False")
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "elisa@example.com")
PASSWORD_RESET_TIMEOUT = int(os.getenv("PASSWORD_RESET_TIMEOUT", str(60 * 60 * 24)))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
