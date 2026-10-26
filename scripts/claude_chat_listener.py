#!/usr/bin/env python3
"""
Weckt ein angeschlossenes LLM (z. B. Claude Code) bei einem Arbeitsauftrag im Chat.

Fragt per MCP (Streamable HTTP, stateless) `list_my_chat_mentions` ab und schreibt für
jede NEUE Ansprache genau EINE Zeile nach stdout – gedacht für das Monitor-Werkzeug von
Claude Code, das jede Zeile als Benachrichtigung zustellt. Die Zeile nennt Session und
Nachricht; das LLM liest dann mit get_chat nach, führt den Auftrag mit den MCP-Tools aus
und antwortet mit post_chat(reply_to=…).

    python3 scripts/claude_chat_listener.py [--handle claude] [--project standard]
Verbindung: --url/--token oder der Eintrag "elisa" in ./.mcp.json (nie committen).
Nur Standardbibliothek.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def load_conn(args):
    url, token = args.url, args.token
    if not (url and token):
        cfg = json.load(open(args.mcp_json))["mcpServers"][args.server]
        url = url or cfg["url"]
        token = token or cfg["headers"]["Authorization"].split(" ", 1)[1]
    return url, token


def call(url, token, tool, arguments, timeout=15):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": arguments}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
    payload = None
    for line in raw.splitlines():                      # SSE ("data: {...}") oder reines JSON
        line = line[5:].strip() if line.startswith("data:") else line.strip()
        if line.startswith("{"):
            payload = json.loads(line)
    result = (payload or {}).get("result") or {}
    rows = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                v = json.loads(item["text"])
            except ValueError:
                continue
            rows.extend(v if isinstance(v, list) else [v])
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--handle", default="claude")
    ap.add_argument("--project", default="standard")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--url", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--mcp-json", default=".mcp.json")
    ap.add_argument("--server", default="elisa")
    ap.add_argument("--include-backlog", action="store_true",
                    help="auch bereits offene Ansprachen beim Start melden")
    args = ap.parse_args()
    seen, first, fails = set(), not args.include_backlog, 0
    print(f"[listener] @{args.handle} in '{args.project}' – warte auf Aufträge …", flush=True)
    while True:
        try:
            url, token = load_conn(args)          # jedes Mal neu lesen (URL/Token können wechseln)
            rows = call(url, token, "list_my_chat_mentions",
                        {"project_key": args.project, "handle": args.handle})
            for r in rows:
                key = (r.get("session_id"), r.get("last_id"))
                if key in seen:
                    continue
                seen.add(key)
                if first:
                    continue                      # Altbestand beim Start nicht melden
                text = (r.get("last_message") or "").replace("\n", " ")[:240]
                print(f"CHAT-AUFTRAG session={r.get('session_id')} msg={r.get('last_id')} "
                      f"von={r.get('last_sender') or '?'}: {text}", flush=True)
            first, fails = False, 0
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            fails += 1
            if fails == 6:                       # erst nach 6 Fehlversuchen in Folge melden
                print(f"[listener] Verbindungsproblem: {exc}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
