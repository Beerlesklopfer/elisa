"""
Lokale Inferenz (beratend): Chat und Embeddings über Ollama ODER Eliezer.

Umschalter: settings.LOCAL_LLM_BACKEND = "ollama" | "eliezer".
Eliezer (GPU-Modellmanager) spricht den OpenAI-Dialekt (/v1/chat/completions,
/v1/embeddings). Es gelten unverändert die Regeln aus CLAUDE.md: die Ausgabe
ist beratend, nie verbindlich; Provenienz steht in settings.LOCAL_CHAT_MODEL.
"""
import httpx
from django.conf import settings


def _eliezer_headers() -> dict:
    key = settings.ELIEZER_API_KEY
    return {"Authorization": f"Bearer {key}"} if key else {}


def _eliezer_post(path: str, payload: dict) -> dict:
    url = settings.ELIEZER_BASE_URL.rstrip("/") + path
    resp = httpx.post(url, json=payload, headers=_eliezer_headers(),
                      timeout=settings.ELIEZER_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _ollama_client():
    import ollama
    return ollama.Client(host=settings.OLLAMA_HOST, timeout=settings.OLLAMA_TIMEOUT)


def backend_label() -> str:
    return "Eliezer" if settings.LOCAL_LLM_BACKEND == "eliezer" else "Ollama"


def chat(messages: list, *, json_mode: bool = False, model: str = "") -> str:
    """Antworttext des lokalen Modells. Wirft bei Fehlern (Aufrufer fängt)."""
    if settings.LOCAL_LLM_BACKEND == "eliezer":
        payload = {"model": model or settings.LOCAL_CHAT_MODEL, "messages": messages}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = _eliezer_post("/v1/chat/completions", payload)
        return data["choices"][0]["message"]["content"]
    kwargs = {"format": "json"} if json_mode else {}
    resp = _ollama_client().chat(model=model or settings.LOCAL_CHAT_MODEL,
                                 messages=messages, **kwargs)
    return resp["message"]["content"]


def embed_many(texts) -> list:
    """Embeddings für eine Textliste (Batch)."""
    texts = list(texts)
    if settings.LOCAL_LLM_BACKEND == "eliezer":
        data = _eliezer_post("/v1/embeddings",
                             {"model": settings.LOCAL_EMBED_MODEL, "input": texts})
        return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    return _ollama_client().embed(model=settings.LOCAL_EMBED_MODEL,
                                  input=texts)["embeddings"]


def embed_one(text: str):
    """Ein Embedding oder None bei Fehler."""
    try:
        return embed_many([text])[0]
    except Exception:
        return None
