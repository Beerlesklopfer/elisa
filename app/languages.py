"""
Sprach-Registry für die Mehrsprachigkeit.

Code (ISO 639-1) → (Anzeigename, Flaggen-Ländercode für flag-icons).
Die Flaggen liegen self-hosted unter static/vendor/flag-icons/.
"""
from __future__ import annotations

# code: (Name, Flaggen-CC)
LANGUAGES = {
    "de": ("Deutsch", "de"),
    "en": ("English", "gb"),
    "fr": ("Français", "fr"),
    "es": ("Español", "es"),
    "it": ("Italiano", "it"),
    "nl": ("Nederlands", "nl"),
    "pt": ("Português", "pt"),
    "pl": ("Polski", "pl"),
    "cs": ("Čeština", "cz"),
    "da": ("Dansk", "dk"),
    "sv": ("Svenska", "se"),
    "no": ("Norsk", "no"),
    "fi": ("Suomi", "fi"),
    "hu": ("Magyar", "hu"),
    "ro": ("Română", "ro"),
    "ru": ("Русский", "ru"),
    "tr": ("Türkçe", "tr"),
    "zh": ("中文", "cn"),
    "ja": ("日本語", "jp"),
}


def name(code: str) -> str:
    return LANGUAGES.get(code, (code, ""))[0]


def flag_cc(code: str) -> str:
    """Ländercode für die flag-icons-Klasse (fi fi-<cc>)."""
    return LANGUAGES.get(code, ("", code))[1] or code


def info(code: str) -> dict:
    n, cc = LANGUAGES.get(code, (code, code))
    return {"code": code, "name": n, "flag": cc}


def all_choices() -> list[dict]:
    """Alle bekannten Sprachen (für die Typable-Combobox)."""
    return [info(c) for c in LANGUAGES]


def expand(codes) -> list[dict]:
    """Liste von Codes → Infos (Name + Flagge), unbekannte werden durchgereicht."""
    return [info(c) for c in (codes or []) if c]
