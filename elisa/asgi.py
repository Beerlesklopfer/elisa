"""ASGI-Einstieg für ELISA (z. B. daphne/uvicorn)."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "elisa.settings")

application = get_asgi_application()
