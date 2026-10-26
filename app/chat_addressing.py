"""
Wer ist in einem Chat gemeint? Explizit per @handle – und IMPLIZIT: eine Nachricht
ohne @-Erwähnung gilt dem zuletzt angesprochenen Teilnehmer, bis der Mensch jemand
anderen anspricht (wer mit einer Persona chattet, muss sie nicht jedes Mal
adressieren). @all ist einmalig und wird nicht fortgeschrieben.
"""
import re

MENTION_RX = re.compile(r"@([\w\-äöüÄÖÜß]+)")


def mentions(text):
    """Alle @handles (klein) in einem Text."""
    return {m.lower() for m in MENTION_RX.findall(text or "")}


def implicit_addressees(prior_messages):
    """Handles, an die eine NEUE Nachricht ohne @ geht: die Erwähnungen der jüngsten
    menschlichen Nachricht davor, die jemanden angesprochen hat (ohne @all).
    `prior_messages` = frühere Nachrichten in zeitlicher Reihenfolge."""
    for m in reversed(list(prior_messages)):
        if getattr(m, "role", "") == "USER":
            tagged = mentions(m.content) - {"all"}
            if tagged:
                return tagged
    return set()
