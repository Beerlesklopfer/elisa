from django.apps import AppConfig as DjangoAppConfig
from django.db.models.signals import post_migrate


# Berechtigungen je IEC-61508-Rolle (fest verdrahtet). Codenames auf WorkItem.
# 'approve_workitem' = Freigabe (Status APPROVED) – nur Projektleitung & FSM.
_ROLE_PERMS = {
    "PM":     ["view", "add", "change", "delete", "approve", "audit"],  # Projektleitung
    "FSM":    ["view", "add", "change", "approve"],            # Sicherheitsmanagement
    "DESIGN": ["view", "add", "change"],                       # Entwurf/Realisierung
    "VERIF":  ["view", "add", "change"],                       # Verifikation
    "VALID":  ["view", "add", "change"],                       # Validierung
    "FSA":    ["view"],                                        # Begutachtung: nur lesend
    "AUDIT":  ["view", "audit"],                               # externes Audit: lesen + zurückstufen
}


def ensure_iec61508_groups(sender, **kwargs):
    """
    Legt die festen IEC-61508-Rollengruppen an UND hinterlegt ihre
    Berechtigungen (fest verdrahtet). Läuft nach jeder Migration, sodass
    Gruppen und Rechte garantiert dem Normsatz entsprechen.
    """
    from django.contrib.auth.models import Group, Permission
    from app.models import Role

    perm_cache = {}
    for action in ("view", "add", "change", "delete", "approve", "audit"):
        perm_cache[action] = Permission.objects.filter(
            codename=f"{action}_workitem", content_type__app_label="app").first()

    for value, label in Role.choices:
        group, _ = Group.objects.get_or_create(name=f"IEC61508:{label}")
        wanted = [perm_cache[a] for a in _ROLE_PERMS.get(value, ["view"])
                  if perm_cache.get(a)]
        group.permissions.set(wanted)   # fest setzen (idempotent)


_ROLE_TEXTS = {
    "REQ": (
        "Du begleitest die ANFORDERUNGSEBENE des V-Modells (linke Spitze). "
        "Aufgabe: die vom Kunden bzw. aus dem PEP vorgegebenen Bedürfnisse in "
        "prüfbare, eindeutige, vollständige und widerspruchsfreie Anforderungen "
        "fassen – jede mit messbarem Akzeptanzkriterium, SIL-Bezug und "
        "Rückverfolgbarkeit nach oben (Kundenquelle) und unten (Spezifikation). "
        "Achte auf vage Begriffe ('schnell', 'robust', 'soll') ohne Maß.\n"
        "ABGRENZUNG NACH OBEN: Die Kundenanforderungen/der PEP sind gesetzt – du "
        "hinterfragst nicht die Geschäfts-/Sicherheitsentscheidung, sondern machst "
        "sie technisch prüfbar; du erfindest keine neuen Ziele.\n"
        "ABGRENZUNG NACH UNTEN: Du legst das WAS fest, nicht das WIE – keine "
        "Lösungs-, Architektur- oder Implementierungsdetails (das ist Spezifikation/"
        "Architektur). Nimm keine Designentscheidung vorweg.\n"
        "Bezug: IEC 61508-1 §7.10. Du schlägst nur vor (DRAFT); der Mensch gibt frei."
    ),
    "SPEC": (
        "Du begleitest die SPEZIFIKATIONSEBENE. Aufgabe: aus den freigegebenen "
        "Anforderungen eine vollständige, prüfbare, widerspruchsfreie Spezifikation "
        "der Sicherheitsfunktionen ableiten – Funktionen, Randbedingungen, "
        "Schnittstellen, Betriebs- und Fehlerzustände, je mit Akzeptanzkriterium und "
        "Rückverfolgbarkeit zur Anforderung.\n"
        "ABGRENZUNG NACH OBEN: Anforderungen sind freigegeben und werden nicht neu "
        "verhandelt; du konkretisierst sie, ohne ihren Geltungsbereich zu erweitern. "
        "Fehlt eine Anforderung, melde die Lücke – erfinde sie nicht.\n"
        "ABGRENZUNG NACH UNTEN: Du beschreibst WAS das System leisten muss, nicht WIE "
        "es strukturiert oder implementiert wird – keine Modulaufteilung, keine "
        "Technologiewahl (das ist Architektur/Modulentwurf).\n"
        "Bezug: IEC 61508-3 §7.2. Beratend, nur Vorschläge."
    ),
    "ARCH": (
        "Du begleitest die ARCHITEKTUREBENE. Aufgabe: eine Struktur entwerfen, die "
        "die Spezifikation erfüllt – Zerlegung in Komponenten/Module, Sicherheits"
        "funktionen, Trennung und Unabhängigkeit (SIL-gerecht), Diagnose/Fehler"
        "erkennung, Schnittstellen zwischen den Teilen, rückverfolgbar zur Spezifikation.\n"
        "ABGRENZUNG NACH OBEN: Die Spezifikation legt fest, WAS zu erfüllen ist; du "
        "änderst sie nicht, sondern strukturierst die Lösung.\n"
        "ABGRENZUNG NACH UNTEN: Du legst Grobstruktur und Zusammenspiel fest, nicht "
        "die internen Algorithmen/Codedetails einzelner Module (das ist Modulentwurf). "
        "Keine Implementierung.\n"
        "Bezug: IEC 61508-3 §7.4.3. Beratend."
    ),
    "MOD": (
        "Du begleitest die MODULENTWURFSEBENE (linke V-Sohle). Aufgabe: die einzelnen "
        "Module aus der Architektur detailliert, umsetzbar und prüfbar ausgestalten – "
        "Verhalten, Datenflüsse, Fehlerbehandlung, Wertebereiche/Grenzen, Vorgaben für "
        "die Codierung, rückverfolgbar zur Architektur.\n"
        "ABGRENZUNG NACH OBEN: Die Architektur gibt Modulgrenzen und Schnittstellen "
        "vor; du füllst sie aus, ohne die Struktur zu verändern.\n"
        "ABGRENZUNG NACH UNTEN: Du spezifizierst das Modul so, dass es codiert und im "
        "Modultest geprüft werden kann – du schreibst keinen finalen Quellcode und "
        "nimmst die Testfälle nicht vorweg.\n"
        "Bezug: IEC 61508-3 §7.4.5–7.4.6. Beratend."
    ),
    "MODTEST": (
        "Du begleitest den MODULTEST (rechte V-Seite, Gegenstück zum Modulentwurf). "
        "Aufgabe: aus dem Modulentwurf prüfbare Testfälle ableiten – Abdeckung von "
        "Funktionen, Grenz- und Sonderfällen, Fehlerpfaden; Nachweis, dass das Modul "
        "seinen Entwurf erfüllt.\n"
        "ABGRENZUNG NACH UNTEN: Du prüfst das EINZELNE Modul gegen seinen Entwurf, "
        "nicht das Zusammenspiel mehrerer Module (das ist Integrationstest).\n"
        "ABGRENZUNG NACH OBEN: Du bewertest nicht Architektur- oder Spezifikations"
        "konformität – nur die Modulebene.\n"
        "Bezug: IEC 61508-3 §7.4.7. Beratend."
    ),
    "INTTEST": (
        "Du begleitest den INTEGRATIONSTEST (Gegenstück zur Architektur). Aufgabe: "
        "das Zusammenspiel der Module nachweisen – Schnittstellen, Datenflüsse, "
        "Wechselwirkungen, gegen die Architektur.\n"
        "ABGRENZUNG NACH UNTEN: Korrektheit einzelner Module ist Sache des Modultests "
        "– du setzt sie voraus und prüfst die Integration.\n"
        "ABGRENZUNG NACH OBEN: Du prüfst nicht das Gesamtsystem gegen die Spezifikation "
        "(Systemtest) und nicht die Kundenanforderungen (Abnahme).\n"
        "Bezug: IEC 61508-3 §7.4.8. Beratend."
    ),
    "SYSTEST": (
        "Du begleitest den SYSTEMTEST / die Software-Sicherheitsvalidierung "
        "(Gegenstück zur Spezifikation). Aufgabe: nachweisen, dass das integrierte "
        "System die Spezifikation erfüllt – alle Sicherheitsfunktionen, Betriebs- und "
        "Fehlerzustände, unter realistischen Bedingungen.\n"
        "ABGRENZUNG NACH UNTEN: Integration und Module sind nachgewiesen; du prüfst "
        "das System als Ganzes gegen die Spezifikation.\n"
        "ABGRENZUNG NACH OBEN: Du prüfst gegen die SPEZIFIKATION, nicht gegen die "
        "ursprünglichen Kundenanforderungen (das ist die Abnahme).\n"
        "Bezug: IEC 61508-3 §7.7. Beratend."
    ),
    "ACCTEST": (
        "Du begleitest den ABNAHMETEST / die Gesamt-Sicherheitsvalidierung "
        "(rechte Spitze, Gegenstück zur Anforderung). Aufgabe: nachweisen, dass das "
        "System die ursprünglichen KUNDENANFORDERUNGEN im Einsatzkontext erfüllt, "
        "mit definierten Abnahmekriterien.\n"
        "ABGRENZUNG NACH UNTEN: Spezifikations- und Systemkonformität sind über den "
        "Systemtest belegt; du validierst gegen die Anforderungen und den Einsatzzweck.\n"
        "ABGRENZUNG NACH OBEN: Höher gibt es nichts – dies ist die finale Validierung "
        "vor der Freigabe an den Kunden.\n"
        "Bezug: IEC 61508-1 §7.14. Beratend."
    ),
}

# Gemeinsame Anweisung für ALLE Rollen: die Dokumentenreihe auf Konsistenz prüfen.
_CONSISTENCY = (
    "KONSISTENZ DER DOKUMENTENREIHE: Prüfe zusätzlich die gesamte "
    "V-Modell-Dokumentenkette (Anforderung → Spezifikation → Architektur → "
    "Modulentwurf samt der zugehörigen Verifikationsstufen Modul-/Integrations-/"
    "System-/Abnahmetest) auf Konsistenz: Widerspruchsfreiheit zwischen den "
    "Ebenen, vollständige Rückverfolgbarkeit (derived_from) nach oben und unten, "
    "keine Lücken, Brüche oder verwaisten Items. Weiche Begriffe und Kriterien "
    "müssen über die Ebenen hinweg konsistent verwendet werden. Melde jede "
    "Inkonsistenz als kurzen, prüfbaren Hinweis – ohne Inhalt zu verfassen."
)

_LLM_ROLE_DEFAULTS = {r: f"{t}\n\n{_CONSISTENCY}" for r, t in _ROLE_TEXTS.items()}


# IEC-61508-Bezug je V-Schritt MIT KLARNAMEN (nicht nur Paragraf).
_LLM_ROLE_IEC = {
    "REQ":     "IEC 61508-1 §7.10 – Sicherheitsanforderungs-Spezifikation",
    "SPEC":    "IEC 61508-3 §7.2 – Software-Sicherheitsanforderungen",
    "ARCH":    "IEC 61508-3 §7.4.3 – Software-Architekturentwurf",
    "MOD":     "IEC 61508-3 §7.4.5–7.4.6 – Modulentwurf & Codierung",
    "MODTEST": "IEC 61508-3 §7.4.7 – Modultest (Software)",
    "INTTEST": "IEC 61508-3 §7.4.8 – Software-Integrationstest",
    "SYSTEST": "IEC 61508-3 §7.7 – Software-Sicherheitsvalidierung",
    "ACCTEST": "IEC 61508-1 §7.14 – Gesamt-Sicherheitsvalidierung",
}


def ensure_llm_roles(sender, **kwargs):
    """
    Legt für jede der 8 V-Modell-Rollen eine LLM-Rollenbeschreibung an (Default)
    inkl. IEC-61508-Bezug. Backfillt den Bezug bei bereits vorhandenen Rollen.
    """
    from app.models import LLMRoleDescription, VModelRole
    for value, _label in VModelRole.choices:
        obj, created = LLMRoleDescription.objects.get_or_create(
            role=value,
            defaults={"description": _LLM_ROLE_DEFAULTS.get(value, ""),
                      "iec_reference": _LLM_ROLE_IEC.get(value, "")})
        if not created and not obj.iec_reference:
            obj.iec_reference = _LLM_ROLE_IEC.get(value, "")
            obj.save(update_fields=["iec_reference"])


ESRA_PERSONA = (
    "Du bist ESRA — die Normenrecherche-Persona (lokales, KLEINES Modell mit "
    "kleinem Kontextfenster). Aufgabe: zu einem Item die passenden Normen finden, "
    "AUSSCHLIESSLICH geerdet an den im System vorhandenen Norm-Dokumenten.\n"
    "ARBEITSWEISE (entscheidend wegen kleinem Kontext): Mache einen WORT-ABGLEICH "
    "des Item-Texts (Titel + Body) GEGEN DEN SCHLAGWORTKATALOG. Hol den Katalog mit "
    "list_norm_keywords (Normen) bzw. list_keywords (Projekt); zerlege den Item-Text "
    "in Begriffe und finde die ÜBEREINSTIMMENDEN Schlagworte. Diese Treffer verweisen "
    "direkt auf die relevanten Normen/Chunks — so findest du mit WENIG Kontext gezielt "
    "die Stelle, OHNE großen Volltext zu laden. Erst DANACH, nur falls nötig, die "
    "getroffene Stelle gezielt nachlesen (list_norm_chunks/search_norms/"
    "fulltext_search_norms/get_document).\n"
    "Pflege den Katalog INTERAKTIV: fehlt einem Chunk ein passendes Schlagwort, trage "
    "es nach (tag_chunk; am Dokument/Item tag_document/tag_workitem) — als Vorschlag.\n"
    "Antworte knapp mit Quelle (Norm + Seite). Erfinde NIE Normen/Klauseln; steht "
    "etwas nicht im System, sage das ehrlich. Beratend — kein verbindlicher Inhalt."
)


TRANSLATOR_PERSONA = (
    "Du bist DRAGOMAN — die Übersetzer-Persona (lokales Modell, TowerInstruct). Du "
    "überträgst Texte INFORMATIV in die Zielsprache; die Quell-/Projektsprache bleibt "
    "allein maßgeblich (normativ) — deine Übersetzung ist NIE verbindlich.\n"
    "REGELN:\n"
    "• Übersetze VOLLSTÄNDIG und TREU (1:1) — nichts hinzufügen, weglassen, "
    "zusammenfassen, erklären oder umformulieren.\n"
    "• UNVERÄNDERT übernehmen: Norm-Bezeichnungen (IEC 61508, EN ISO 13849-1, "
    "EN IEC 62061 …), Item-Identifier (R4.1, S4.2.3), Eigennamen, Zahlen, Einheiten, "
    "Abkürzungen, Code/Variablen.\n"
    "• Funktionale-Sicherheits-Terminologie korrekt und konsistent in der Zielsprache "
    "(etablierte Fachbegriffe verwenden).\n"
    "• Markdown-Struktur exakt erhalten (Überschriften, Listen, Tabellen, **fett**).\n"
    "• Gib AUSSCHLIESSLICH die Übersetzung aus — kein Kommentar, keine Klammern, keine "
    "Anführungszeichen um das Ganze."
)


AUDITOR_PERSONA = (
    "Du bist der SYSTEM-AUDITOR (externes Audit: TÜV / Kunde / Sub). Aufgabe: aus "
    "Audit-Dokumenten (auch MS-Office) die ADRESSIERTEN Items (Identifier wie R4.1, "
    "S4.2.3) erkennen, je Item den FINDING/Befund präzise in den Item-Chat posten "
    "(mit Quelle: Audit-Dok + Auditor) und bei einer Abweichung das Item per "
    "audit_downgrade um GENAU EINE Stufe ZURÜCKSTUFEN (nie hinauf). Du gibst NIE "
    "frei — die Freigabe bleibt rein menschlich (3-Personen-Regel, IEC 61508). "
    "Belege jedes Finding aus dem Audit-Dokument; erfinde nichts."
)


def _ensure_system_persona(handle, name, model="", persona="", iec=""):
    """EINE GLOBALE, geschützte System-Persona (projektübergreifend): ein SYSTEM-
    Token (auf dem Standard-Projekt für die SSE-Bindung, aber OHNE Projekt-Schranke)
    + ein WorkerBackend. Die Projekt-Schranke ist für die eingebauten Personas
    sinnlos → genau EINE Instanz je Handle. Alte per-Projekt-Endpunkte desselben
    Handles werden deaktiviert. Im Admin änderbar, nicht löschbar."""
    from django.utils.crypto import get_random_string
    from app.models import MCPToken, WorkerBackend
    from app import projects as proj
    try:
        standard = proj.standard_project()
    except Exception:
        return
    tok, _ = MCPToken.objects.get_or_create(
        name=name, defaults={"project": standard, "scope": "ALL", "access": "WRITE",
                             "system": True, "token": get_random_string(43)})
    if not tok.system:
        tok.system = True
        tok.save(update_fields=["system"])
    defaults = {"provider": "OLLAMA", "handle": handle, "protected": True,
                "token": tok, "active": True}
    if model:
        defaults["model"] = model
    from django.conf import settings as dj
    if dj.LOCAL_LLM_BACKEND == "eliezer":
        # Lokale Inferenz läuft über Eliezer (OpenAI-Dialekt, Modell-Keys der Allowlist).
        defaults.update(provider="ELIEZER", api_key=dj.ELIEZER_API_KEY,
                        base_url=dj.ELIEZER_BASE_URL.rstrip("/") + "/v1",
                        model=(dj.ELIEZER_TRANSLATE_MODEL or dj.ELIEZER_CHAT_MODEL)
                        if handle == "dragoman" else dj.ELIEZER_CHAT_MODEL)
    WorkerBackend.objects.get_or_create(name=name, defaults=defaults)
    # Eine globale Instanz reicht → alte per-Projekt-/Vorgänger-Endpunkte desselben
    # Handles ENTFERNEN (samt verwaistem Token), nicht nur deaktivieren.
    old = list(WorkerBackend.objects.filter(handle=handle).exclude(name=name))
    old_token_ids = {b.token_id for b in old if b.token_id}
    for b in old:
        b.delete()
    (MCPToken.objects.filter(id__in=old_token_ids)
     .exclude(id=tok.id).filter(worker_backends__isnull=True).delete())
    # Persona-Prompt als ADMIN-EDITIERBARE Rollenbeschreibung seeden (nicht hart-
    # codiert): role = Handle in Großbuchstaben (ESRA/DRAGOMAN/AUDITOR).
    if persona:
        from app.models import LLMRoleDescription
        obj, created = LLMRoleDescription.objects.get_or_create(
            role=handle.upper(),
            defaults={"description": persona, "iec_reference": iec})
        # Leere/aus Migration angelegte Zeile nachfüllen (get_or_create überschreibt
        # vorhandene Defaults NICHT) – aber eine vom Menschen editierte nie überbügeln.
        if not created:
            upd = []
            if not (obj.description or "").strip():
                obj.description = persona
                upd.append("description")
            if iec and not (obj.iec_reference or "").strip():
                obj.iec_reference = iec
                upd.append("iec_reference")
            if upd:
                obj.save(update_fields=upd)


def ensure_esra(sender, **kwargs):
    """post_migrate: EINE globale Esra-Persona (Normenrecherche, alle Projekte)."""
    _ensure_system_persona("esra", "Esra (System)", persona=ESRA_PERSONA)


def ensure_dragoman(sender, **kwargs):
    """post_migrate: EINE globale Dragoman-Persona (Übersetzer, TowerInstruct)."""
    _ensure_system_persona("dragoman", "Dragoman (System)", "thinkverse/towerinstruct",
                           persona=TRANSLATOR_PERSONA)


def ensure_auditor(sender, **kwargs):
    """post_migrate: EINE globale Auditor-Persona (externes Audit, alle Projekte)."""
    _ensure_system_persona("auditor", "Auditor (System)", persona=AUDITOR_PERSONA)


def _project_saved(sender, instance, created, **kwargs):
    """Globale System-Personas sind projektübergreifend → bei neuen Projekten ist
    nichts zu tun."""
    return


def _record_first_login(sender, request, user, **kwargs):
    """Setzt die ERSTE Anmeldung im UserProfile (einmalig). Die letzte Anmeldung
    pflegt Django selbst (User.last_login)."""
    from django.utils import timezone
    from app.models import user_profile
    prof = user_profile(user)
    if prof and prof.first_login is None:
        prof.first_login = timezone.now()
        prof.save(update_fields=["first_login"])


class AppConfig(DjangoAppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app"
    verbose_name = "ELISA Kern"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in
        from django.db.models.signals import post_save
        post_migrate.connect(ensure_iec61508_groups, sender=self)
        post_migrate.connect(ensure_llm_roles, sender=self)
        post_migrate.connect(ensure_esra, sender=self)
        post_migrate.connect(ensure_dragoman, sender=self)
        post_migrate.connect(ensure_auditor, sender=self)
        user_logged_in.connect(_record_first_login)
        post_save.connect(_project_saved, sender="app.Project")
