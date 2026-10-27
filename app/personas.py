"""
Die Personas von ELISA – biblische Namen mit passendem Akronym.

Reine Darstellung (Vorstellung im Chat, Anzeigenamen). Die technischen Handles
(@esra, @tertius, @nathan) und die Rollenbeschreibungen (LLMRoleDescription)
bleiben davon unberührt. Die Personas beraten nur – verbindlich wird nichts ohne
menschliche Freigabe (CLAUDE.md).
"""
from django.utils.translation import gettext_lazy as _

# System-Personas: handle = @-Handle im Chat.
SYSTEM_PERSONAS = [
    {"name": "Lukas", "handle": "lukas",
     "acronym": "**L**ookup **U**nderlying **K**nowledge, **A**nswer **S**ourced",
     "role": _("RAG-Chat – beantwortet Fragen geerdet an Normen und Projektdokumenten "
             "(„alles von Anfang an sorgfältig erforscht“, Lk 1,3)")},
    {"name": "Esra", "handle": "esra",
     "acronym": "**E**xtract **S**tandards, **R**eference-**A**nchored",
     "role": _("Normenrecherche – findet die passenden Normen (der Schriftgelehrte, Esra 7)")},
    {"name": "Tertius", "handle": "tertius",
     "acronym": "**T**ranslate **E**xactly, **R**etain **T**erms, **I**nvariants, "
                "**U**nchanged **S**tructure",
     "role": _("Übersetzer – informativ, die Quellsprache bleibt maßgeblich "
             "(der Schreiber des Römerbriefs, Röm 16,22)")},
    {"name": "Nathan", "handle": "nathan",
     "acronym": "**N**onconformities **A**udited against **T**raceability, "
                "**H**azards **A**nd **N**orms",
     "role": _("Externes Audit – prüft kritisch von außen (der Prophet vor David, 2 Sam 12)")},
]

# V-Modell-Personas: je Schritt eine Persona (code = Phase/VModelRole-Wert).
VMODEL_PERSONAS = [
    {"code": "REQ", "name": "Mose", "handle": "mose", "step": _("Anforderungen"),
     "acronym": "**M**andatory **O**bligations, **S**tated **E**xplicitly"},
    {"code": "SPEC", "name": "Noah", "handle": "noah", "step": _("Systementwurf"),
     "acronym": "**N**ormalize **O**bligations **A**nd **H**azards"},
    {"code": "ARCH", "name": "Salomo", "handle": "salomo", "step": _("Architektur"),
     "acronym": "**S**tructure, **A**llocation, **L**ayering, **O**verview of "
                "**M**odules, **O**ptimized"},
    {"code": "MOD", "name": "Hiram", "handle": "hiram", "step": _("Modulentwurf"),
     "acronym": "**H**ierarchical **I**mplementation **R**ules for **A**lgorithms "
                "& **M**odules"},
    {"code": "MODTEST", "name": "Gideon", "handle": "gideon", "step": _("Modultest"),
     "acronym": "**G**uarded **I**nputs, **D**ata **E**xercised **O**n "
                "**N**ominal and fault cases"},
    {"code": "INTTEST", "name": "Josua", "handle": "josua", "step": _("Integrationstest"),
     "acronym": "**J**oin **O**ne **S**ubsystem, **U**nderstand **A**ll interfaces"},
    {"code": "SYSTEST", "name": "Daniel", "handle": "daniel", "step": _("Systemtest"),
     "acronym": "**D**emonstrate **A**ll **N**ominal **I**nterfaces and edge cases, "
                "**L**ive"},
    {"code": "ACCTEST", "name": "Thomas", "handle": "thomas", "step": _("Abnahme"),
     "acronym": "**T**rust only **H**ands-on **O**bservation, **M**easured "
                "**A**cceptance, **S**ign-off"},
]


def system_persona(handle):
    """Persona-Eintrag zu einem @-Handle (esra/tertius/nathan) oder None."""
    handle = (handle or "").lower()
    return next((p for p in SYSTEM_PERSONAS if p["handle"] == handle), None)


def rag_persona(name):
    """Eintrag des RAG-Chat-Assistenten, wenn er den Standardnamen trägt."""
    p = SYSTEM_PERSONAS[0]
    return p if (name or "").strip().lower() == p["name"].lower() else None


def vmodel_persona(handle):
    """V-Schritt-Persona zu einem @-Handle (mose/noah/…) oder None."""
    handle = (handle or "").lower()
    return next((p for p in VMODEL_PERSONAS if p["handle"] == handle), None)


def tooltip(handle):
    """Vorstellung für den Hover (Tooltip): Name, Akronym und Aufgabe der Persona –
    leer, wenn der Handle keine Persona ist."""
    from django.utils.translation import gettext as _
    handle = (handle or "").lstrip("@").lower()
    sp = system_persona(handle)
    if sp:
        return f"{sp['name']} — {plain(sp['acronym'])}\n{sp['role']}"
    vp = vmodel_persona(handle)
    if vp:
        return (f"{vp['name']} — {plain(vp['acronym'])}\n"
                f"{_('V-Schritt')}: {vp['step']} ({vp['code']})")
    return ""


def plain(text):
    """Akronym ohne Markdown-Fettung (für Prompts)."""
    return str(text).replace("**", "")
