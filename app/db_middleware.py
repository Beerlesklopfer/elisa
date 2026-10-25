"""
Setzt je Request den aktiven Mandanten-DB-Alias aus der Session (Login-Wahl).

Reihenfolge in MIDDLEWARE: NACH SessionMiddleware (Session muss geladen sein),
VOR AuthenticationMiddleware (request.user wird aus der gewählten DB geladen).
"""
from django.conf import settings

from app import dbrouter


class DBSelectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._valid = {a for a, _ in getattr(settings, "SELECTABLE_DATABASES",
                                             [("default", "")])}

    def __call__(self, request):
        alias = "default"
        try:
            alias = request.session.get("db", "default")
        except Exception:
            pass
        if alias not in self._valid:
            alias = "default"
        dbrouter.set_db(alias)
        request.current_db = alias
        try:
            return self.get_response(request)
        finally:
            dbrouter.set_db("default")
