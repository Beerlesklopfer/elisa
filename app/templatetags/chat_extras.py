"""Template-Filter für die Chat-Darstellung."""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# @handle (Buchstaben/Ziffern/-/_ inkl. Umlaute) – hebt Erwähnungen hervor.
_MENTION = re.compile(r"(@[\wäöüÄÖÜß\-]+)")


@register.filter
def highlight_mentions(text):
    """Hebt @handle-Erwähnungen als neutrale Chips hervor (HTML-sicher).
    Wird in ALLEN Chats verwendet; bewusst KEINE Warnfarbe."""
    out = escape(text or "")
    out = _MENTION.sub(r'<span class="mention">\1</span>', out)
    return mark_safe(out)


def _link_norms(escaped):
    """Norm-Referenzen im (bereits escapeten) Text: VORHANDEN → klickbarer Link
    (Quelle), FEHLEND → rot-fett."""
    from urllib.parse import quote
    from django.urls import reverse
    from app import norm_refs
    maps = norm_refs.norm_file_map()
    try:
        base = reverse("norms-download")
    except Exception:
        base = "/normen/download/"

    def repl(m):
        token = m.group(1)
        f = norm_refs.file_for(token, maps)
        if f:
            return (f'<a href="{base}?name={quote(f)}" class="norm-cite" '
                    f'data-name="{escape(f)}" title="{escape(f)}">'
                    f'<i class="fas fa-book-open me-1"></i>{token}</a>')
        return (f'<span class="text-danger fw-bold" '
                f'title="Norm nicht im System">{token}</span>')

    return norm_refs._STD_RE.sub(repl, escaped)


@register.filter
def glyph_map_json(participants):
    """{handle: {icon,color}} der LLM-Teilnehmer als JSON – damit das Frontend die
    Provider-Icons UND eine provider-spezifische Hintergrund-Tönung an die
    Nachrichten-Absender hängen kann. Enthält zusätzlich die RAG-Persona (Lukas,
    lokales Ollama), die per Klarnamen statt @-Handle auftritt."""
    import json
    from django.conf import settings
    from app.participants import PROVIDER_GLYPH
    m = {p.get("handle"): {"icon": p.get("icon", "fa-robot"), "color": p.get("color", "")}
         for p in (participants or []) if p.get("kind") == "llm" and p.get("handle")}
    rag = getattr(settings, "RAG_PERSONA_NAME", "Lukas")
    icon, color = PROVIDER_GLYPH.get("OLLAMA", ("fa-robot", "#5a5a5a"))
    m.setdefault(rag, {"icon": icon, "color": color})
    return mark_safe(json.dumps(m))


_MD_TAGS = ["p", "br", "strong", "em", "b", "i", "code", "pre", "blockquote",
            "ul", "ol", "li", "h1", "h2", "h3", "h4", "hr", "a", "table", "thead",
            "tbody", "tr", "th", "td", "del"]
_MD_ATTRS = {"a": ["href", "title"]}
_TAG_SPLIT = re.compile(r"(<[^>]+>)")


def _markdown_html(text):
    """Markdown → bereinigtes HTML. Rohes HTML aus dem Text wird NICHT durchgelassen
    (bleach mit fester Tag-/Attribut-Liste, nur http/https/mailto-Links)."""
    import bleach
    import markdown
    html = markdown.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])
    return bleach.clean(html, tags=_MD_TAGS, attributes=_MD_ATTRS,
                        protocols=["http", "https", "mailto"], strip=True)


@register.filter
def chat_render_plain(text):
    """Wie chat_render, aber OHNE Markdown (für Zeilen mit white-space:pre-wrap,
    z. B. den Item-Chat): escapen, @mentions als Chips, Norm-Referenzen."""
    out = escape(text or "")
    out = _MENTION.sub(r'<span class="mention">\1</span>', out)
    return mark_safe(_link_norms(out))


@register.filter
def chat_render(text):
    """Chat-Nachricht rendern: Markdown (sicher bereinigt), dazu @mentions als Chips
    und Norm-Referenzen (VORHANDEN → Quellen-Link, FEHLEND → rot-fett). Mentions und
    Norm-Referenzen wirken nur auf Text, nicht in Tags/Code-Blöcken."""
    html = _markdown_html(text)
    out, in_code = [], 0
    for part in _TAG_SPLIT.split(html):
        if part.startswith("<"):
            low = part.lower()
            if low.startswith(("<code", "<pre")):
                in_code += 1
            elif low.startswith(("</code", "</pre")):
                in_code = max(0, in_code - 1)
            out.append(part)
        elif in_code or not part:
            out.append(part)
        else:
            seg = _MENTION.sub(r'<span class="mention">\1</span>', part)
            out.append(_link_norms(seg))
    return mark_safe("".join(out))
