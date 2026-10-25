"""
Mandanten-Router (ERP-Stil): jede Anfrage spricht die beim Login gewählte DB.

- Ein Thread-local hält den aktiven DB-Alias je Request (Default: 'default').
- Sessions liegen IMMER in 'default' (sonst Henne-Ei: die Session enthält ja die
  DB-Wahl und muss ohne sie lesbar sein).
- Alles andere (inkl. auth.User) routet auf den gewählten Alias.

Ohne konfigurierte Zusatz-DBs (SELECTABLE_DATABASES = nur 'default') verhält sich
das System exakt wie zuvor (Single-DB).
"""
from __future__ import annotations

import threading

_state = threading.local()

# Diese Apps bleiben in 'default' (zentraler Session-/Steuer-Store).
PINNED_TO_DEFAULT = {"sessions"}


def set_db(alias: str) -> None:
    _state.alias = alias or "default"


def get_db() -> str:
    return getattr(_state, "alias", "default")


class TenantRouter:
    def _route(self, model):
        if model._meta.app_label in PINNED_TO_DEFAULT:
            return "default"
        return get_db()

    def db_for_read(self, model, **hints):
        return self._route(model)

    def db_for_write(self, model, **hints):
        return self._route(model)

    def allow_relation(self, *args, **kwargs):
        return True

    def allow_migrate(self, db, app_label, **hints):
        # Volle Schema-Kopie in jeder Mandanten-DB.
        return True
