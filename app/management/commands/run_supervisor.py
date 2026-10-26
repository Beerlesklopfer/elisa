"""
Supervisor (systemd-Service, ersetzt run_feedback_worker).

Aufgabe:
  • STARTET je aktivem WorkerBackend (= Projekt + Persona/Scope + Provider) einen
    MCP-Client-Worker-Prozess und ÜBERWACHT ihn (Auto-Restart, Reload bei Konfig-
    Änderung im Admin). Reconcile-Loop 1×/Minute.
  • Führt den Unix-Socket (settings.SUPERVISOR_SOCKET) als REGISTER + RELAY: die
    Worker registrieren sich und tauschen darüber NUR untereinander Nachrichten
    aus (client-to-client). Die eigentliche Arbeit läuft über MCP-Chat (Primär).
  • Schreibt einen Status-Snapshot (settings.SUPERVISOR_STATUS) fürs Admin.

    python manage.py run_supervisor
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Supervisor: startet/überwacht MCP-Client-Worker + Unix-Socket-Relay."

    def handle(self, *args, **opts):
        self.stdout.write(self.style.SUCCESS("Supervisor startet (Strg-C zum Beenden)."))
        try:
            asyncio.run(_supervise())
        except KeyboardInterrupt:
            self.stdout.write("\nSupervisor beendet.")


def _worker_provider(provider) -> str:
    p = (provider or "").upper()
    if p == "CLAUDE":
        return "claude"
    if p == "OLLAMA":
        return "ollama"
    return "openai"            # OpenAI-kompatibel (LM Studio / DeepSeek / ChatGPT)


def _persona_for(handle, scope):
    """System-Prompt je Persona: Esra = Normenrecherche; sonst die V-Schritt-
    Persona (LLMRoleDescription) passend zum Token-Scope; ALL/unbekannt = leer."""
    from app.models import LLMRoleDescription
    # System-Personas: Prompt aus der ADMIN-editierbaren Rollenbeschreibung
    # (role = ESRA/TERTIUS/NATHAN); Konstante nur als Fallback.
    sys_role = {"lukas": "LUKAS", "esra": "ESRA", "tertius": "TERTIUS",
                "nathan": "NATHAN"}.get(handle)
    if sys_role:
        rd = LLMRoleDescription.objects.filter(role=sys_role).first()
        if rd and rd.description:
            return rd.description
        from app.apps import (LUKAS_PERSONA, ESRA_PERSONA, TRANSLATOR_PERSONA,
                              NATHAN_PERSONA)
        return {"lukas": LUKAS_PERSONA, "esra": ESRA_PERSONA, "tertius": TRANSLATOR_PERSONA,
                "nathan": NATHAN_PERSONA}[handle]
    role = (scope or "").upper()
    obj = LLMRoleDescription.objects.filter(role=role).first() if role and role != "ALL" else None
    return obj.description if obj else ""


def _load_backends():
    """Aktive WorkerBackends als self-contained dicts (für Subprozess-Args)."""
    from app.models import WorkerBackend
    out = []
    for b in WorkerBackend.objects.filter(active=True).select_related("token__project"):
        t = b.token
        if not t or not t.project_id:
            continue
        out.append({
            "id": b.id, "name": b.name,
            "mcp_base": b.effective_mcp_base or settings.MCP_PUBLIC_BASE,
            "project": t.project.key, "scope": t.scope_slug, "token": t.token,
            "provider": _worker_provider(b.provider), "model": b.effective_model or "",
            "llm_base": b.effective_base_url or "", "api_key": b.effective_api_key or "",
            "handle": b.effective_handle,
            "persona": _persona_for(b.effective_handle, t.scope_slug),
            "system": bool(getattr(t, "system", False)),
        })
    return out


async def _spawn(b):
    args = [sys.executable, "-m", "mcp_worker.mcp_client_worker",
            "--mcp-base", b["mcp_base"], "--project", b["project"], "--scope", b["scope"],
            "--token", b["token"], "--handle", b["handle"], "--provider", b["provider"],
            "--model", b["model"], "--llm-base", b["llm_base"], "--api-key", b["api_key"],
            "--persona", b.get("persona", ""), "--socket", str(settings.SUPERVISOR_SOCKET)]
    if b.get("system"):
        args.append("--system")
    print(f"[supervisor] starte {b['name']} ({b['handle']} @ {b['project']}/{b['scope']})",
          flush=True)
    return await asyncio.create_subprocess_exec(*args, cwd=str(settings.BASE_DIR))


async def _reconcile(procs):
    from asgiref.sync import sync_to_async
    want = {b["id"]: b for b in
            await sync_to_async(_load_backends, thread_sensitive=True)()}
    for bid in list(procs):                       # nicht mehr aktiv → stoppen
        if bid not in want:
            p = procs.pop(bid)
            try:
                p["proc"].terminate()
            except Exception:
                pass
            print(f"[supervisor] gestoppt: {p['info']['name']}", flush=True)
    for bid, b in want.items():                   # neu / abgestürzt / geändert → (neu) starten
        cur = procs.get(bid)
        if cur and cur["proc"].returncode is None:
            if cur["info"] == b:
                continue                          # läuft + Konfig unverändert
            try:                                  # Konfig geändert (Modell/Token/…) → neu
                cur["proc"].terminate()
            except Exception:
                pass
            print(f"[supervisor] Konfig geändert → starte {b['name']} neu", flush=True)
        procs[bid] = {"proc": await _spawn(b), "info": b}


def _write_status(procs, clients):
    status = {
        "workers": [{"id": bid, "name": p["info"]["name"], "handle": p["info"]["handle"],
                     "project": p["info"]["project"], "scope": p["info"]["scope"],
                     "running": p["proc"].returncode is None}
                    for bid, p in procs.items()],
        "connected": sorted({i.get("handle") for i in clients.values() if i.get("handle")}),
    }
    try:
        Path(settings.SUPERVISOR_STATUS).write_text(json.dumps(status, ensure_ascii=False))
    except Exception:
        pass


async def _supervise():
    sock = str(settings.SUPERVISOR_SOCKET)
    Path(sock).parent.mkdir(parents=True, exist_ok=True)
    try:
        os.unlink(sock)
    except FileNotFoundError:
        pass

    clients = {}     # writer -> register-info
    procs = {}       # backend_id -> {proc, info}

    async def handle_client(reader, writer):
        info = {}
        try:
            first = await reader.readline()
            if not first:
                return
            try:
                info = json.loads(first.decode())
            except Exception:
                info = {}
            clients[writer] = info
            print(f"[supervisor] Worker am Socket: {info.get('handle')} "
                  f"@ {info.get('project')}/{info.get('scope')}", flush=True)
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except Exception:
                    continue
                # RELAY (client-to-client): an Ziel-Handle bzw. Broadcast.
                to = msg.get("to")
                msg.setdefault("from", info.get("handle"))
                data = (json.dumps(msg, ensure_ascii=False) + "\n").encode()
                for w, i in list(clients.items()):
                    if w is writer:
                        continue
                    if to in (None, "*", i.get("handle")):
                        try:
                            w.write(data)
                            await w.drain()
                        except Exception:
                            pass
        finally:
            clients.pop(writer, None)
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_unix_server(handle_client, path=sock)
    try:
        os.chmod(sock, 0o660)
    except Exception:
        pass
    print(f"[supervisor] Socket bereit: {sock}", flush=True)

    async with server:
        asyncio.ensure_future(server.serve_forever())
        while True:                                 # Reconcile-Loop 1×/Minute
            try:
                await _reconcile(procs)
                _write_status(procs, clients)
            except Exception as exc:
                print(f"[supervisor] Reconcile-Fehler: {exc}", file=sys.stderr, flush=True)
            await asyncio.sleep(60)
