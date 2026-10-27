"""
OCR für eingescannte PDF-Seiten über ein Vision-/OCR-Modell der lokalen Inferenz
(Eliezer, OpenAI-Dialekt mit Bild-Eingabe). Reine Mechanik der Indexierung: der erkannte
Text landet nur im RAG-Index (beratender Kontext), nie in verbindlichen Feldern.
"""
import base64
import io

from django.conf import settings

PROMPT = ("Gib den gesamten Text dieser Dokumentseite vollständig und originalgetreu als "
          "reinen Text aus (in Leserichtung, Tabellen zeilenweise). Keine Kommentare, "
          "keine Erklärungen, nichts hinzufügen.")


class OcrError(Exception):
    pass


def render_page_png(path, page_index, dpi=150):
    """Rendert eine PDF-Seite (0-basiert) als PNG-Bytes (pypdfium2, keine Systempakete)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        img = pdf[page_index].render(scale=max(50, min(dpi, 400)) / 72).to_pil()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()


def ocr_page(path, page_index, model, dpi=150):
    """Text einer Seite per OCR-Modell. Wirft OcrError bei Fehlern."""
    if settings.LOCAL_LLM_BACKEND != "eliezer":
        raise OcrError("OCR braucht LOCAL_LLM_BACKEND=eliezer (Bild-Eingabe).")
    from app import local_llm
    png = render_page_png(path, page_index, dpi)
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    try:
        out = local_llm.chat([{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": uri}}]}], model=model)
    except Exception as exc:
        raise OcrError(f"OCR-Modell '{model}' antwortet nicht: {exc}")
    return (out or "").strip()
