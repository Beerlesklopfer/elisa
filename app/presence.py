"""
Leichte Anwesenheits-Erkennung („who is online") über den Prozess-Cache.

daphne läuft als Einzelprozess (siehe elisa.service), daher genügt der
Default-LocMemCache – kein zusätzliches Modell/Migration nötig. Jeder Request
eines angemeldeten Nutzers frischt einen Schlüssel mit TTL auf; „online" =
Schlüssel existiert noch. LLM-Teilnehmer gelten als online, wenn ihr MCP-Token
kürzlich benutzt wurde (`MCPToken.last_used`).
"""
from django.core.cache import cache

PRESENCE_TTL = 120          # Sekunden ohne Request → gilt als offline
_KEY = "seen:{}"


def mark_online(user) -> None:
    if user is not None and getattr(user, "is_authenticated", False):
        cache.set(_KEY.format(user.pk), True, PRESENCE_TTL)


def is_online(user_pk) -> bool:
    return bool(cache.get(_KEY.format(user_pk)))
