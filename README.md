# ELISA

**E**ngineering **L**ifecycle **I**nsight for **S**afety **A**rgumentation

**ELISA – Macht das Unsichtbare sichtbar.**

> *„Herr, öffne ihm die Augen, dass er sieht!"* — 2 Kön 6,17

Funktionale Sicherheit ist für viele Firmen eine Angstdomäne: Was nicht
sichtbar ist, macht Angst — die ungeprüfte Lücke, die verwaiste Anforderung,
der fehlende Nachweis. Die Fülle an Norm, Nachweisen und Abhängigkeiten
überfordert. Der Slogan begegnet dieser Überforderung: ELISA ordnet, verlinkt
und zeigt genau das, was als Nächstes zu tun ist. **ELISA macht sichtbar, was verborgen ist.** Der Name
erinnert an Elisa, der nicht herrschte, sondern beriet: Er öffnete dem Diener
die Augen für das, was schon da war. Genau so arbeitet das Werkzeug — es zeigt
Zusammenhänge, Lücken und Widersprüche; entscheiden und verantworten bleibt
beim Menschen.

**ELISA unterstützt Ingenieurinnen und Ingenieure dabei, das gesamte
V-Modell sauber und nachvollziehbar zu durchlaufen** — von der Anforderung über
Spezifikation, Architektur und Modulentwurf bis zu den zugehörigen Teststufen
(Modul-, Integrations-, System- und Abnahmetest) — mit durchgängigem Norm-Bezug
nach **IEC 61508**.

Das Werkzeug nimmt dem Menschen die *mechanische* Fleißarbeit ab: das Verlinken
(Traceability), das Prüfen auf Lücken und Widersprüche, das Pflegen von Status
und das Erzeugen der Dokumente. **Die fachliche Verantwortung bleibt
ausdrücklich beim Menschen.** ELISA entscheidet nichts Verbindliches; es
bereitet vor, prüft und schlägt vor.

> Diese README beschreibt das Projekt für **Menschen**. Den verbindlichen
> Arbeitskontext für die Weiterentwicklung (inkl. der „nicht verhandelbaren
> Regeln") enthält [`CLAUDE.md`](CLAUDE.md).

## Betrieb als Podman-Image

ELISA wird als Container-Image ausgeliefert (`Containerfile`, `compose.yaml`):

```bash
cp .env.example elisa.env      # Secret, Hosts, Eliezer-URL/Key eintragen
podman compose -f compose.yaml -f compose.podman.yaml up -d --build
```

Sechs Dienste: `proxy` (nginx, Port 8080: liefert `/static/` und leitet `/` und `/mcp/` weiter;
hier öffnest du ELISA), `eliezer` (Modellmanager, aus `../eliezer` gebaut; ELISAs
Partner, erreichbar als `http://eliezer:1234`), `db` (PostgreSQL mit pgvector) sowie `web` (daphne, Port 8088, migriert und sammelt
Static beim Start), `mcp` (MCP-Server, Port 8765) und `worker` (Supervisor). Daten
(media, Static, incoming) liegen im Volume `data`, die Datenbank in `pgdata`; die Konfiguration wird
als `/etc/elisa/env` schreibgeschützt eingehängt. Läuft Eliezer schon auf dem Host, startest du zusätzlich mit `-f compose.host-eliezer.yaml`
und lässt den Dienst `eliezer` weg. Wer Eliezer extern betreibt, lässt den Dienst weg und setzt die URL; er läuft dann auf dem
GPU-Host (`ELIEZER_BASE_URL`). Für die GPU zusätzlich `-f compose.gpu.yaml`. Der Dienst läuft rootless als UID 10001 ohne
Capabilities. Static-Dateien liefert normalerweise der vorgeschaltete nginx aus
(`elisa.nginx.conf`); ohne nginx schaltet `ELISA_SERVE_STATIC=true` WhiteNoise ein.
`deploy.sh` und die systemd-Units bleiben als Alternative ohne
Container bestehen.

## Installation als Metapaket (`elisa-stack`)

Für Debian-Server gibt es das Metapaket `elisa-stack`, das den Podman-Stack
**rootless als `www-data`** betreibt (Quadlet-Units unter
`/etc/containers/systemd/users/33/`) und nginx als Proxy einrichtet:

```bash
packaging/build-deb.sh           # baut dist/elisa-stack_<version>_all.deb
sudo ELISA_DOMAIN=elisa.firma.de apt install ./dist/elisa-stack_*_all.deb
```

- **preinst:** richtet subuid/subgid, HOME (`/var/lib/elisa/home`) und *Linger*
  für `www-data` ein (die Container laufen ohne angemeldeten Benutzer), lädt
  `packaging/install-as-www-data.sh` von GitHub, prüft die im Paket
  festgelegte SHA256 (Download per Commit-SHA) und führt es **als `www-data`**
  aus: ELISA und Eliezer holen und die Images bauen. Das Repo muss dafür
  öffentlich sein.
- **postinst:** legt `/etc/elisa/env` einmalig mit Zufallswerten an, schreibt die
  Domain nach `/etc/elisa/stack.conf` und rendert
  `packaging/nginx/elisa-proxy.conf` nach `/etc/nginx/sites-available/<host.domain>.conf`
  (Link in `sites-enabled`, dann `nginx -t` und reload). Die Domain kommt aus
  `ELISA_DOMAIN`, sonst `hostname -f`. Danach startet es die Dienste.
- Eliezer extern betreiben: vor der Installation in `/etc/elisa/stack.conf`
  `ELISA_SKIP_ELIEZER=1` setzen und `ELIEZER_BASE_URL` in `/etc/elisa/env`.
- GPU (AMD): Drop-in `elisa-eliezer.container.d/gpu.conf` mit `AddDevice=`.

## Chat

Die Eingabe merkt sich die eigenen Nachrichten der Session: **↑** holt eine frühere,
**↓** eine spätere, ganz unten steht wieder der angefangene Entwurf (wie in der
Shell). Mit **@all** sprichst du alle Teilnehmer an (Menschen und Personas); die
@-Liste schlägt `@all` mit vor. Personas stoßen sich damit nicht gegenseitig an:
`@all` zählt nur in Nachrichten von Menschen.

## MCP-Transport

Der MCP-Server spricht **Streamable HTTP** (`…/<projekt>/<scope>/mcp`, aktueller
Standard, immer aktiv). Der ältere **SSE-Transport** (`…/sse`, `…/messages/`) gilt
als veraltet und lässt sich abschalten: `MCP_SSE_ENABLED=false` in `elisa.env`.
Dann antworten `/sse` und `/messages/` mit `410`, und die im Admin erzeugte
Client-Konfiguration verwendet `"type": "http"` mit der `/mcp`-URL. Der
mitgelieferte Worker nutzt Streamable HTTP (`MCP_CLIENT_TRANSPORT=sse` erzwingt SSE).

## Lokale Modelle: Ollama oder Eliezer

Chat, Embeddings und Notnagel-Hinweise laufen über ein lokales Modell. Standard
ist Ollama; mit `LOCAL_LLM_BACKEND=eliezer` übernimmt
[Eliezer](https://github.com/Beerlesklopfer/eliezer) (GPU-Modellmanager,
OpenAI-kompatibel). Konfiguration über Umgebungsvariablen:

```
LOCAL_LLM_BACKEND=eliezer
ELIEZER_BASE_URL=http://127.0.0.1:1234
ELIEZER_API_KEY=sk-…            # nur Umgebung/Env-Datei, nie ins Repo
ELIEZER_CHAT_MODEL=<model-key>  # Key aus Eliezers Allowlist
ELIEZER_EMBED_MODEL=<model-key> # 768-dimensional (Embedding-Spalte)
```

Das gilt für Chat, Embeddings, Notnagel-Hinweise, die Übersetzung
(`app/translate.py`, Modell optional über `ELIEZER_TRANSLATE_MODEL`) und das
eigenständige `rag/rag_normen.py`. Das Modell berät nur; verbindlich wird
nichts ohne menschliche Freigabe.

## Worum es geht

Sicherheitsgerichtete Spezifikation muss **prüfbar und verantwortbar** sein.
Genau deshalb trennt ELISA strikt zwei Welten:

- **Der deterministische Kern** (eine relationale Datenbank, gesteuert von
  Django) ist die **einzige Quelle der Wahrheit**. Was hier freigegeben ist,
  hat ein Mensch verantwortet.
- **Die Sprachmodelle (LLMs) laufen beratend daneben.** Sie liefern Entwürfe,
  Hinweise und Norm-Verweise — aber nie verbindlichen Inhalt. Jeder ihrer
  Beiträge ist als Vorschlag erkennbar, mit voller Herkunftsangabe, und wird
  erst durch eine bewusste menschliche Handlung Teil der Spezifikation.

Damit bleibt die Geschwindigkeit eines Assistenten erhalten, ohne die
Verantwortbarkeit aufzugeben.

## Die wichtigsten Prinzipien

- **Mensch gibt frei.** Der Statusweg lautet `Entwurf → Vorgeschlagen →
  Freigegeben`; der letzte Schritt ist immer menschlich.
- **Korrektheit kommt aus der Datenbank, nicht aus dem Modell.** Lücken in der
  Traceability, Abdeckungsprüfung und Statusregeln sind nachprüfbare Logik —
  kein Modell „entscheidet" darüber.
- **Alles ist auditierbar.** Zu jedem maschinell erzeugten Beitrag wird
  festgehalten, welches Modell ihn wann beigesteuert hat.
- **Normen werden nicht „auswendig gelernt".** Der Norm-Bezug entsteht zur
  Laufzeit über ein RAG (Retrieval-Augmented Generation): die Modelle zitieren
  aus den tatsächlich vorhandenen Dokumenten, statt frei zu fabulieren.

## Wie es sich anfühlt

- **Arbeitsbereich (Workspace):** ein Baum entlang des V-Modells. Links wird
  spezifiziert (REQ → SPEC → ARCH → MOD), rechts verifiziert. Items werden
  gegliedert, verknüpft, versioniert und freigegeben — Inhalt schreibt immer der
  Mensch im WYSIWYG-Editor (Markdown, Mermaid-Diagramme, eingebettete Bilder und
  Tabellen).
- **Beratender Chat:** ein persönlicher Norm-Chat sowie projektweite Chats, in
  denen man die Assistenten direkt per `@name` ansprechen kann. Der Chat ist
  RAG-gestützt, persistiert — und ausdrücklich **nie** die Quelle der Wahrheit.
- **Eingangsdokumente:** die vom Kunden gelieferten Unterlagen (Ablaufplan PEP,
  Anforderungen REQ) werden unverändert abgelegt und automatisch für die
  Assistenten erschlossen.

## Die Assistenten (Personas)

Jeder der acht V-Modell-Schritte hat eine eigene fachliche Persona, dazu kommen
vier Spezialisten. Alle tragen biblische Namen mit passendem Akronym; im Chat
stellen sie sich so vor.

**Spezialisten**

| Persona | Akronym | Aufgabe |
|---|---|---|
| **Lukas** | **L**ookup **U**nderlying **K**nowledge, **A**nswer **S**ourced | RAG-Chat – beantwortet Fragen geerdet an Normen und Projektdokumenten („alles von Anfang an sorgfältig erforscht“, Lk 1,3) |
| **Esra** (`@esra`) | **E**xtract **S**tandards, **R**eference-**A**nchored | Normenrecherche – findet die passenden Normen (der Schriftgelehrte, Esra 7) |
| **Tertius** (`@tertius`) | **T**ranslate **E**xactly, **R**etain **T**erms, **I**nvariants, **U**nchanged **S**tructure | Übersetzer – informativ, die Quellsprache bleibt maßgeblich (der Schreiber des Römerbriefs, Röm 16,22) |
| **Nathan** (`@nathan`) | **N**onconformities **A**udited against **T**raceability, **H**azards **A**nd **N**orms | Externes Audit – prüft kritisch von außen (der Prophet vor David, 2 Sam 12) |

**V-Modell-Schritte**

| Persona | Schritt | Akronym |
|---|---|---|
| **Mose** | Anforderungen (REQ) | **M**andatory **O**bligations, **S**tated **E**xplicitly |
| **Noah** | Systementwurf (SPEC) | **N**ormalize **O**bligations **A**nd **H**azards |
| **Salomo** | Architektur (ARCH) | **S**tructure, **A**llocation, **L**ayering, **O**verview of **M**odules, **O**ptimized |
| **Hiram** | Modulentwurf (MOD) | **H**ierarchical **I**mplementation **R**ules for **A**lgorithms & **M**odules |
| **Gideon** | Modultest (MODTEST) | **G**uarded **I**nputs, **D**ata **E**xercised **O**n **N**ominal and fault cases |
| **Josua** | Integrationstest (INTTEST) | **J**oin **O**ne **S**ubsystem, **U**nderstand **A**ll interfaces |
| **Daniel** | Systemtest (SYSTEST) | **D**emonstrate **A**ll **N**ominal **I**nterfaces and edge cases, **L**ive |
| **Thomas** | Abnahme (ACCTEST) | **T**rust only **H**ands-on **O**bservation, **M**easured **A**cceptance, **S**ign-off |

Die Personas können **lokal** (auf eigener Infrastruktur) oder **extern** (über
einen Cloud-Anbieter wie Claude oder ChatGPT) laufen. Sie wissen voneinander,
wer lokal und wer extern ist — eine lokale Persona kann eine externe gezielt um
eine **externe Zweitmeinung/Verifikation** bitten.

## Mehrsprachigkeit

Spezifikationen werden in ihrer **normativen Quellsprache** verfasst; der
maßgebliche Wortlaut wird nie übersetzt. Jede Nutzerin kann zusätzlich eine
**informative Übersetzung** einblenden (automatisch erstellt). Die Chats bleiben
sprachagnostisch.

## Technik in Kürze

Django (ASGI) als deterministischer Kern · PostgreSQL bzw. SQLite · ein lokales
Ollama für Embeddings und den Norm-Chat · ein MCP-Server, der den Assistenten
kontrollierten Zugriff gibt · externe Modelle (Claude/ChatGPT/LM-Studio) als
zusätzliche Personas · RAG über die Norm- und Projektdokumente · pandoc für die
Dokumentgenerierung (Markdown → `.docx`).

Schnellstart für die Entwicklung:

```bash
pip install -r requirements.txt
ollama pull nomic-embed-text && ollama pull llama3.1
python manage.py migrate && python manage.py create_user
python manage.py runserver
```

Installation und Betrieb (vier systemd-Dienste: Web, MCP-Server, Worker,
Ollama; hinter nginx mit TLS) erledigt `deploy.sh`. Details zu Aufbau,
Komponenten und Regeln stehen in [`CLAUDE.md`](CLAUDE.md) und den Skills unter
`.claude/skills/`.

---

*ELISA — prüfbare, verantwortbare Spezifikation
nach IEC 61508.*
