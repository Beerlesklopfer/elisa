#!/usr/bin/env python3
"""
Norm-RAG mit Ollama oder Eliezer. Liefert den Norm-Bezug fuer die Spezifikation.

Voraussetzungen:
    pip install ollama chromadb pypdf httpx
    ollama pull nomic-embed-text
    ollama pull llama3.1

Eliezer statt Ollama (OpenAI-kompatibel):
    LOCAL_LLM_BACKEND=eliezer ELIEZER_BASE_URL=http://127.0.0.1:1234 \\
    ELIEZER_API_KEY=... ELIEZER_EMBED_MODEL=<key> ELIEZER_CHAT_MODEL=<key> \\
    python rag/rag_normen.py

Ablauf:
    1. Norm-PDFs aus ./documents einlesen
    2. Text in ueberlappende Chunks zerlegen
    3. Chunks einbetten und in ChromaDB speichern
    4. Frage -> relevante Chunks holen -> als Kontext an das LLM

Hinweis: Das LLM wird NICHT trainiert. Die Norm bleibt externes Wissen,
das zur Laufzeit hinzugezogen wird.
"""

import os
import glob
import hashlib

import chromadb
from pypdf import PdfReader

BACKEND = os.getenv("LOCAL_LLM_BACKEND", "ollama").strip().lower()
ELIEZER_URL = os.getenv("ELIEZER_BASE_URL", "http://127.0.0.1:1234").rstrip("/")
ELIEZER_KEY = os.getenv("ELIEZER_API_KEY", "")
if BACKEND == "eliezer":
    EMBED_MODEL = os.getenv("ELIEZER_EMBED_MODEL", "")
    CHAT_MODEL = os.getenv("ELIEZER_CHAT_MODEL", "")
else:
    EMBED_MODEL = "nomic-embed-text"
    CHAT_MODEL = "llama3.1"
DOCS_DIR = "./documents"
DB_DIR = "./chroma_db"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
TOP_K = 4


def _eliezer_post(path, payload):
    import httpx
    headers = {"Authorization": f"Bearer {ELIEZER_KEY}"} if ELIEZER_KEY else {}
    r = httpx.post(ELIEZER_URL + path, json=payload, headers=headers, timeout=300)
    r.raise_for_status()
    return r.json()


def embed(text):
    if BACKEND == "eliezer":
        data = _eliezer_post("/v1/embeddings", {"model": EMBED_MODEL, "input": [text]})
        return data["data"][0]["embedding"]
    import ollama
    return ollama.embeddings(model=EMBED_MODEL, prompt=text)["embedding"]


def chat(prompt):
    messages = [{"role": "user", "content": prompt}]
    if BACKEND == "eliezer":
        data = _eliezer_post("/v1/chat/completions", {"model": CHAT_MODEL, "messages": messages})
        return data["choices"][0]["message"]["content"]
    import ollama
    return ollama.chat(model=CHAT_MODEL, messages=messages)["message"]["content"]


def load_pdfs(directory):
    docs = []
    for path in glob.glob(os.path.join(directory, "*.pdf")):
        reader = PdfReader(path)
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                docs.append((os.path.basename(path), i + 1, text))
    return docs


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def build_index(collection):
    docs = load_pdfs(DOCS_DIR)
    if not docs:
        print(f"Keine PDFs in {DOCS_DIR} gefunden.")
        return
    for filename, page_no, text in docs:
        for j, chunk in enumerate(chunk_text(text)):
            embedding = embed(chunk)
            chunk_id = hashlib.md5(f"{filename}-{page_no}-{j}".encode()).hexdigest()
            collection.add(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{"quelle": filename, "seite": page_no}],
            )
    print(f"Index erstellt: {collection.count()} Chunks gespeichert.")


def retrieve(collection, question, n=TOP_K):
    q_emb = embed(question)
    res = collection.query(query_embeddings=[q_emb], n_results=n)
    return list(zip(res["documents"][0], res["metadatas"][0]))


def answer(collection, question):
    hits = retrieve(collection, question)
    context = "\n\n".join(
        f"[Quelle: {m['quelle']}, Seite {m['seite']}]\n{doc}" for doc, m in hits
    )
    prompt = f"""Beantworte die Frage ausschliesslich auf Basis des Kontexts.
Steht die Antwort nicht im Kontext, sage das ehrlich.

Kontext:
{context}

Frage: {question}
Antwort:"""
    return chat(prompt), hits


def main():
    client = chromadb.PersistentClient(path=DB_DIR)
    collection = client.get_or_create_collection("normen")
    if collection.count() == 0:
        print("Baue Index auf ...")
        build_index(collection)
    print("\nRAG bereit. Frage eingeben (leer = beenden).\n")
    while True:
        q = input("Frage: ").strip()
        if not q:
            break
        text, hits = answer(collection, q)
        print("\n" + text + "\nVerwendete Quellen:")
        for _, m in hits:
            print(f"  - {m['quelle']}, Seite {m['seite']}")
        print()


if __name__ == "__main__":
    main()
