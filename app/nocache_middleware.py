"""HTML nie ungeprüft aus dem Browser-Cache nehmen.

Problem: Nach einem Deploy lieferte der Server die neue Seite + neue Assets
(`chat.js?v=…`), der Browser zeigte aber die ALTE HTML-Seite aus dem Cache –
und damit die alte Asset-URL ohne Versionsstring. Folge: veraltetes JS/CSS,
obwohl alles deployt war.

Fix: Auf HTML-Antworten `Cache-Control: no-cache` setzen. Der Browser darf die
Seite cachen, MUSS sie aber vor Wiederverwendung beim Server revalidieren – so
greift das `?v=`-Cache-Busting der Assets sofort. Die Assets (JS/CSS/Bilder)
selbst bleiben unangetastet und weiter lange cachebar.
"""


class NoCacheHTMLMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        ctype = (response.get("Content-Type") or "")
        # Nur HTML; Streaming/SSE (text/event-stream) und Assets bleiben unberührt.
        if ctype.startswith("text/html") and not getattr(response, "streaming", False):
            response["Cache-Control"] = "no-cache, must-revalidate"
        return response
