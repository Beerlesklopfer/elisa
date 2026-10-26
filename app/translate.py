"""
Übersetzung über das im Admin festgelegte Übersetzungs-LLM (Tertius, Default
lokales Ollama + TowerInstruct). Übersetzungen sind INFORMATIV und NIE normativ
(CLAUDE.md): der Wortlaut der Projektsprache bleibt allein maßgeblich.
"""
import os

from django.conf import settings


def translation_backend():
    """Das aktive Übersetzungs-Backend (Tertius) – im Admin änderbar/nicht löschbar."""
    from app.models import WorkerBackend
    return WorkerBackend.objects.filter(handle="tertius", active=True).first()


def translate_text(text, target_language_name):
    """Übersetzt `text` informativ nach `target_language_name`.
    Rückgabe: (ok: bool, ergebnis_oder_fehlertext: str)."""
    from app.apps import TRANSLATOR_PERSONA
    text = (text or "").strip()
    if not text:
        return True, ""
    be = translation_backend()
    provider = be.provider if be else "OLLAMA"
    model = (be.model if be and be.model else "thinkverse/towerinstruct")
    base_url = (be.effective_base_url if be else settings.OLLAMA_HOST)
    api_key = be.effective_api_key if be else ""
    user = (f"Übersetze den folgenden Text vollständig und treu nach "
            f"{target_language_name}. Gib NUR die Übersetzung aus:\n\n{text}")
    try:
        if provider == "OLLAMA" and settings.LOCAL_LLM_BACKEND == "eliezer":
            # Lokale Inferenz läuft über Eliezer (OpenAI-Dialekt, app/local_llm.py).
            from app import local_llm
            model = (be.model if be and be.model else
                     settings.ELIEZER_TRANSLATE_MODEL or settings.LOCAL_CHAT_MODEL)
            return True, local_llm.chat([
                {"role": "system", "content": TRANSLATOR_PERSONA},
                {"role": "user", "content": user}], model=model).strip()
        if provider == "OLLAMA":
            import ollama
            host = base_url or settings.OLLAMA_HOST
            if host.rstrip("/").endswith("/v1"):      # nativer Client braucht den HOST,
                host = host.rstrip("/")[:-3]           # nicht den OpenAI-kompatiblen /v1
            cl = ollama.Client(host=host, timeout=settings.OLLAMA_TIMEOUT)
            r = cl.chat(model=model, messages=[
                {"role": "system", "content": TRANSLATOR_PERSONA},
                {"role": "user", "content": user}])
            return True, (r["message"]["content"] or "").strip()
        if provider == "CLAUDE":
            import anthropic
            c = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
            m = c.messages.create(model=model or "claude-haiku-4-5", max_tokens=4000,
                                  system=TRANSLATOR_PERSONA,
                                  messages=[{"role": "user", "content": user}])
            return True, "".join(getattr(b, "text", "") for b in m.content).strip()
        # OpenAI-kompatibel (ChatGPT / DeepSeek / LM Studio / custom)
        from openai import OpenAI
        cl = OpenAI(base_url=base_url or None, api_key=api_key or "not-needed")
        r = cl.chat.completions.create(model=model or "local-model", messages=[
            {"role": "system", "content": TRANSLATOR_PERSONA},
            {"role": "user", "content": user}])
        return True, (r.choices[0].message.content or "").strip()
    except Exception as exc:
        return False, f"Übersetzung fehlgeschlagen ({provider}/{model}): {exc}"
