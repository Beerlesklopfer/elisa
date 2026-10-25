elisa (0.3.0) unstable; urgency=medium

  Umbenennung der Anwendung von Spec-Anvil in ELISA.

  * Django-Projektpaket specanvil/ -> elisa/ (settings, urls, wsgi, asgi,
    DJANGO_SETTINGS_MODULE in manage.py und mcp_server).
  * systemd-/nginx-Units umbenannt (elisa.service, elisa-mcp.service,
    elisa-worker.service, elisa-ollama.service, elisa.nginx.conf);
    FHS-Pfade /usr/share|/etc|/var/lib|/var/log/elisa, deploy.sh angepasst.
  * Umgebungsvariablen SPECANVIL_* -> ELISA_*; DB-Name/-User-Default "elisa".
  * Anzeigename, Texte, Übersetzungen, Export-Typ-Präfix (elisa-<typ>) und
    Doku (README, CLAUDE.md) auf ELISA umgestellt.
  * Hartkodierte Domain-Verweise entfernt (Mail-/Host-Defaults: localhost bzw.
    example.com; per Umgebungsvariablen konfigurierbar).
  * Firmenbranding entfernt (Logo, Anschrift, Kontakt, Firmenbezeichner);
    CSS-Variablen --elisa-*, Setting ELISA_REFERENCE_DOCX. Die Word-Vorlage
    docs_templates/elisa-reference.docx ist nicht mehr enthalten und muss für
    die Dokumentgenerierung bereitgestellt werden.
  * Leitbild „Herr, öffne ihm die Augen!" (2 Kön 6,17) in README und
    CLAUDE.md: ELISA macht in der Angstdomäne Functional Safety sichtbar, was
    verborgen ist.
  * Eliezer-Anbindung (GPU-Modellmanager, OpenAI-Dialekt): neues Modul
    app/local_llm.py mit Umschalter LOCAL_LLM_BACKEND=ollama|eliezer für
    Embeddings (rag_service), RAG-Chat (views_chat) und Notnagel-Toasts
    (views_feedback). Einstellungen ELIEZER_BASE_URL, ELIEZER_API_KEY (nur
    Umgebung), ELIEZER_CHAT_MODEL, ELIEZER_EMBED_MODEL, ELIEZER_TIMEOUT.
    Default bleibt ollama; Provenienz (llm_model) folgt LOCAL_CHAT_MODEL.
  * Defaults auf localhost: DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,
    ELISA_BIND_ADDRESS=127.0.0.1, MCP_PUBLIC_BASE=http://localhost/mcp.
  * .mcp.json (enthält Bearer-Token) aus dem Repository ausgeschlossen.

 -- Jörg Bernau <Joerg.Bernau@onesimus.io>  Sun, 25 Oct 2026 13:30:00 +0100

spec-anvil (0.2.0) unstable; urgency=medium

  Rechte V-Modell-Seite jetzt auch im Datenmodell abgebildet (vorher nur Scope).

  * WorkItem.phase um die vier Teststufen erweitert (MODTEST, INTTEST, SYSTEST,
    ACCTEST); max_length 5→8. MCPToken-Scope bleibt bewusst auf die linke Seite
    beschränkt (passt zu server.py VALID_SCOPES).
  * Neue Verifikations-Kante WorkItem.verifies / verified_by: ein Test-Item
    verifiziert Entwicklungs-Items seiner Partnerebene (VERIFY_PARTNER:
    MOD↔MODTEST, ARCH↔INTTEST, SPEC↔SYSTEST, REQ↔ACCTEST).
  * Abdeckung: is_orphan ist phasenbewusst (rechts: Test ohne verifies);
    neues is_unverified (Entwicklungs-Item ohne prüfendes Test-Item).
  * Worktree: Items auf der rechten Seite anlegbar (alle Ebenen außer REQ);
    Identifier-Präfixe MT/IT/ST/AT (kollidieren nicht mit R/S/A/M).
  * Item-Ansicht: Verifikations-Referenzen („Verifiziert" / „Verifiziert durch")
    anzeig- und pflegbar (workitem_ref um verifies/verified_by erweitert).
  * Doku/Skill/Kommentare auf „gesamtes V-Modell" angeglichen (README,
    CHANGELOG, CLAUDE.md, traceability-Skill, views/llm_roles).
  * Migration 0050 (workitem.verifies + phase-choices/max_length).

  Regeln/Doku:
  * CLAUDE.md: verbindliche Regel „Jeder Push schreibt das CHANGELOG fort"
    (Debian-Stil).

 -- Jörg Bernau <Joerg.Bernau@onesimus.io>  Wed, 10 Jun 2026 00:04:22 +0200

spec-anvil (0.1.0) unstable; urgency=medium

  Erste versionierte Fassung (Branch development). Teilautomatisierung des
  gesamten V-Modells (REQ→SPEC→ARCH→MOD und die zugehörigen Teststufen
  MODTEST/INTTEST/SYSTEST/ACCTEST) mit Norm-Bezug nach IEC 61508.

  Kern:
  * Deterministischer Django-Kern als alleinige Quelle der Wahrheit; LLMs
    laufen ausschließlich beratend (Provenienz an jedem maschinellen Beitrag).
  * Statusautomat Entwurf → Vorgeschlagen → Freigegeben; Freigabe rein
    menschlich (APPROVED erfordert menschlichen approved_by).
  * Traceability über selbstreferenzierende WorkItem-Hierarchie inkl.
    Orphan-/Abdeckungsprüfung als nachprüfbare DB-Logik.

  Arbeitsbereich (Workspace):
  * Gliederung/Identifier-Nummerierung (S4.1.1 …) per Kontextmenü und
    Tastatur (Strg+ / Strg+Shift+), Anlegen auch im leeren Projekt.
  * Tree-Navigation: ALT-Pfeile (Geschwister/Tiefe), ALT-Bild↑/↓ lineares
    Durchblättern, ALT+⌫ / Strg+ALT+⌫ Sprung-Historie vor/zurück.
  * WYSIWYG-Editor (Markdown, Mermaid, eingebettete Bilder/Tabellen);
    EmbeddedImage-Anhang am Dokumentende mit Nummer, Caption, Urheberangabe.
  * Hover-Hilfe mit Tastenkürzel-Übersicht am Arbeitsbereich-Titel.

  Personas & Chat:
  * Acht V-Schritt-Personas plus globale System-Personas Salinar
    (Normenrecherche), Dragoman (Übersetzer), Auditor (Audit); lokaler
    RAG-Norm-Assistent „Wendelin".
  * MCP-SSE-Server mit Bearer-Token je Projekt/Scope; Supervisor startet je
    WorkerBackend einen Persona-Worker (lokale und externe Modelle).
  * Lokal/Extern-Marker je Persona (Provider bzw. DNS-Auflösung der base_url);
    eine lokale Persona kann eine externe um externe Verifikation bitten.
  * Inter-Persona-Dialog; Personas adressieren Absender per echtem @handle
    statt generischem „@Mensch".
  * Begrüßung in neuem RAG-Chat durch Wendelin (stellt Teilnehmer vor),
    ohne dabei selbst Persona-Antworten auszulösen.
  * Chat-Verbesserungen: per-Provider-Sprechblasenfarben, Absender-Icons,
    @-Wake-Character-Autocomplete, Zitier-Kontextmenü, Chat umbenennen,
    Typ-Unterscheidung (Projekt-/RAG-Chat), auto-wachsende Eingabezeile.

  Normen, RAG, Mehrsprachigkeit:
  * Norm- und projektbezogenes RAG (Ollama-Embeddings); Schlagwortkatalog.
  * Informative Übersetzungen je Nutzer (ItemTranslation, asynchron via
    Dragoman); normative Quellsprache wird nie übersetzt.
  * UI-Internationalisierung (de Quelle, en vollständig gepflegt).

  Betrieb:
  * Vier systemd-Dienste (Web/daphne, MCP, Worker, Ollama) hinter nginx;
    Installation via deploy.sh.
  * Asset-Cache-Busting (?v=<mtime>) und NoCacheHTMLMiddleware, damit der
    Browser nach einem Deploy sofort frische Assets lädt.

 -- Jörg Bernau <Joerg.Bernau@onesimus.io>  Tue, 09 Jun 2026 23:48:45 +0200
