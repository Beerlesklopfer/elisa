"""
Teilnehmer eines Projekt-Chats (für ALLE Chat-Systeme: Item-Chat + Chat).

Menschen (Projektmitglieder, @vorname) UND angeschlossene LLM-Backends
(@claude/@ollama …). Jeder Teilnehmer trägt einen Online-Status (who-is-online):
Mensch = kürzlich aktiv (presence-Cache), LLM = MCP-Token kürzlich benutzt.
"""
import re
from datetime import timedelta

from django.utils import timezone

from .presence import is_online, PRESENCE_TTL

# Provider → kurzes @-Handle.
_PROVIDER_HANDLE = {"CLAUDE": "claude", "OPENAI": "chatgpt", "DEEPSEEK": "deepseek",
                    "OLLAMA": "ollama", "LMSTUDIO": "lmstudio", "CUSTOM": "llm"}

# Provider → (FontAwesome-Icon, Markenfarbe) – damit man im Chat sofort sieht,
# WELCHER Anbieter dahintersteckt (repräsentativ, nicht die geschützten Logos).
PROVIDER_GLYPH = {
    "CLAUDE":   ("fa-star-of-life", "#d97757"),   # Anthropic-Clay
    "OPENAI":   ("fa-atom",         "#10a37f"),   # OpenAI-Grün
    "DEEPSEEK": ("fa-water",        "#4d6bfe"),
    "OLLAMA":   ("fa-horse-head",   "#5a5a5a"),   # Lama
    "LMSTUDIO": ("fa-flask",        "#7048e8"),
    "CUSTOM":   ("fa-robot",        "#6c757d"),
}


def _glyph(provider):
    icon, color = PROVIDER_GLYPH.get((provider or "").upper(), PROVIDER_GLYPH["CUSTOM"])
    return {"provider": (provider or "").upper(), "icon": icon, "color": color}


# Lokalität: läuft die Persona auf EIGENER Infrastruktur (lokal) oder über einen
# externen Cloud-Dienst (extern)? Zweck: eine LOKALE Persona soll eine EXTERNE
# erkennen, um sie um eine externe Verifikation/Zweitmeinung zu bitten.
LOCAL_PROVIDERS = {"OLLAMA", "LMSTUDIO"}
EXTERNAL_PROVIDERS = {"CLAUDE", "OPENAI", "DEEPSEEK", "ANTHROPIC"}


def _host_is_local(base_url):
    """True, wenn der Host der base_url auf eine PRIVATE/Loopback/Link-Local-IP
    zeigt – per DNS-Auflösung (deckt auch LAN-Hostnamen ab, nicht nur IP-Präfixe)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    if not base_url:
        return False
    host = urlparse(base_url if "://" in base_url else "//" + base_url).hostname or ""
    if not host:
        return False

    # Die konfigurierte lokale Inferenz (settings.LOCAL_LLM_HOST) ist per Definition
    # lokal – auch wenn sie über einen LAN-Hostnamen (GPU-Server) läuft.
    try:
        from django.conf import settings
        own = urlparse(settings.OLLAMA_HOST).hostname
        if own and host.lower() == own.lower():
            return True
    except Exception:
        pass

    def _is_local_ip(addr):
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        return ip.is_private or ip.is_loopback or ip.is_link_local

    if _is_local_ip(host):                       # base_url enthält schon eine IP
        return True
    try:                                          # Hostname → IP(s) auflösen
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return host == "localhost"
    return any(_is_local_ip(sa[0]) for *_, sa in infos)


def locality_of(provider, base_url=""):
    """'local' oder 'external' für ein Backend. Klar zuordenbare Provider direkt;
    CUSTOM/unbekannt über DNS-Auflösung der base_url (private/loopback = lokal)."""
    p = (provider or "").upper()
    if p in LOCAL_PROVIDERS:
        return "local"
    if p in EXTERNAL_PROVIDERS:
        return "external"
    return "local" if _host_is_local(base_url) else "external"


def slug_handle(s):
    """Klein, ASCII, ohne Sonderzeichen – für @-Handles (Vorname → @vorname)."""
    s = (s or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "", s)


def chat_participants(project):
    """Liste der Chat-Teilnehmer mit @-Handle, Art und Online-Status.
    Menschen = Projektmitglieder (@vorname); LLMs = aktive MCP-Tokens des
    Projekts (@claude/@ollama …, online wenn das Token kürzlich benutzt wurde)."""
    from .models import MCPToken, WorkerBackend, ProjectMembership
    out, used = [], set()
    # Menschen: Projektmitglieder – Handle = Vorname.
    for m in (ProjectMembership.objects.filter(project=project)
              .select_related("user")):
        u = m.user
        h = slug_handle(u.first_name) or slug_handle(u.username) or f"user{u.pk}"
        if h in used:
            h2 = f"{h}-{slug_handle(u.last_name)}" if u.last_name else f"{h}-{u.pk}"
            h = h2 if h2 not in used else f"{h}-{u.pk}"
        used.add(h)
        out.append({"handle": h, "label": u.get_full_name() or u.username,
                    "kind": "human", "info": m.get_role_display(),
                    "online": is_online(u.pk)})
    # LLM-Teilnehmer = aktive MCP-Tokens (Zugangspunkte externer LLMs, z. B.
    # Claude). Online, wenn das Token kürzlich benutzt wurde. Handle aus dem
    # Provider eines verknüpften WorkerBackends, sonst aus dem Token-Namen.
    cutoff = timezone.now() - timedelta(seconds=PRESENCE_TTL)
    # 1) Aktive LLM-BACKENDS des Projekts = je ein Teilnehmer. Backend-basiert (nicht
    #    Token-basiert!), denn mehrere Backends dürfen sich einen Token teilen –
    #    sonst fiele bei geteiltem Token einer raus.
    seen_tokens = set()
    for b in (WorkerBackend.objects.filter(active=True, token__project=project)
              .select_related("token")):
        h = b.effective_handle
        if h in used:
            h = f"{h}-{b.pk}"
        used.add(h)
        t = b.token
        if t:
            seen_tokens.add(t.pk)
        lu = t.last_used if t else None
        out.append({"handle": h, "label": b.name, "kind": "llm",
                    "info": (f"{t.get_scope_display()} · {t.get_access_display()}"
                             if t else "LLM"),
                    "online": bool(lu and lu >= cutoff), **_glyph(b.provider)})
    # 2) Token-only-Zugänge (z. B. Claude Desktop ohne eigenes WorkerBackend).
    for t in (MCPToken.objects.filter(active=True, project=project)
              .exclude(pk__in=seen_tokens)):
        parts = (t.name or "").split()
        h = (slug_handle(parts[0]) if parts else "") or f"mcp{t.pk}"
        if h in used:
            h = f"{h}-{t.scope_slug}" if t.scope_slug != "all" else f"{h}-{t.pk}"
        used.add(h)
        out.append({"handle": h, "label": t.name or f"MCP {t.get_scope_display()}",
                    "kind": "llm",
                    "info": f"{t.get_scope_display()} · {t.get_access_display()}",
                    "online": bool(t.last_used and t.last_used >= cutoff),
                    **_glyph(None)})
    # Ollama ist KEIN Sonderfall mehr: es läuft (wie jedes LLM) als MCP-Worker über
    # ein WorkerBackend + Token und erscheint darüber als Teilnehmer.
    # Globale System-Personas (salinar/dragoman/auditor) sind in JEDEM Projekt
    # verfügbar – auch wenn ihr System-Token auf einem anderen Projekt gebunden ist.
    for b in (WorkerBackend.objects.filter(active=True, token__system=True)
              .select_related("token")):
        h = b.effective_handle
        if h in used:
            continue
        used.add(h)
        lu = b.token.last_used
        out.append({"handle": h, "label": b.name, "kind": "llm",
                    "info": "System-Persona · alle Projekte",
                    "online": bool(lu and lu >= cutoff), **_glyph(b.provider)})
    return out
