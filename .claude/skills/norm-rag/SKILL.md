---
name: norm-rag
description: Aufbau und Abfrage des Norm-RAG mit Ollama – PDFs einlesen, chunken, Embeddings erzeugen, in ChromaDB speichern, relevante Klauseln abrufen. Nutze diesen Skill IMMER, wenn es um den Norm-Bezug geht: Retrieval, Embeddings, Vektorsuche, ChromaDB, das Einlesen von Norm-PDFs oder das Auffinden passender Klauseln für ein WorkItem – auch wenn nur "Normen durchsuchen" oder "Klausel finden" gesagt wird. Nicht für Fine-Tuning/Training verwenden – das LLM wird nie trainiert.
---

# Norm-RAG

Liefert den Norm-Bezug, ohne das Modell zu trainieren. Klauseln werden zur
Laufzeit abgerufen und als Kontext bereitgestellt; jeder Treffer trägt Quelle
und Seite für die Nachvollziehbarkeit.

Implementierung: `rag/rag_normen.py`.

## Pipeline

1. PDFs aus `./documents` einlesen (Text + Seitenzahl).
2. In überlappende Chunks zerlegen (`CHUNK_SIZE` 800, `CHUNK_OVERLAP` 150).
3. Pro Chunk ein Embedding über `nomic-embed-text`, Ablage in ChromaDB mit
   Metadaten `{quelle, seite}`.
4. Abfrage: Frage einbetten, ähnlichste Chunks holen, als Kontext ins
   Chat-Modell. Antwort nur auf Basis des Kontexts; sonst ehrliches „weiß nicht".

## Verwendung

```bash
ollama pull nomic-embed-text
ollama pull llama3.1
python rag/rag_normen.py        # baut Index beim ersten Lauf, dann interaktiv
```

## Hinweise

- Bei stark gegliederten Normen liefert Chunking entlang der Abschnittsnummern
  (z. B. „6.4.1") präzisere Treffer als das einfache Chunking nach Zeichen.
- `TOP_K` erhöhen, wenn Antworten oft mehrere Abschnitte kombinieren müssen.
- Anbindung an das Datenmodell: Ein Treffer wird zu einem `NormLink`-Vorschlag
  (`confirmed=False`); bestätigt wird er erst durch einen Menschen.
- Norm-PDFs sind in der Regel lizenzpflichtig – nur lizenzierte Dokumente in
  `./documents` ablegen.
