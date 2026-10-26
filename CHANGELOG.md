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
  * Slogan „ELISA – Macht das Unsichtbare sichtbar.“ in README, CLAUDE.md
    und Footer (übersetzt: Making the invisible visible); Leitgedanke: begegnet
    der Überforderung in der Angstdomäne Functional Safety.
  * Eliezer jetzt auch in app/translate.py (ELIEZER_TRANSLATE_MODEL) und im
    eigenständigen rag/rag_normen.py.
  * Auslieferung als Podman-Image: Containerfile, compose.yaml,
    compose.podman.yaml, packaging/container-entrypoint.sh (web|mcp|worker),
    .env.example (fehlte bisher, deploy.sh verwies darauf), .containerignore;
    WhiteNoise für Static nur optional (ELISA_SERVE_STATIC=true, sonst nginx); elisa.env in .gitignore.
  * compose.yaml bindet Eliezer ein (Dienst "eliezer", Build aus ../eliezer,
    ELISA → http://eliezer:1234); compose.gpu.yaml reicht die AMD-GPU durch.
    PostgreSQL mit pgvector als Dienst "db"; django.contrib.postgres in
    INSTALLED_APPS (HnswIndex-Systemcheck).
  * Akronym festgelegt: ELISA = Engineering Lifecycle Insight for Safety
    Argumentation (README, CLAUDE.md, Login-Seite).
  * Metapaket elisa-stack (packaging/build-deb.sh): rootless Podman als
    www-data via Quadlet, Linger (Container laufen ohne Anmeldung), preinst
    holt install-as-www-data.sh von GitHub (Commit-SHA + SHA256) und baut die
    Images als www-data; postinst legt /etc/elisa/env an und rendert
    packaging/nginx/elisa-proxy.conf nach sites-available/<host.domain>.conf
    (+ sites-enabled).
  * Compose: Dienst "proxy" (nginx-unprivileged, Port 8080,
    packaging/nginx/elisa-compose.conf) liefert Static und proxyt web/mcp;
    compose.host-eliezer.yaml für einen Eliezer auf dem Host.
  * Fix: mcp auf <2 gepinnt (mcp 2.x entfernt mcp.server.fastmcp, der
    MCP-Container lief in eine Absturzschleife).
  * CSRF-Defaults um die Proxy-Origins (localhost:8080) erweitert.
  * Fix: Startseite warf 500 (KeyError MODTEST): die linke V-Seite zeigt nur
    die vier spezifizierenden Phasen (views.home), nicht alle acht.
  * Hinweis: nginx löst web/mcp beim Start auf – nach dem Neuerstellen dieser
    Container den Dienst "proxy" neu starten (sonst 502).
  * Persona "Salinar" heißt jetzt "Esra" (Esra, der Schriftgelehrte und
    Gesetzeskundige – passend zur Normenrecherche): Handle @esra, Modell
    EsraTask, MCP-Tools ask_esra / next_esra_task / complete_esra_task.
    Migration 0051 benennt Modell, Rollenbeschreibung, Token und Backend um
    (Token-Wert bleibt). Achtung: MCP-Clients, die die alten Tool-Namen
    verwenden, müssen angepasst werden.
  * Neuer Provider "Eliezer (lokal)" für Worker-Backends (OpenAI-Dialekt,
    Default-URL http://127.0.0.1:1234/v1, Key aus `eliezer --new-key`);
    Migration 0052. Neu angelegte System-Personas nutzen ihn automatisch, wenn
    LOCAL_LLM_BACKEND=eliezer gesetzt ist.
  * Navigation: Eintrag "Admin" (Verweis auf /admin/) im Profil-Pulldown für
    berechtigte Administratoren (is_staff oder Superuser); nicht mehr im
    Projektmenü oder als eigener Menüpunkt.
  * Personas mit biblischen Namen und Akronymen (app/personas.py): Lukas
    (RAG-Chat, vorher Wendelin), Esra, Tertius (@dragoman), Nathan (@auditor)
    sowie je V-Schritt Mose, Noah, Salomo, Hiram, Gideon, Josua, Daniel,
    Thomas. Der Chat stellt beim Anlegen alle Personas mit Akronym vor; die
    technischen Handles bleiben unverändert. Lokalisiert (gettext de/en):
    Vorstellung und Rollentexte folgen der Sprache der anlegenden Person, die
    Akronyme bleiben englisch.
  * Corporate Identity neu: Nachtblau (#1b2a41), Bernstein (#b45f06), warmes
    Papierweiß – die frühere Farbwelt war auf SALZ abgestimmt; Verweise auf
    CrystalKey entfernt.
  * Alte Persona-Namen aus dem System entfernt (Migration 0053): Dragoman ->
    Tertius (@tertius), Auditor -> Nathan (@nathan) bei Handle, Token,
    Worker-Backend, Rollenbeschreibung und alten Chat-Absendern (auch
    Wendelin -> Lukas, Salinar -> Esra). Die menschliche Projektrolle
    "Auditor" bleibt. Achtung: MCP-Clients mit Handle/Token-Namen der alten
    Personas müssen angepasst werden.
  * MCP: Streamable HTTP (…/<projekt>/<scope>/mcp) als Standard-Transport; der
    veraltete SSE-Transport ist per MCP_SSE_ENABLED=false abschaltbar (410).
    Worker nutzt Streamable HTTP (MCP_CLIENT_TRANSPORT=sse für SSE); Admin-
    Verbindungs-JSON und Plugin-Bundle folgen dem Schalter. Scope-/Schreib-
    Prüfung gilt für beide Transporte.
  * Fix: Worker-Backend "Eliezer (lokal)" ("Modelle abrufen" → Connection
    refused im Container): leere Base-URL folgt jetzt ELIEZER_BASE_URL (bzw.
    OLLAMA_HOST), ein leerer API-Key dem ELIEZER_API_KEY der Umgebung.
  * Fix: MCP-Middleware (Body-Replay) rief sich bei Streamable HTTP rekursiv selbst
    auf (RecursionError); ruft jetzt das ursprüngliche receive.
  * "Modelle abrufen" beim Provider Eliezer listet nur Sprachmodelle (Typ llm
    aus /api/v1/models), keine Embedding-/Bildmodelle.
  * Persona Lukas als System-Persona angelegt (@lukas, Token + Backend
    "Lukas (System)", Rollenbeschreibung LUKAS, Migration 0054) wie Esra,
    Tertius und Nathan; neu im Admin editierbar.
  * Chat: ↑/↓ in der Eingabe blättert durch die eigenen Nachrichten der Session
    (Entwurf bleibt erhalten). @all spricht alle Teilnehmer an (RAG-Chat,
    Item-Chat, MCP-Erwähnungen, Autocomplete); nur Menschen können @all
    auslösen (keine Persona-Endlosschleifen).
  * Chat: Administratoren sehen unter "Chats anderer Nutzer (Admin)" die
    persönlichen Chats der Mitglieder (nur Eigentümer, Datum, Anzahl – ohne
    Inhalt) und dürfen jeden Chat des Projekts löschen (Item-Chats nicht).
    Kopieren-Button an jeder Nachricht (kopiert den Rohtext).
  * MCP: neues Lese-Tool list_chats (Projekt-Chats, optional persönliche) und
    get_chat(session_id, after_id) zum fortlaufenden Mitlesen – z. B. durch
    Claude Code über einen READ-Token.
  * Sicherheit (MCP): Tool-Aufrufe mit Objekt-IDs ohne project_key (session_id,
    task_id, request_id, doc_id) werden gegen das Projekt des Tokens geprüft –
    ein Token von Projekt A kann keine Chats/Aufgaben/Dokumente von Projekt B
    mehr lesen oder ändern (System-Personas ausgenommen wie bisher).
  * Chat: einzelne Nachrichten löschbar (Papierkorb an der Nachricht; Admin
    jede, Eigentümer im persönlichen Chat jede, im Projekt-Chat PL jede und
    Mitglieder ihre eigenen; Item-Chats ausgenommen).
  * Fix: MCP get_chat/get_item_chat/list_*_mentions lieferten bei "sender" die
    Methoden-Repräsentation statt des Absendernamens (sender_label wurde nicht
    aufgerufen).
  * V-Schritt-Personas als eigene System-Personas angelegt (post_migrate): Mose
    (REQ), Noah (SPEC), Salomo (ARCH), Hiram (MOD), Gideon (MODTEST), Josua
    (INTTEST), Daniel (SYSTEST), Thomas (ACCTEST) – je Token "<Name> (System)" +
    WorkerBackend, Handle @mose … @thomas. Der Supervisor verbindet sie auf dem
    URL-Scope ihrer Phase (neu: modtest/inttest/systest/acctest als URL-Scope; die
    Teststufen bleiben keine Token-Scope-Dimension) und stellt ihrem Prompt Name
    und Akronym voran. Die Chat-Vorstellung nennt Handles und Verbindungsstatus.
  * Fix: Chat rendert jetzt Markdown (Fett, Listen, Zitate, Code, Tabellen) – auch
    Persona-Antworten und die Begrüßung; sicher bereinigt (bleach, kein rohes
    HTML), Mentions/Norm-Links bleiben, der Server liefert das HTML an Poll und
    Senden mit.
  * MCP: Streamable HTTP ist standardmäßig stateless (MCP_STATELESS=true) – Clients
    überleben einen Neustart des Servers (kein "Session not found" mehr).
  * Fix: Persona-Antworten im Chat – Noah schrieb auf „@all Hi" ein erfundenes
    Pflichtenheft. Der Worker hängt im Chat jetzt CHAT_MODE_RULES an (kurz,
    nur die gestellte Frage, keine Spezifikation/Items/Identifier ohne
    Auftrag, bei Smalltalk kurze Vorstellung); die System-Personas kennen Name und
    Akronym im Prompt.
  * Chat: Nachricht bearbeiten und neu senden (Stift an der eigenen Nachricht
    holt den Text ins Eingabefeld; Senden schickt sie neu).
  * Chat: Bezug sichtbar – Antworten der Personas zeigen „Antwort auf <Absender>:
    „…““ (neues Feld ChatMessage.reply_to, Migration 0055; post_chat(reply_to),
    list_my_chat_mentions liefert last_id).
  * Chat: implizite Adressierung – eine Nachricht ohne @ geht an die zuletzt
    angesprochene Persona, bis der Mensch jemand anderen anspricht (@all zählt
    einmalig); Chip „Schreibt mit: @…“ über dem Eingabefeld. Gleiche Regel im
    RAG-Chat-Server und im MCP (list_my_chat_mentions).
  * Chat-Persona gekürzt: V-Schritt-Personas bekommen im Chat nur Name, Akronym,
    Schritt und die Titelzeile ihrer Rolle (--chat-persona); der volle Prompt
    bleibt für Toasts/Editor. Verhindert erfundene Pflichtenhefte bei „Hi".
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
