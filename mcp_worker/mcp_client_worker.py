#!/usr/bin/env python3
"""
MCP-Client-Worker — provider-agnostische Brücke LLM ↔ Anwendung.

PRIMÄRKANAL = MCP-Chat: der Worker verbindet sich als echter MCP-CLIENT (MCP-SDK,
SSE-Transport) zum ELISA-MCP-Server (…/<projekt>/<scope>/mcp bzw. …/sse, Bearer-Token)
und erledigt seine Arbeit über die MCP-Tools:
  list_my_mentions → get_item_chat / get_workitem → post_item_chat
Das LLM (Claude / OpenAI-kompatibel / Ollama) ist nur ein Textgenerator.

NEBENKANAL = Unix-Socket des Supervisors: der Worker registriert sich (Projekt +
Persona/Handle) und kann mit ANDEREN Workern direkt Nachrichten austauschen
(client-to-client, newline-JSON). Über den Socket läuft KEINE Arbeitsverteilung.

Start (i. d. R. vom Supervisor gespawnt):
    python -m mcp_worker.mcp_client_worker --mcp-base http://127.0.0.1:8765 \
        --project telehaase --scope spec --token <BEARER> --handle claude \
        --provider claude --model claude-haiku-4-5 --socket /var/lib/elisa/supervisor.sock
"""
import argparse
import asyncio
import contextlib
import json
import os
import sys

CHAT_SYSTEM = (
    "Du bist {handle}, ein beratendes LLM im ELISA (IEC 61508). Antworte knapp, "
    "sachlich, auf Deutsch. Du berätst nur — verbindliche Inhalte trägt der Mensch "
    "im Editor ein. Den Nutzer darfst du per @vorname adressieren."
)


# Gilt zusätzlich zur Persona, wenn sie im CHAT antwortet (nicht im Editor/Toast):
# Rollenbeschreibungen der V-Schritte verlangen Spezifikationen/Items – im Chat
# führte das bei einer bloßen Begrüßung zu erfundenen Pflichtenheften.
CHAT_MODE_RULES = (
    "CHAT-MODUS (hat Vorrang vor allem Obigen): Du antwortest in einem Chat, nicht im "
    "Editor. Beantworte NUR, was die letzte Nachricht fragt – kurz, höchstens 5 Sätze, "
    "ohne Überschriften oder Tabellen. Erzeuge KEINE Spezifikation, Anforderungen, Items, "
    "Tabellen oder Traceability-Verweise, außer sie werden ausdrücklich verlangt, und "
    "erfinde nie Identifier, Handles, Normstellen oder Zahlen. Bei Begrüßung oder "
    "Smalltalk: stelle dich in 1–2 Sätzen mit Namen und Aufgabe vor und frage, wobei du "
    "helfen kannst. Weißt du etwas nicht, sag es."
)

# ── LLM (provider-agnostisch) ───────────────────────────────────────────────
def _llm_text(provider, model, base_url, api_key, system, user):
    api_key = (api_key or "").strip()        # Whitespace/Umbruch aus Copy-Paste raus
    if provider == "claude":
        import anthropic
        c = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        m = c.messages.create(model=model or "claude-haiku-4-5", max_tokens=900,
                              temperature=0.3, system=system,
                              messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in m.content).strip()
    if provider == "ollama":
        import ollama
        host = base_url or os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        if host.rstrip("/").endswith("/v1"):      # nativer Client braucht den HOST (nicht /v1)
            host = host.rstrip("/")[:-3]
        cl = ollama.Client(host=host, timeout=float(os.getenv("OLLAMA_TIMEOUT", "300")))
        r = cl.chat(model=model or "llama3.1",
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}])
        return (r["message"]["content"] or "").strip()
    from openai import OpenAI          # LM Studio / DeepSeek / ChatGPT (OpenAI-kompat.)
    cl = OpenAI(base_url=base_url or None, api_key=api_key or "not-needed")
    try:
        r = cl.chat.completions.create(model=model or "local-model", temperature=0.3,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}])
        return (r.choices[0].message.content or "").strip()
    except Exception:
        # „pro"/Reasoning-Modelle (z. B. gpt-5.5-pro) laufen über die Responses-API,
        # nicht über chat/completions. Fallback:
        r = cl.responses.create(model=model, instructions=system, input=user)
        return (getattr(r, "output_text", "") or "").strip()


def _tool_json(result):
    """MCP-Tool-Ergebnis → EIN Python-Objekt (erster Content-Block). Für Tools,
    die ein einzelnes dict zurückgeben (get_workitem, next_esra_task)."""
    try:
        for c in result.content:
            t = getattr(c, "text", None)
            if t is not None:
                try:
                    return json.loads(t)
                except Exception:
                    return t
    except Exception:
        pass
    return None


def _tool_rows(result):
    """MCP-Tool-Ergebnis → LISTE aller Zeilen. FastMCP gibt ein Listen-Resultat
    als MEHRERE Content-Blöcke zurück (einer je Element) — die las der alte Code
    nur als content[0]. Hier sammeln wir ALLE Blöcke. Für list_my_mentions,
    get_item_chat, list_document_chunks, list_norm_keywords usw."""
    rows = []
    try:
        for c in result.content:
            t = getattr(c, "text", None)
            if t is None:
                continue
            try:
                v = json.loads(t)
            except Exception:
                continue
            if isinstance(v, list):
                rows.extend(v)
            elif isinstance(v, dict):
                rows.append(v)
    except Exception:
        pass
    return rows


# ── Nebenkanal: Supervisor-Socket (client-to-client) ────────────────────────
async def _socket_register(args, inbox):
    """Verbindet zum Supervisor-Socket, registriert sich und legt eingehende
    Nachrichten anderer Worker in `inbox`. Reine Inter-Worker-Kommunikation."""
    if not args.socket:
        return
    while True:
        try:
            reader, writer = await asyncio.open_unix_connection(args.socket)
            hello = {"type": "register", "project": args.project, "scope": args.scope,
                     "handle": args.handle, "provider": args.provider}
            writer.write((json.dumps(hello) + "\n").encode())
            await writer.drain()
            print(f"[worker {args.handle}] Supervisor-Socket registriert.", flush=True)
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    inbox.append(json.loads(line.decode()))
                except Exception:
                    pass
        except Exception as exc:
            print(f"[worker {args.handle}] Socket ({exc}); retry 5s", file=sys.stderr, flush=True)
            await asyncio.sleep(5)


async def _vstep_persona(session, proj, phase):
    """V-Schritt-Persona (LLMRoleDescription) zur Item-Phase – damit Esra im
    jeweiligen V-Modell-Schritt ‚in Rolle geht'."""
    if not phase:
        return ""
    p = _tool_json(await session.call_tool(
        "get_persona", {"project_key": proj, "role": phase}))
    return p.get("persona", "") if isinstance(p, dict) else ""


# ── Primärkanal: MCP-Chat ───────────────────────────────────────────────────
async def _poll_once(session, args, proj):
    try:
        res = await session.call_tool("list_my_mentions",
                                      {"project_key": proj, "handle": args.handle})
        mentions = _tool_rows(res)
    except Exception as exc:
        print(f"[worker {args.handle}] list_my_mentions({proj}): {exc}", file=sys.stderr, flush=True)
        return
    for mn in mentions:
        ident = (mn or {}).get("identifier")
        if not ident:
            continue
        try:
            chat = _tool_rows(await session.call_tool(
                "get_item_chat", {"project_key": proj, "identifier": ident}))
            item = _tool_json(await session.call_tool(
                "get_workitem", {"project_key": proj, "identifier": ident})) or {}
        except Exception:
            chat, item = [], {}
        system = ((args.persona or CHAT_SYSTEM.format(handle="@" + args.handle))
                  + "\n\n" + CHAT_MODE_RULES)
        last_sender = mn.get("last_sender") or ""
        last_name = mn.get("last_sender_name") or ""
        who = (f"{last_sender} ({last_name})" if last_sender and last_name
               else last_sender or last_name or "der Nutzer")
        addr = (f"Sprich {last_sender} mit diesem Handle an" if last_sender
                else "Adressiere die Person nicht mit einem erfundenen Handle")
        user = (f"Item {ident} — {item.get('title', '')}\n{item.get('body', '')}\n\n"
                f"Chatverlauf:\n{json.dumps(chat, ensure_ascii=False)[:4000]}\n\n"
                f"Die LETZTE Nachricht stammt von {who}:\n{mn.get('last_message', '')}\n\n"
                f"Antworte INHALTLICH. {addr} – NIE generisch '@Mensch'.")
        if args.handle == "esra":
            # Esra geht in die V-Schritt-Persona des Items UND nutzt die Norm-Tools.
            try:
                vp = await _vstep_persona(session, proj, item.get("phase"))
                if vp:
                    system = vp + "\n\n" + (args.persona or "")
                norms = _tool_rows(await session.call_tool("search_norms", {
                    "query": (mn.get("last_message") or item.get("body") or "")[:500], "n": 5}))
                if norms:
                    user += ("\n\nNORM-TREFFER (search_norms, RAG):\n"
                             + json.dumps(norms, ensure_ascii=False)[:2500])
            except Exception:
                pass
        loc = await _locality_line(session, proj, args.handle)
        if loc:
            user += "\n\n" + loc
        try:
            answer = await asyncio.to_thread(_llm_text, args.provider, args.model,
                                             args.llm_base, args.api_key, system, user)
        except Exception as exc:
            print(f"[worker {args.handle}] LLM-Fehler ({ident}): {exc}", file=sys.stderr, flush=True)
            continue
        if answer:
            try:
                await session.call_tool("post_item_chat", {
                    "project_key": proj, "identifier": ident,
                    "message": answer, "sender": "@" + args.handle})
                print(f"[worker {args.handle}] {ident} beantwortet ({len(answer)} Z.)", flush=True)
            except Exception as exc:
                print(f"[worker {args.handle}] post_item_chat: {exc}", file=sys.stderr, flush=True)


_chat_attempts = {}   # session_id → zuletzt bearbeitete Nachricht (gegen Endlos-Retry)


async def _locality_line(session, proj, handle):
    """Roster-Zeile für den Persona-Prompt: eigene Lokalität + die der anderen
    verbundenen Personas (lokal/extern), damit eine LOKALE Persona eine EXTERNE für
    eine externe Verifikation/Zweitmeinung per @handle ansprechen kann."""
    try:
        roster = _tool_rows(await session.call_tool("list_personas", {"project_key": proj}))
    except Exception:
        return ""
    if not roster:
        return ""
    hl = (handle or "").lower()
    me = next((r for r in roster if (r.get("handle") or "").lower() == hl), None)
    others = [r for r in roster if (r.get("handle") or "").lower() != hl]
    tag = lambda r: "lokal" if r.get("locality") == "local" else "extern"
    parts = []
    if me:
        parts.append(f"Du läufst {'LOKAL' if me.get('locality') == 'local' else 'EXTERN'}.")
    if others:
        parts.append("Verbundene Personas: "
                     + ", ".join(f"@{r['handle']} ({tag(r)})" for r in others) + ".")
        ext = [f"@{r['handle']}" for r in others if r.get("locality") == "external"]
        if ext:
            parts.append("Für eine EXTERNE Verifikation/Zweitmeinung sprich eine externe "
                         "Persona per @handle an, z. B. " + ", ".join(ext) + ".")
    return " ".join(parts)


async def _chat_once(session, args, proj):
    """Persona-Teilnahme an Projekt-/RAG-Chats inkl. (begrenztem) Inter-Persona-
    Dialog: auf @<handle>-Erwähnungen in Chat-Sessions antworten."""
    try:
        mentions = _tool_rows(await session.call_tool(
            "list_my_chat_mentions", {"project_key": proj, "handle": args.handle}))
    except Exception as exc:
        print(f"[worker {args.handle}] list_my_chat_mentions({proj}): {exc}",
              file=sys.stderr, flush=True)
        return
    for mn in mentions:
        sid = mn.get("session_id")
        if not sid:
            continue
        # Dieselbe letzte Nachricht NICHT wiederholt verarbeiten (z. B. bei API-
        # Fehler/401 sonst Dauer-Retry alle paar Sekunden).
        sig = (mn.get("last_message") or "")[:160]
        if _chat_attempts.get(sid) == sig:
            continue
        _chat_attempts[sid] = sig
        try:
            chat = _tool_rows(await session.call_tool("get_chat", {"session_id": sid}))
        except Exception:
            chat = []
        system = ((args.chat_persona or args.persona
                   or CHAT_SYSTEM.format(handle="@" + args.handle))
                  + "\n\n" + CHAT_MODE_RULES)
        last_sender = mn.get("last_sender") or ""
        last_name = mn.get("last_sender_name") or ""
        who = (f"{last_sender} ({last_name})" if last_sender and last_name
               else last_sender or last_name or "ein Teilnehmer")
        addr = (f"Sprich {last_sender} direkt mit diesem Handle an"
                if last_sender else "Sprich die Person nicht mit einem erfundenen Handle an")
        user = (f"Chat-Verlauf (jede Nachricht hat 'sender_handle'):\n"
                f"{json.dumps(chat, ensure_ascii=False)[:4000]}\n\n"
                f"Die LETZTE Nachricht stammt von {who}:\n{mn.get('last_message', '')}\n\n"
                f"Antworte als @{args.handle} INHALTLICH auf diese letzte Nachricht "
                f"(keine Begrüßungsfloskel). {addr} – NIE generisch '@Mensch'. "
                f"Andere darfst du per ihren sender_handle adressieren. Halte dich kurz.")
        if args.handle == "esra":
            # Esra darf/soll im PROJEKT-Chat Aussagen über das GANZE Projekt
            # treffen → Projekt-Überblick (alle Items + Eingangsdokumente) UND die
            # Norm-Treffer zur Frage über die MCP-Tools beziehen.
            try:
                items = _tool_rows(await session.call_tool(
                    "list_workitems", {"project_key": proj}))
                if items:
                    user += ("\n\nPROJEKT-ITEMS (komplett, list_workitems):\n"
                             + json.dumps(items, ensure_ascii=False)[:3500])
            except Exception:
                pass
            try:
                docs = _tool_rows(await session.call_tool(
                    "list_project_documents", {"project_key": proj}))
                if docs:
                    user += ("\n\nPROJEKT-DOKUMENTE (list_project_documents):\n"
                             + json.dumps(docs, ensure_ascii=False)[:1500])
            except Exception:
                pass
            try:
                norms = _tool_rows(await session.call_tool("search_norms", {
                    "query": (mn.get('last_message') or '')[:400], "n": 5}))
                if norms:
                    user += ("\n\nNORM-TREFFER (search_norms):\n"
                             + json.dumps(norms, ensure_ascii=False)[:2000])
            except Exception:
                pass
        loc = await _locality_line(session, proj, args.handle)
        if loc:
            user += "\n\n" + loc
        try:
            answer = await asyncio.to_thread(_llm_text, args.provider, args.model,
                                             args.llm_base, args.api_key, system, user)
        except Exception as exc:
            print(f"[worker {args.handle}] Chat-LLM-Fehler: {exc}", file=sys.stderr, flush=True)
            continue
        if answer:
            try:
                await session.call_tool("post_chat", {
                    "session_id": sid, "message": answer, "sender": "@" + args.handle,
                    "reply_to": mn.get("last_id") or 0})
                print(f"[worker {args.handle}] Chat {sid} beantwortet ({len(answer)} Z.)", flush=True)
            except Exception as exc:
                print(f"[worker {args.handle}] post_chat: {exc}", file=sys.stderr, flush=True)


# ── Esra: event-getriebene Normenrecherche (Queue-Tasks) ─────────────────
def _llm_keywords(args, text):
    """Lässt das (lokale) LLM 4–8 prägnante Schlagwort-Slugs für einen Chunk
    vergeben. Liefert eine Liste kurzer Slugs."""
    import re
    sysmsg = ("Du vergibst 4–8 prägnante Schlagworte (Fachbegriffe, Normen, Größen) "
              "für den Textauszug. Antworte NUR mit einem JSON-Array kurzer "
              "Kleinbuchstaben-Slugs, z. B. [\"sil-2\",\"diagnose\",\"iec-61508\"]. "
              "Keine Erklärung.")
    out = _llm_text(args.provider, args.model, args.llm_base, args.api_key, sysmsg, text[:1500])
    m = re.search(r"\[.*\]", out or "", re.S)
    try:
        arr = json.loads(m.group(0)) if m else []
    except Exception:
        arr = []
    return [str(x).strip().lower()[:60] for x in arr if str(x).strip()][:8]


async def _esra_tag_document(session, args, proj, doc_id):
    chunks = _tool_rows(await session.call_tool(
        "list_document_chunks", {"project_key": proj, "doc_id": doc_id, "limit": 300}))
    tagged = 0
    for c in chunks:
        if c.get("keywords") or len((c.get("text") or "")) < 25:
            continue                                  # schon getaggt / trivial
        kws = await asyncio.to_thread(_llm_keywords, args, c.get("text", ""))
        if kws:
            await session.call_tool("tag_chunk", {
                "project_key": proj, "chunk_uid": c["uid"], "keywords": kws})
            tagged += 1
    return f"{tagged} Chunk(s) verschlagwortet"


async def _esra_match_item(session, args, proj, identifier):
    item = _tool_json(await session.call_tool(
        "get_workitem", {"project_key": proj, "identifier": identifier})) or {}
    catalog = _tool_rows(await session.call_tool("list_norm_keywords", {}))
    user = (f"ITEM {identifier}: {item.get('title', '')}\n{(item.get('body') or '')[:1500]}\n\n"
            f"NORM-SCHLAGWORTKATALOG (je Norm die Schlagworte):\n"
            f"{json.dumps(catalog, ensure_ascii=False)[:3000]}\n\n"
            "WORT-ABGLEICH: welche Normen passen über ÜBEREINSTIMMENDE Schlagworte? "
            "Antworte knapp: passende Norm(en) + die Treffer-Schlagworte.")
    ans = await asyncio.to_thread(_llm_text, args.provider, args.model, args.llm_base,
                                  args.api_key, args.persona or "Du bist Esra.", user)
    if ans:
        await session.call_tool("post_item_chat", {
            "project_key": proj, "identifier": identifier,
            "message": "📜 Esra (Normenabgleich):\n" + ans, "sender": "@esra"})
    return "Item↔Normen abgeglichen"


async def _esra_once(session, args, proj):
    task = _tool_json(await session.call_tool(
        "next_esra_task", {"project_key": proj})) or {}
    tid = task.get("task_id")
    if not tid:
        return
    print(f"[worker {args.handle}] Esra-Task {tid} ({task.get('kind')}) @ {proj}", flush=True)
    try:
        if task.get("kind") == "TAG_DOC" and task.get("doc_id"):
            note = await _esra_tag_document(session, args, proj, task["doc_id"])
        elif task.get("kind") == "MATCH_ITEM" and task.get("identifier"):
            note = await _esra_match_item(session, args, proj, task["identifier"])
        else:
            note = "übersprungen (kein Ziel)"
        await session.call_tool("complete_esra_task",
                                {"task_id": tid, "ok": True, "note": note[:500]})
    except Exception as exc:
        await session.call_tool("complete_esra_task",
                                {"task_id": tid, "ok": False, "note": str(exc)[:500]})


async def _translation_once(session, args, proj):
    """Tertius: ARBEITET DAS ÜBERSETZUNGS-BACKLOG AB — holt offene Aufgaben (vom
    Auto-Übersetzen beim Öffnen erzeugt) per MCP, bis keine mehr offen sind,
    übersetzt je per LLM und schreibt das Ergebnis zurück."""
    for _ in range(50):                               # Backlog-Schranke pro Zyklus
        task = _tool_json(await session.call_tool(
            "next_translation_task", {"project_key": proj})) or {}
        ident = task.get("identifier")
        if not ident:
            return                                    # Backlog leer
        print(f"[worker {args.handle}] übersetze {ident} → {task.get('lang')} @ {proj}", flush=True)
        system = args.persona or "Du bist ein Übersetzer. Gib NUR die Übersetzung aus."
        user = (f"Übersetze den folgenden Text vollständig und treu nach "
                f"{task.get('lang_name') or task.get('lang')}. Gib NUR die Übersetzung aus:\n\n"
                f"{task.get('title', '')}\n{task.get('body', '')}")
        try:
            out = await asyncio.to_thread(_llm_text, args.provider, args.model,
                                          args.llm_base, args.api_key, system, user)
            ok = True
        except Exception as exc:
            out, ok = f"Übersetzung fehlgeschlagen: {exc}", False
        try:
            await session.call_tool("complete_translation", {
                "project_key": proj, "identifier": ident,
                "lang": task.get("lang"), "text": out, "ok": ok})
        except Exception as exc:
            print(f"[worker {args.handle}] complete_translation: {exc}", file=sys.stderr, flush=True)


async def _projects(session, args):
    """System-Personas arbeiten projektübergreifend (ALLE Projekte); normale Worker
    nur ihr eigenes."""
    if not args.system:
        return [args.project]
    rows = _tool_rows(await session.call_tool("list_projects", {}))
    keys = [p.get("key") for p in rows if isinstance(p, dict) and p.get("key")]
    return keys or [args.project]


@contextlib.asynccontextmanager
async def _transport(use_sse, url, headers):
    """Verbindung zum MCP-Server: Streamable HTTP (Standard) oder SSE (veraltet)."""
    if use_sse:
        from mcp.client.sse import sse_client
        async with sse_client(url, headers=headers) as (read, write):
            yield read, write
    else:
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            yield read, write


async def _mcp_loop(args, inbox):
    from mcp import ClientSession
    use_sse = args.transport == "sse"
    url = (f"{args.mcp_base.rstrip('/')}/{args.project}/{args.scope}/"
           + ("sse" if use_sse else "mcp"))
    # Direkter on-box-Client (localhost) → KEIN nginx-/mcp-Präfix: leerer
    # X-Forwarded-Prefix weist den Server an, den messages-Pfad ohne /mcp zu bauen.
    headers = {"Authorization": f"Bearer {args.token}", "X-Forwarded-Prefix": ""}
    while True:
        try:
            async with _transport(use_sse, url, headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    print(f"[worker {args.handle}] MCP verbunden: {url}"
                          + (" (system/alle Projekte)" if args.system else ""), flush=True)
                    while True:
                        for proj in await _projects(session, args):
                            await _poll_once(session, args, proj)
                            await _chat_once(session, args, proj)   # Projekt-/RAG-Chats
                            if args.handle == "esra":
                                await _esra_once(session, args, proj)
                            if args.handle == "tertius":
                                await _translation_once(session, args, proj)
                        await asyncio.sleep(args.interval)
        except Exception as exc:
            print(f"[worker {args.handle}] MCP-Fehler ({exc}); reconnect 5s",
                  file=sys.stderr, flush=True)
            await asyncio.sleep(5)


async def _amain(args):
    inbox = []           # Inter-Worker-Nachrichten (Nebenkanal)
    await asyncio.gather(_mcp_loop(args, inbox), _socket_register(args, inbox))


def main():
    ap = argparse.ArgumentParser(description="ELISA MCP-Client-Worker")
    ap.add_argument("--mcp-base", default=os.getenv("MCP_PUBLIC_BASE", "http://127.0.0.1:8765"))
    ap.add_argument("--transport", choices=["http", "sse"],
                    default=os.getenv("MCP_CLIENT_TRANSPORT", "http"),
                    help="MCP-Transport: http = Streamable HTTP (Standard), sse = veraltet")
    ap.add_argument("--project", required=True)
    ap.add_argument("--scope", default="all")
    ap.add_argument("--token", required=True)
    ap.add_argument("--handle", required=True)
    ap.add_argument("--provider", default="claude", choices=["claude", "openai", "ollama"])
    ap.add_argument("--model", default="")
    ap.add_argument("--llm-base", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--socket", default="")
    ap.add_argument("--persona", default="")     # System-Prompt (z. B. Esra); leer = generisch
    ap.add_argument("--chat-persona", default="")  # kurze Persona nur für den Chat (optional)
    ap.add_argument("--system", action="store_true")  # projektübergreifend (alle Projekte)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()
    try:
        asyncio.run(_amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
