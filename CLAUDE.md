# CLAUDE.md

Kontext für Claude Code. Bitte vor jeder Änderung lesen, besonders den
Abschnitt „Nicht verhandelbare Regeln".

## Was dieses Projekt ist

Werkzeug zur Teilautomatisierung des **gesamten V-Modells**
(Anforderung → Spezifikation → Architektur → Modulentwurf und die zugehörigen
Teststufen: Modul-, Integrations-, System- und Abnahmetest). Automatisiert wird
nur die *Mechanik* (Verlinkung, Konsistenzprüfung, Statuspflege,
Dokumentgenerierung). Die fachliche Verantwortung bleibt beim Menschen.

Stack: Django (deterministischer Kern + DB) und ein lokales LLM über Ollama
(beratend, danebenlaufend). Norm-Bezug über ein RAG (Retrieval-Augmented
Generation), nicht über Fine-Tuning – die Modellgewichte werden nie trainiert.

**Name:** ELISA = **E**ngineering **L**ifecycle **I**nsight for **S**afety
**A**rgumentation – Einblick in den gesamten Lebenszyklus, damit die
Sicherheitsargumentation (Safety Case nach IEC 61508) nachvollziehbar wird.
Die Argumentation selbst führt der Mensch.

**Slogan:** „ELISA – Macht das Unsichtbare sichtbar.“ Er begegnet der
Überforderung durch Norm- und Nachweisfülle: Struktur und Sichtbarkeit statt
Unübersichtlichkeit.

**Leitbild:** „Herr, öffne ihm die Augen!" (2 Kön 6,17). Functional Safety
ist für viele Firmen eine Angstdomäne; ELISA macht sichtbar, was verborgen ist
(Lücken, Orphans, fehlende Nachweise) – es berät wie Elisa, entscheidet aber
nie. Das stützt Regel 1–3: sichtbar machen ja, verbindlich setzen nein.

## Architektur in einem Satz

Die relationale Datenbank ist die einzige verbindliche Quelle der Wahrheit
(„source of truth"). Das LLM erzeugt nichts Verbindliches; es liefert Entwürfe
und Hinweise in den deterministischen Kern hinein.

## Nicht verhandelbare Regeln

Diese Regeln sind der Grund, warum das Werkzeug überhaupt zulässig ist
(prüfbare, verantwortbare Spezifikation). Niemals aufweichen:

1. **Das LLM verfasst keinen VERBINDLICHEN Inhalt.** Freigegebener Inhalt
   (`status = APPROVED`) in `WorkItem.body` und jede verbindliche Aussage
   stammt ausschließlich von einem Menschen.

   *Bewusste Erweiterung (MCP-Vorschläge):* Ein externes LLM (z. B. Claude
   Desktop über den MCP-Server) **darf REQ-Entwürfe vorschlagen** – aber nur
   streng eingerahmt und nie verbindlich:
   - immer `status = DRAFT`, **nie** PROPOSED/APPROVED durch das LLM;
   - `generated_by_llm = True` + `llm_model` (volle, auditierbare Provenienz);
   - sichtbar als „LLM-Vorschlag", den ein Mensch prüft, überarbeitet und erst
     dann (PL/FSM) freigibt. Die Freigabe bleibt rein menschlich (Regel 2).

   Damit liefert das LLM prüfpflichtige Entwürfe in den deterministischen Kern;
   verbindlich wird nichts ohne menschliche Freigabe. Direkt im Editor schreibt
   weiterhin der Mensch.

2. **`status = APPROVED` setzt einen menschlichen `approved_by` voraus.** Das
   LLM darf diesen Status nie setzen. Der Zustandsautomat lautet
   `DRAFT → PROPOSED → APPROVED`, und der letzte Schritt ist menschlich.

3. **LLM-Ausgaben sind genau zweierlei** – nichts dazwischen:
   - *ephemere Hinweise* (Toasts): werden nie gespeichert.
   - *vorgeschlagene Referenzen* (z. B. `NormLink`): werden mit
     `confirmed=False` abgelegt und erst durch einen menschlichen Klick
     bestätigt.
   - *beratender Chat* (`ChatSession`/`ChatMessage`): persistierter, RAG-
     gestützter Beratungs-Dialog (IEC 61508). Bewusst zugelassene dritte
     Kategorie – mit strikten Guardrails: NIE Quelle der Wahrheit; kein
     Endpoint schreibt aus dem Chat in `WorkItem.body` oder ein anderes
     verbindliches Feld; Übernahme in eine Spezifikation ist immer manuelles,
     menschliches Einfügen im Editor. Provenienz an jeder Assistenten-Nachricht.

4. **Provenienz wird mitgeschrieben** (`generated_by_llm`, `llm_model`), damit
   jeder Datensatz auditierbar bleibt.

5. **Invarianten gehören in die DB, nicht ins Prompt.** Orphan-Erkennung,
   Abdeckungsprüfung, Statusregeln und Dokumentgenerierung sind reines
   Django/SQL. Verlasse dich für Korrektheit nie auf das LLM.

## Kernkomponenten

- `app/models.py` – Datenmodell: `WorkItem` (selbstreferenzierende Hierarchie
  über `derived_from`), `NormClause`, `NormLink`. Enthält die Invarianten
  (`is_orphan`, Statuschoices).
- `app/views_feedback.py` – Live-Schreibfeedback. Beratend, schreibt keinen
  Inhalt. Gibt strukturierte Toasts als JSON zurück.
- `app/static/live_feedback.js` – Frontend: debounced Editor-Eingabe →
  Feedback-Endpoint → nicht-blockierende, interaktive Toasts
  (notice / checkbox / radio / form). Referenzvorschläge werden erst auf Klick
  verknüpft.
- `rag/rag_normen.py` – Eigenständiges RAG über die Norm-PDFs (Embeddings +
  Vektorsuche + Generierung), für den Norm-Bezug.
- `app/models.py::ProjectDocument` – Dokumentenmanagement je Projekt. PEP
  (Product Engineering Process) und REQ (Kundenanforderungen) sind statisch
  (kommen vom Kunden, werden nie verändert) und werden über den MCP-Server
  read-only bereitgestellt (`mcp_server/server.py`).
- `app/project_index.py` – Indexierung der Projektdokumente.

## Dokument-Indexierung (RAG)

**Alle Dokumente eines Projekts werden vom LLM (RAG) indiziert** – Text wird
extrahiert, in Chunks zerlegt, per `nomic-embed-text` eingebettet und in
ChromaDB abgelegt. **Projektbezogene Dokumente werden dem jeweiligen Projekt
zugeordnet** (eigene Collection je Projekt bzw. `project`-Metadatum); globale
Normen liegen in der gemeinsamen `normen`-Collection.

Der Chat/das Feedback ziehen diese Embeddings nur **beratend** als Kontext
heran (Retrieval-Augmented Generation, kein Fine-Tuning). Es bleibt bei den
Regeln oben: das LLM verfasst nichts Verbindliches, die DB ist die Quelle der
Wahrheit. Indexierung ist reine Mechanik (deterministisch, wiederholbar über
`manage.py index_project_docs`).

## Rollenteilung der LLMs (wichtig)

Das lokale **Ollama** (8B) halluziniert bei Wissensfragen und wird daher
bewusst **eingeschränkt**:

- **Ollama:** nur **Embeddings (Indexierung)** und **Retrieval über vorhandene
  Dokumente** (geerdete Antworten), plus **Notnagel** für Write-time-Toasts,
  wenn kein Reviewer verbunden ist (dann klar als „lokal/unsicher" markiert).
- **Write-time-Toasts** kommen primär vom **MCP-Team** (stärkere LLMs, z. B.
  Claude Desktop, verbunden über den MCP-Server). Ablauf: Editor legt einen
  `FeedbackRequest` an → Team holt ihn per `next_feedback_request` **in der
  Persona des jeweiligen V-Schritts** (`LLMRoleDescription` + Projektbeschreibung)
  → liefert Toasts via `submit_feedback` → Editor pollt `/api/feedback-poll/`.
- **Jeder der 8 V-Schritte hat eine Persona** (`LLMRoleDescription`). Das, die
  strikte Zyklus-Reihenfolge (kein Überspringen) und die menschliche Freigabe
  verhindern „Vorpreschen" und generisches Halluzinieren.

Der Toast-Vertrag bleibt unverändert: es werden NUR Toasts geliefert, nie
Inhalt; verbindlich wird etwas erst durch menschlichen Klick.

### Lokale Inferenz: Ollama oder Eliezer

`app/local_llm.py` kapselt Chat und Embeddings der lokalen Inferenz.
`LOCAL_LLM_BACKEND=eliezer` leitet sie an **Eliezer** (GPU-Modellmanager,
OpenAI-kompatibel: `/v1/chat/completions`, `/v1/embeddings`) statt an Ollama.
Rollenteilung und Regeln bleiben unverändert (beratend, Toasts/Vorschläge,
nichts Verbindliches). Konfiguration: `ELIEZER_BASE_URL`, `ELIEZER_API_KEY`
(nur Umgebung, nie im Repo), `ELIEZER_CHAT_MODEL`, `ELIEZER_EMBED_MODEL`;
die Modell-Keys müssen auf Eliezers Allowlist stehen. Achtung: die
Embedding-Spalte ist 768-dimensional – ein anderes Embedding-Modell erfordert
Neuindexierung (`manage.py index_project_docs`) und ggf. Migration.

### Auslieferung (Podman-Image)

Standard-Deployment ist das Image aus `Containerfile` (`compose.yaml`: `web`,
`mcp`, `worker`, `db` und `eliezer` als Partner; Entrypoint `packaging/container-entrypoint.sh`). Konfiguration
nur über `elisa.env` (aus `.env.example`, nie committen), eingehängt als
`/etc/elisa/env`. Static liefert nginx; WhiteNoise nur optional (`ELISA_SERVE_STATIC=true`). `deploy.sh`/systemd bleiben als
Alternative.

### Metapaket `elisa-stack`

Server-Installation per .deb (`packaging/build-deb.sh`): Podman rootless als
`www-data` (Quadlet unter `/etc/containers/systemd/users/33/`, Linger), nginx als
Proxy mit `/etc/nginx/sites-available/<host.domain>.conf` (+ `sites-enabled`).
Das preinst lädt `packaging/install-as-www-data.sh` von GitHub per Commit-SHA und
prüft die eingebaute SHA256 – ausgeführt wird es nur als `www-data`, nie als
root. Beim Ändern dieses Skripts: committen, pushen, Paket neu bauen.

## Toast-Vertrag (LLM-Ausgabe)

Der Feedback-Endpoint erwartet vom LLM ausschließlich JSON dieser Form:

```json
{ "toasts": [
  { "type": "notice|radio|checkbox|form", "severity": "info|warn|conflict",
    "message": "…", "options": ["…"], "fields": [{"name":"…","label":"…"}],
    "action": "norm-link|completeness|append-criterion" }
]}
```

`options`/`fields`/`action` sind nur bei den interaktiven Typen gesetzt. Ein
`action`-Submit löst immer einen expliziten, menschlich angestoßenen Endpoint
aus – nie schreibt das LLM selbst.

## Entwicklung

```bash
pip install -r requirements.txt
ollama pull nomic-embed-text      # Embeddings fürs RAG
ollama pull llama3.1              # kleines, schnelles Chat-Modell für Live-Feedback
python manage.py makemigrations && python manage.py migrate
```

Für die Live-Toasts ein kleines Modell (3–8B) wählen und Feedback pro
abgeschlossenem Satz/Absatz auslösen, nicht pro Tastendruck. Ollama läuft für
einen Einzelplatz auf einem Laptop; für mehrere gleichzeitige Nutzer auf eine
Workstation/Server mit GPU auslagern und nur die Host-Adresse des
Ollama-Clients ändern.

### Git / Push (verbindlich)

**Jeder Push schreibt das `CHANGELOG.md` fort.** Vor jedem `git push` einen
neuen Eintrag im **Debian-Changelog-Stil** ergänzen (`elisa (<version>)
…; urgency=…`, Bullet-Liste der Änderungen, abschließende Maintainer-/Datums-
zeile mit `-- Name <mail>  RFC-2822-Datum`). Kein Push ohne aktualisiertes
Changelog.

## Skills

Unter `.claude/skills/` liegen drei Skills, die die wiederkehrenden Muster
kodieren. Vor Arbeiten am jeweiligen Bereich den passenden Skill lesen:

- `traceability-model` – Datenmodell, Invarianten, Statusautomat.
- `write-time-feedback` – beratender Linter, Toast-Vertrag, Regel „LLM
  verfasst nie Inhalt".
- `norm-rag` – Norm-RAG aufbauen und abfragen.
