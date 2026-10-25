#!/usr/bin/env python3
"""
Autonomer Persona-Worker für ELISA – poll-frei über SSE.

Hält eine SSE-Verbindung zum MCP-Push-Endpoint (`/<projekt>/<scope>/events`),
wird bei neuen FeedbackRequests vom Server GETRIGGERT (kein Poll), lässt das
Modell IN DER PERSONA des V-Schritts antworten und liefert ausschließlich Toasts
zurück – nie verbindlichen Inhalt (CLAUDE.md, Toast-Vertrag).

Kein DB-Zugriff nötig: das Event trägt Persona + Entwurf + Nachbarn selbst.

Backends (`--backend`):
  claude  – Anthropic-API (Default; hier auf dem Server, kein LM Studio).
            Key über ANTHROPIC_API_KEY.
  openai  – OpenAI-kompatibel, z. B. LM Studio auf GPU (zuhause).

Start (Claude):
    ANTHROPIC_API_KEY=… python -m mcp_worker.worker \
        --mcp-base https://elisa.example.com/mcp \
        --project telehaase --scope all --token <BEARER>

Start (LM Studio zuhause):
    python -m mcp_worker.worker --backend openai \
        --llm-base http://localhost:1234/v1 --model <modell> …

Env-Alternativen: MCP_BASE, MCP_PROJECT, MCP_SCOPE, MCP_TOKEN,
                  WORKER_BACKEND, LLM_MODEL, LLM_BASE_URL, LLM_API_KEY,
                  ANTHROPIC_API_KEY
"""
import argparse
import json
import os
import sys
import time

import httpx

TOAST_CONTRACT = (
    "Du bist ein beratender Lektor (Write-time-Linter) und antwortest "
    "AUSSCHLIESSLICH mit JSON dieser Form: "
    '{"toasts":[{"type":"notice|radio|checkbox|form",'
    '"severity":"info|warn|conflict","message":"…","options":["…"],'
    '"fields":[{"name":"…","label":"…"}],'
    '"action":"norm-link|completeness|append-criterion"}]}. '
    "options/fields/action nur bei interaktiven Typen. Schreibe NIE "
    "verbindlichen Inhalt – nur kurze, prüfbare Hinweise. Prüfe auch die "
    "Konsistenz zur Dokumentenreihe. Wenn nichts zu melden ist: {\"toasts\":[]}."
)


def _prompt(payload):
    persona = payload.get("persona") or ""
    draft = payload.get("draft") or ""
    neighbours = payload.get("neighbours") or []
    system = (persona + "\n\n" + TOAST_CONTRACT).strip()
    user = "ENTWURF (zu prüfen):\n" + draft
    if neighbours:
        user += ("\n\nNACHBAR-ITEMS (Kontext / Widerspruchsprüfung):\n"
                 + json.dumps(neighbours, ensure_ascii=False))
    return system, user


def _extract_toasts(raw: str):
    try:
        data = json.loads((raw or "{}").strip())
    except json.JSONDecodeError:
        return []
    toasts = data.get("toasts", []) if isinstance(data, dict) else []
    return toasts if isinstance(toasts, list) else []


def _toasts_claude(client, model, system, user):
    """Anthropic-API; Prefill mit '{' erzwingt ein JSON-Objekt als Antwort."""
    msg = client.messages.create(
        model=model, max_tokens=1024, temperature=0.2, system=system,
        messages=[{"role": "user", "content": user},
                  {"role": "assistant", "content": "{"}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content)
    return _extract_toasts("{" + text)


def _toasts_openai(client, model, system, user):
    """OpenAI-kompatibel (LM Studio) mit JSON-Response-Format."""
    resp = client.chat.completions.create(
        model=model, temperature=0.2,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    return _extract_toasts(resp.choices[0].message.content)


def make_toasts(backend, client, model, payload):
    system, user = _prompt(payload)
    if backend == "claude":
        return _toasts_claude(client, model, system, user)
    return _toasts_openai(client, model, system, user)


def _handle(hx, base, project, scope, headers, backend, client, model, payload):
    rid = payload.get("request_id")
    role = payload.get("role")
    try:
        toasts = make_toasts(backend, client, model, payload)
    except Exception as exc:  # Modellfehler darf den Worker nicht abreißen
        print(f"[worker] LLM-Fehler bei #{rid}: {exc}", file=sys.stderr, flush=True)
        toasts = []
    url = f"{base}/{project}/{scope}/events/{rid}/toasts"
    r = hx.post(url, headers=headers, json={"toasts": toasts})
    print(f"[worker] #{rid} [{role}] -> {len(toasts)} Toast(s), submit HTTP {r.status_code}",
          flush=True)


CHAT_SYSTEM = (
    "Du bist {sender}, ein beratendes LLM im Item-Chat eines IEC-61508-"
    "Spezifikationswerkzeugs. Antworte knapp, hilfreich und sachlich auf Deutsch. "
    "Du berätst nur – du schreibst KEINEN verbindlichen Inhalt; verbindliche "
    "Inhalte trägt der Mensch im Editor ein (CLAUDE.md Regel 3). Den Nutzer darfst "
    "du per @vorname adressieren."
)


def _chat_reply(backend, client, model, system, user):
    """Freitext-Antwort (KEIN Toast-JSON) fürs Chatten mit den Menschen."""
    if backend == "claude":
        msg = client.messages.create(
            model=model, max_tokens=800, temperature=0.4, system=system,
            messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in msg.content).strip()
    resp = client.chat.completions.create(
        model=model, temperature=0.4,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}])
    return (resp.choices[0].message.content or "").strip()


def _handle_chat(hx, base, project, scope, headers, backend, client, model,
                 handles, sender, payload):
    """`event: chat_mention` → antworten, NUR wenn mein @-Handle gemeint ist."""
    msg = payload.get("message") or ""
    low = msg.lower()
    if handles and not any(("@" + h) in low for h in handles):
        return  # nicht an mich gerichtet
    ident = payload.get("identifier", "")
    system = CHAT_SYSTEM.format(sender=sender or "ein LLM")
    user = (f"Item {ident} — {payload.get('title', '')}\n{payload.get('body', '')}\n\n"
            f"Chatverlauf:\n{json.dumps(payload.get('history', []), ensure_ascii=False)}\n\n"
            f"Neue Nachricht von @{payload.get('from', 'user')}: {msg}\n\nAntworte dem Nutzer.")
    try:
        answer = _chat_reply(backend, client, model, system, user)
    except Exception as exc:
        print(f"[worker] Chat-LLM-Fehler ({ident}): {exc}", file=sys.stderr, flush=True)
        return
    if not answer:
        return
    r = hx.post(f"{base}/{project}/{scope}/events/chat-reply", headers=headers,
                json={"identifier": ident, "message": answer, "sender": sender})
    print(f"[worker] chat_mention {ident} -> Antwort {len(answer)} Z., HTTP {r.status_code}",
          flush=True)


def _build_client(backend, llm_base, api_key):
    if backend == "claude":
        import anthropic
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("API-Key fehlt (Backend claude / ANTHROPIC_API_KEY).")
        return anthropic.Anthropic(api_key=key)
    from openai import OpenAI
    # Lokale Anbieter (Ollama/LM Studio) ignorieren den Key, brauchen aber einen.
    return OpenAI(base_url=llm_base, api_key=api_key or "not-needed")


def run(base, project, scope, token, backend, model, llm_base, api_key,
        handles=None, sender=""):
    base = base.rstrip("/")
    events_url = f"{base}/{project}/{scope}/events"
    headers = {"Authorization": f"Bearer {token}"}
    client = _build_client(backend, llm_base, api_key)
    where = "Anthropic-API" if backend == "claude" else llm_base
    handles = handles or []
    print(f"[worker] verbunden: {events_url}  (Backend {backend}, Modell {model} @ {where}; "
          f"Chat-Handles {handles})", flush=True)
    with httpx.Client(timeout=httpx.Timeout(None)) as hx:
        while True:
            try:
                with hx.stream("GET", events_url, headers=headers) as r:
                    if r.status_code != 200:
                        print(f"[worker] Stream-Fehler HTTP {r.status_code}; retry 3s",
                              file=sys.stderr, flush=True)
                        time.sleep(3); continue
                    event = None
                    for line in r.iter_lines():
                        if line.startswith("event:"):
                            event = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"):
                            data = line[5:].strip()
                            if event == "feedback" and data:
                                _handle(hx, base, project, scope, headers,
                                        backend, client, model, json.loads(data))
                            elif event == "chat_mention" and data:
                                _handle_chat(hx, base, project, scope, headers,
                                             backend, client, model, handles, sender,
                                             json.loads(data))
                        elif line == "":
                            event = None
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                print(f"[worker] Verbindung/Parse-Fehler ({exc}); reconnect 3s",
                      file=sys.stderr, flush=True)
                time.sleep(3)


def main():
    ap = argparse.ArgumentParser(description="ELISA Persona-Worker (poll-frei, SSE)")
    ap.add_argument("--mcp-base", default=os.getenv("MCP_BASE", "http://127.0.0.1:8765"))
    ap.add_argument("--project", default=os.getenv("MCP_PROJECT", "telehaase"))
    ap.add_argument("--scope", default=os.getenv("MCP_SCOPE", "all"))
    ap.add_argument("--token", default=os.getenv("MCP_TOKEN", ""))
    ap.add_argument("--backend", choices=["claude", "openai"],
                    default=os.getenv("WORKER_BACKEND", "claude"))
    ap.add_argument("--model", default=os.getenv("LLM_MODEL", ""))
    ap.add_argument("--llm-base", default=os.getenv("LLM_BASE_URL", "http://localhost:1234/v1"))
    ap.add_argument("--api-key", default=os.getenv("LLM_API_KEY", "lm-studio"))
    a = ap.parse_args()
    if not a.token:
        ap.error("--token (oder MCP_TOKEN) erforderlich")
    # Backend-spezifischer Default fürs Modell (schnell + günstig für Linter-Toasts)
    model = a.model or ("claude-haiku-4-5" if a.backend == "claude" else "local-model")
    handle = "claude" if a.backend == "claude" else "llm"
    run(a.mcp_base, a.project, a.scope, a.token, a.backend, model, a.llm_base, a.api_key,
        handles=[handle], sender="@" + handle)


if __name__ == "__main__":
    main()
