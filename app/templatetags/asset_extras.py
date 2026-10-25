"""Cache-Busting für eigene statische Assets.

`{% static_v 'js/chat.js' %}` liefert die normale Static-URL mit angehängtem
`?v=<mtime>` der Quelldatei. Ändert sich die Datei (Deploy), ändert sich die
URL automatisch → Browser/Proxy laden sie neu, statt eine veraltete Fassung aus
dem Cache zu zeigen. Reine Mechanik, ohne ManifestStaticFilesStorage (rührt die
Vendor-CSS mit ihren url()-Verweisen nicht an).
"""
import os

from django import template
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.templatetags.static import static

register = template.Library()


def _mtime(path):
    """mtime der Quelldatei (über die Finder, sonst STATIC_ROOT). 0 = unbekannt."""
    try:
        found = finders.find(path)
        if found and os.path.exists(found):
            return int(os.path.getmtime(found))
        if staticfiles_storage.exists(path):
            return int(staticfiles_storage.get_modified_time(path).timestamp())
    except Exception:
        pass
    return 0


@register.simple_tag
def static_v(path):
    url = static(path)
    v = _mtime(path)
    return f"{url}?v={v}" if v else url
