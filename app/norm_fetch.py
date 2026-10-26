"""
Normen aus dem Netz holen und den RAG-Index anstoßen – für angeschlossene LLMs (MCP),
die einen Arbeitsauftrag aus dem Chat ausführen („suche frei zugängliche Normen und
installiere sie ins RAG"). Reine Mechanik, keine Inhalte vom LLM.

Schutz: nur https, Host-Allowlist (settings.MCP_NORM_HOSTS), nur öffentliche IPs
(kein SSRF auf interne Dienste), Größenlimit, PDF-Magic-Check, kein Überschreiben.
Es dürfen nur frei lizenzierte Dokumente geladen werden – die Verantwortung für die
Auswahl liegt beim Menschen, der den Auftrag erteilt (Quelle wird protokolliert).
"""
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx
from django.conf import settings
from django.utils import timezone

MAX_BYTES = 80 * 1024 * 1024
MAX_HOPS = 5
_INDEX_PROC = None


class FetchError(Exception):
    pass


def _check_host(host):
    allowed = settings.MCP_NORM_HOSTS
    if "*" not in allowed and host.lower() not in allowed:
        raise FetchError(f"Host '{host}' ist nicht erlaubt (MCP_NORM_HOSTS: {', '.join(allowed)}).")
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError(f"Host '{host}' nicht auflösbar: {exc}")
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError(f"Host '{host}' zeigt auf eine nicht-öffentliche Adresse.")


def _safe_name(name, url, disposition=""):
    if not name:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disposition or "")
        name = unquote(m.group(1)) if m else unquote(Path(urlparse(url).path).name) or "norm"
    name = re.sub(r"[^\w.\- ]+", "_", Path(name).name, flags=re.UNICODE).strip(" ._") or "norm"
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def fetch_pdf(url, name="", requested_by=""):
    """Lädt ein PDF nach INCOMING_DIR. Liefert {file, bytes, sha256, source_url}."""
    cur = url
    with httpx.Client(timeout=60, follow_redirects=False,
                      headers={"User-Agent": "ELISA-norm-fetch/1.0"}) as cl:
        for _hop in range(MAX_HOPS + 1):
            p = urlparse(cur)
            if p.scheme != "https" or not p.hostname:
                raise FetchError("Nur https-URLs sind erlaubt.")
            _check_host(p.hostname)
            for attempt in range(6):            # EUR-Lex liefert zunächst 202 (wird erzeugt)
                with cl.stream("GET", cur) as r:
                    if r.status_code == 202 and attempt < 5:
                        time.sleep(3)
                        continue
                    if r.is_redirect:
                        cur = str(r.url.join(r.headers["location"]))
                        break
                    if r.status_code != 200:
                        raise FetchError(f"HTTP {r.status_code} von {p.hostname}.")
                    target = Path(settings.INCOMING_DIR) / _safe_name(
                        name, cur, r.headers.get("content-disposition", ""))
                    if target.exists():
                        raise FetchError(f"{target.name} existiert bereits in incoming/.")
                    h, size, first = hashlib.sha256(), 0, b""
                    Path(settings.INCOMING_DIR).mkdir(parents=True, exist_ok=True)
                    tmp = target.with_suffix(".part")
                    try:
                        with open(tmp, "wb") as out:
                            for chunk in r.iter_bytes(65536):
                                if not first:
                                    first = chunk[:5]
                                    if first != b"%PDF-":
                                        raise FetchError("Die Antwort ist kein PDF.")
                                size += len(chunk)
                                if size > MAX_BYTES:
                                    raise FetchError("Datei größer als 80 MB – abgebrochen.")
                                h.update(chunk)
                                out.write(chunk)
                        if not size:
                            raise FetchError("Leere Antwort.")
                        tmp.replace(target)
                    finally:
                        tmp.unlink(missing_ok=True)
                    meta = {"source_url": url, "final_url": cur, "sha256": h.hexdigest(),
                            "bytes": size, "fetched_at": timezone.now().isoformat(),
                            "requested_by": requested_by}
                    target.with_suffix(".source.json").write_text(
                        json.dumps(meta, ensure_ascii=False, indent=2))
                    return {"file": target.name, "bytes": size, "sha256": meta["sha256"],
                            "source_url": url}
        raise FetchError("Zu viele Weiterleitungen.")


def start_index(only=""):
    """Startet build_rag_index im Hintergrund (ein Lauf zur Zeit)."""
    global _INDEX_PROC
    if index_running():
        return {"started": False, "reason": "Indexierung läuft bereits."}
    args = [sys.executable, str(settings.BASE_DIR / "manage.py"), "build_rag_index"]
    if only:
        args += ["--only", Path(only).stem]
    try:
        log = open(Path(settings.DATA_DIR) / "rag_index.log", "ab")
    except OSError:
        log = subprocess.DEVNULL
    _INDEX_PROC = subprocess.Popen(args, cwd=str(settings.BASE_DIR), stdout=log, stderr=log)
    return {"started": True, "pid": _INDEX_PROC.pid}


def index_running():
    return _INDEX_PROC is not None and _INDEX_PROC.poll() is None


def index_status(tail_lines=6):
    lines = []
    try:
        lines = (Path(settings.DATA_DIR) / "rag_index.log").read_text(errors="replace").splitlines()[-tail_lines:]
    except OSError:
        pass
    return {"running": index_running(), "log_tail": lines}
