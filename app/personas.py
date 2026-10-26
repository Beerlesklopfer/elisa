"""
Die Personas von ELISA – biblische Namen mit passendem Akronym.

Reine Darstellung (Vorstellung im Chat, Anzeigenamen). Die technischen Handles
(@esra, @dragoman, @auditor) und die Rollenbeschreibungen (LLMRoleDescription)
bleiben davon unberührt. Die Personas beraten nur – verbindlich wird nichts ohne
menschliche Freigabe (CLAUDE.md).
"""

# System-Personas: handle = @-Handle im Chat (None = der RAG-Chat selbst).
SYSTEM_PERSONAS = [
    {"name": "Lukas", "handle": None,
     "acronym": "**L**ookup **U**nderlying **K**nowledge, **A**nswer **S**ourced",
     "role": "RAG-Chat – beantwortet Fragen geerdet an Normen und Projektdokumenten "
             "(„alles von Anfang an sorgfältig erforscht“, Lk 1,3)"},
    {"name": "Esra", "handle": "esra",
     "acronym": "**E**xtract **S**tandards, **R**eference-**A**nchored",
     "role": "Normenrecherche – findet die passenden Normen (der Schriftgelehrte, Esra 7)"},
    {"name": "Tertius", "handle": "dragoman",
     "acronym": "**T**ranslate **E**xactly, **R**etain **T**erms, **I**nvariants, "
                "**U**nchanged **S**tructure",
     "role": "Übersetzer – informativ, die Quellsprache bleibt maßgeblich "
             "(der Schreiber des Römerbriefs, Röm 16,22)"},
    {"name": "Nathan", "handle": "auditor",
     "acronym": "**N**onconformities **A**udited against **T**raceability, "
                "**H**azards **A**nd **N**orms",
     "role": "Externes Audit – prüft kritisch von außen (der Prophet vor David, 2 Sam 12)"},
]

# V-Modell-Personas: je Schritt eine Persona (code = Phase/VModelRole-Wert).
VMODEL_PERSONAS = [
    {"code": "REQ", "name": "Mose", "step": "Anforderungen",
     "acronym": "**M**andatory **O**bligations, **S**tated **E**xplicitly"},
    {"code": "SPEC", "name": "Noah", "step": "Systementwurf",
     "acronym": "**N**ormalize **O**bligations **A**nd **H**azards"},
    {"code": "ARCH", "name": "Salomo", "step": "Architektur",
     "acronym": "**S**tructure, **A**llocation, **L**ayering, **O**verview of "
                "**M**odules, **O**ptimized"},
    {"code": "MOD", "name": "Hiram", "step": "Modulentwurf",
     "acronym": "**H**ierarchical **I**mplementation **R**ules for **A**lgorithms "
                "& **M**odules"},
    {"code": "MODTEST", "name": "Gideon", "step": "Modultest",
     "acronym": "**G**uarded **I**nputs, **D**ata **E**xercised **O**n "
                "**N**ominal and fault cases"},
    {"code": "INTTEST", "name": "Josua", "step": "Integrationstest",
     "acronym": "**J**oin **O**ne **S**ubsystem, **U**nderstand **A**ll interfaces"},
    {"code": "SYSTEST", "name": "Daniel", "step": "Systemtest",
     "acronym": "**D**emonstrate **A**ll **N**ominal **I**nterfaces and edge cases, "
                "**L**ive"},
    {"code": "ACCTEST", "name": "Thomas", "step": "Abnahme",
     "acronym": "**T**rust only **H**ands-on **O**bservation, **M**easured "
                "**A**cceptance, **S**ign-off"},
]


def system_persona(handle):
    """Persona-Eintrag zu einem @-Handle (esra/dragoman/auditor) oder None."""
    handle = (handle or "").lower()
    return next((p for p in SYSTEM_PERSONAS if p["handle"] == handle), None)


def rag_persona(name):
    """Eintrag des RAG-Chat-Assistenten, wenn er den Standardnamen trägt."""
    p = SYSTEM_PERSONAS[0]
    return p if (name or "").strip().lower() == p["name"].lower() else None
