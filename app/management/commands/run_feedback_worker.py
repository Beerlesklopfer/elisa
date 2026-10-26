"""
Startet die im Admin verwalteten Persona-Worker-Backends (poll-frei, SSE).

Jedes aktive `WorkerBackend` läuft in einem eigenen Thread und bedient – über
seinen MCP-Token – genau EINEN V-Schritt (Persona) eines Projekts mit dem dort
gewählten Provider/Modell. So bekommt jede Persona ihren eigenen Provider „mit
der eigentlichen Stärke".

    python manage.py run_feedback_worker            # alle aktiven Backends
    python manage.py run_feedback_worker --name "Claude REQ"
"""
import threading

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Startet die aktiven Persona-Worker-Backends (SSE-Push, kein Poll)."

    def add_arguments(self, parser):
        parser.add_argument("--name", help="Nur dieses Backend (sonst alle aktiven).")
        parser.add_argument("--list", action="store_true",
                            help="Nur auflisten, nicht starten.")

    def handle(self, *args, **opts):
        from app.models import WorkerBackend
        from mcp_worker import worker

        qs = WorkerBackend.objects.filter(active=True).select_related("token__project")
        if opts.get("name"):
            qs = qs.filter(name=opts["name"])
        backends = list(qs)
        if not backends:
            self.stderr.write(self.style.WARNING("Keine aktiven Backends gefunden."))
            return

        runnable = []
        for b in backends:
            t = b.token
            if not t or not t.project_id:
                self.stderr.write(f"  ! {b.name}: kein Projekt-Token – übersprungen.")
                continue
            queue = f"{t.project.key}/{t.scope_slug}"
            flag = "" if t.access == "WRITE" else "  ⚠ Token NICHT WRITE (kein Rückschreiben!)"
            self.stdout.write(
                f"  • {b.name}: {b.get_provider_display()} / {b.effective_model} "
                f"→ {queue}{flag}")
            runnable.append((b, t, queue))

        if opts.get("list") or not runnable:
            return

        from app.participants import _PROVIDER_HANDLE, slug_handle
        threads = []
        for b, t, queue in runnable:
            # Chat-Handles: Provider-Handle (z. B. claude) + Token-Name (z. B. zpmc),
            # damit der Worker auf beide @-Schreibweisen reagiert.
            prov = _PROVIDER_HANDLE.get(b.provider, "llm")
            tokh = slug_handle((t.name or "").split()[0]) if t.name else ""
            handles = [h for h in dict.fromkeys([prov, tokh]) if h]
            params = dict(base=b.effective_mcp_base, project=t.project.key,
                          scope=t.scope_slug, token=t.token, backend=b.protocol,
                          model=b.effective_model, llm_base=b.effective_base_url,
                          api_key=b.effective_api_key, handles=handles,
                          sender="@" + (handles[0] if handles else "llm"))
            th = threading.Thread(target=worker.run, kwargs=params,
                                  name=b.name, daemon=True)
            th.start()
            threads.append(th)

        self.stdout.write(self.style.SUCCESS(
            f"{len(threads)} Worker laufen (SSE-Push). Strg-C zum Beenden."))
        try:
            for th in threads:
                th.join()
        except KeyboardInterrupt:
            self.stdout.write("\nBeende Worker …")
