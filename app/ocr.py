"""
OCR für eingescannte PDF-Seiten über ein Vision-/OCR-Modell der lokalen Inferenz
(Eliezer, OpenAI-Dialekt mit Bild-Eingabe). Reine Mechanik der Indexierung: der erkannte
Text landet nur im RAG-Index (beratender Kontext), nie in verbindlichen Feldern.
"""
import base64
import io
import time

from django.conf import settings

PROMPT = ("Gib den gesamten Text dieser Dokumentseite vollständig und originalgetreu als "
          "reinen Text aus (in Leserichtung, Tabellen zeilenweise). Keine Kommentare, "
          "keine Erklärungen, nichts hinzufügen.")


class OcrError(Exception):
    pass


MAX_EDGE = 1600      # längste Bildkante in Pixeln (olmOCR ist auf ~1288 px trainiert)


def render_page_png(path, page_index, dpi=150):
    """Rendert eine PDF-Seite (0-basiert) als Bild (pypdfium2, keine Systempakete).
    Die längste Kante wird auf MAX_EDGE begrenzt und als JPEG kodiert: große Scans
    (mehrere MB) überschreiten sonst das Request-Limit der Inferenz (Verbindungsabbruch)
    und bringen für die Erkennung nichts. Rückgabe: JPEG-Bytes."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[page_index]
        w, h = page.get_size()
        scale = min(max(50, min(dpi, 400)) / 72, MAX_EDGE / max(w, h))
        img = page.render(scale=scale).to_pil().convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    finally:
        pdf.close()


def ocr_page(path, page_index, model, dpi=150):
    """Text einer Seite per OCR-Modell. Wirft OcrError bei Fehlern."""
    if settings.LOCAL_LLM_BACKEND != "eliezer":
        raise OcrError("OCR braucht LOCAL_LLM_BACKEND=eliezer (Bild-Eingabe).")
    from app import local_llm
    png = render_page_png(path, page_index, dpi)
    uri = "data:image/jpeg;base64," + base64.b64encode(png).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": uri}}]}]
    last = None
    for attempt in range(4):
        try:
            return (local_llm.chat(msgs, model=model) or "").strip()
        except Exception as exc:
            # Beim ersten Aufruf lädt Eliezer das Modell (ggf. nach Verdrängen eines
            # anderen) und bricht die Verbindung kurz ab → mit Pause erneut versuchen.
            last = exc
            time.sleep(10 * (attempt + 1))
    raise OcrError(f"OCR-Modell '{model}' antwortet nicht: {last}")
