"""
Markdown → sicheres HTML (für die Anzeige von WorkItem-Bodies, bes. REQ).

Nutzt `markdown` + `bleach` (Sanitisierung), wenn installiert; sonst Fallback
auf escaped Plaintext mit Zeilenumbrüchen. So funktioniert die Anzeige immer,
und nach Deploy (requirements.txt) wird echtes Markdown gerendert.
"""
import html as _htmlmod
import re as _re

from django.utils.html import escape

# ```mermaid-Codeblock → <div class="mermaid">…</div> (clientseitig zu SVG gerendert).
# NACH bleach angewandt; der Diagramm-Quelltext wird ent-escaped (Mermaid parst
# Diagramm-Syntax, kein HTML).
_MERMAID_RE = _re.compile(r'<pre><code class="language-mermaid">(.*?)</code></pre>', _re.S)


def _mermaidize(h: str) -> str:
    return _MERMAID_RE.sub(
        lambda m: '<div class="mermaid">' + _htmlmod.unescape(m.group(1)) + "</div>", h)


_TAGS = ["p", "br", "strong", "em", "b", "i", "u", "del", "code", "pre",
         "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
         "a", "hr", "table", "thead", "tbody", "tr", "th", "td", "span", "img"]
_ATTRS = {"a": ["href", "title", "rel"], "*": ["class"],
          # Bilder – inkl. base64-eingebetteter Bilder via data:-URI.
          "img": ["src", "alt", "title", "width", "height"]}
# data: erlaubt eingebettete base64-Bilder (![alt](data:image/png;base64,…)).
_PROTOCOLS = ["http", "https", "mailto", "data"]


def render(text: str) -> str:
    text = text or ""
    try:
        import markdown as _md
        html = _md.markdown(text, extensions=["extra", "sane_lists", "nl2br"])
        try:
            import bleach
            html = bleach.clean(html, tags=_TAGS, attributes=_ATTRS,
                                protocols=_PROTOCOLS, strip=True)
        except Exception:
            pass
        return _mermaidize(html)
    except Exception:
        return escape(text).replace("\n", "<br>")
