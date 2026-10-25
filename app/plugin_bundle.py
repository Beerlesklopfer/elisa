"""
Erzeugung einer installierbaren **.mcpb** (Desktop-Extension) je MCP-Persona.

End-User dürfen LOKALE Extensions installieren; diese bridged per
`npx mcp-remote` auf unseren Remote-SSE-Server und gibt den Bearer-Header mit.
URL + Token stehen vorbelegt im `user_config` (Token maskiert).
"""
from __future__ import annotations

import json
import os

from app import llm_roles
from app.models import VModelRole


def mcp_base() -> str:
    return os.getenv("MCP_PUBLIC_BASE", "http://192.168.88.252/mcp")


def _meta(token):
    """(name, beschreibung, persona, sse_url) für einen Token/Persona."""
    proj = token.project
    pkey = proj.key if proj else "elisa"
    role = token.scope if token.scope in VModelRole.values else None
    role_label = dict(VModelRole.choices).get(role, "Gesamtes V-Modell")
    iec = llm_roles.iec_reference_for(role) if role else ""
    name = f"elisa-{pkey}-{token.scope_slug}"
    short_desc = (f"ELISA MCP – {proj.name if proj else 'Projekt'} · {role_label}"
                  + (f" ({iec})" if iec else ""))
    persona = (llm_roles.context_for(project=proj, role=role) if role
               else (f"PROJEKT: {proj.name}\n{(proj.description or '').strip()}"
                     if proj else ""))
    return name, short_desc, persona, f"{mcp_base()}/{token.url_path}/sse"


def mcpb(token):
    """Liefert (name, {relpfad: inhalt}) für die .mcpb (manifest.json im Wurzel)."""
    name, short_desc, persona, sse_url = _meta(token)
    manifest = {
        "dxt_version": "0.1",
        "name": name,
        "version": "1.0.0",
        "description": short_desc,
        "author": {"name": "ELISA"},
        "user_config": {
            "url": {"type": "string", "title": "MCP-Endpunkt (SSE)",
                    "description": short_desc, "required": True, "default": sse_url},
            "token": {"type": "string", "title": "Bearer-Token",
                      "description": "Persönliches Bearer-Token für diese Persona.",
                      "sensitive": True, "required": True, "default": token.token},
        },
        "server": {
            "type": "node",
            "entry_point": "server/index.js",
            "mcp_config": {
                "command": "npx",
                "args": ["-y", "mcp-remote", "${user_config.url}",
                         "--header", "Authorization: Bearer ${user_config.token}"],
            },
        },
    }
    files = {
        "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False),
        "server/index.js": ("// Bridge zu Remote-SSE über `npx mcp-remote` – "
                            "Ausführung siehe manifest.json (server.mcp_config).\n"),
        "README.md": f"# {short_desc}\n\n## Persona\n\n{persona}\n\nRemote-Endpunkt: {sse_url}\n",
    }
    return name, files
