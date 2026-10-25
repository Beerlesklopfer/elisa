---
name: write-time-feedback
description: Arbeit am beratenden Live-Feedback während des Schreibens – der Feedback-Endpoint, der Toast-Vertrag (notice/checkbox/radio/form), der debounced Editor-Loop und die Aktions-Endpoints. Nutze diesen Skill IMMER, wenn es um Toasts, LLM-Hinweise beim Schreiben, den Linter für Spezifikationen, das JSON-Format der LLM-Ausgabe oder die Regel "das LLM verfasst nie Inhalt" geht – auch wenn nur "Feedback" oder "Hinweise" gesagt wird.
---

# Write-time feedback (beratender Linter)

Das LLM läuft beim Schreiben daneben und gibt Hinweise. Es verfasst nie Inhalt.

## Zwei – und nur zwei – Arten von LLM-Ausgabe

1. **Ephemere Hinweise (Toasts):** werden nie gespeichert. Linter-Charakter.
2. **Vorgeschlagene Referenzen:** als `NormLink(confirmed=False)` abgelegt, erst
   durch menschlichen Klick bestätigt.

Inhalt (`body`) entsteht ausschließlich durch menschliche Eingabe – auch wenn
er über ein Form-Toast eingegeben wird: Den Text tippt der Mensch, das LLM hat
nur den Anlass geliefert.

## Toast-Vertrag (LLM gibt NUR dieses JSON zurück)

```json
{ "toasts": [
  { "type": "notice|radio|checkbox|form", "severity": "info|warn|conflict",
    "message": "…", "options": ["…"], "fields": [{"name":"…","label":"…"}],
    "action": "norm-link|completeness|append-criterion" }
]}
```

`options`/`fields`/`action` nur bei interaktiven Typen. Der System-Prompt in
`app/views_feedback.py` erzwingt dieses Format; Ollama wird mit `format="json"`
aufgerufen.

## Ablauf (siehe `views_feedback.py`, `static/live_feedback.js`)

1. Editor-Eingabe wird debounced an `/api/writing-feedback/` geschickt
   (mit Nachbar-Items zur Widerspruchsprüfung, rein lesend).
2. Der Endpoint ruft Ollama auf und gibt `{toasts: [...]}` zurück. Er
   **speichert nichts**.
3. `renderToast` verzweigt über `type` und baut das Steuerelement.
4. Erst ein menschlicher Klick auf „Übernehmen" ruft `/api/toast-action/` –
   das ist der einzige Pfad, der etwas persistiert (Link bestätigen, vom
   Menschen getippten Form-Inhalt ins `body` schreiben).

## Regeln

- Der Feedback-Endpoint darf nie `body` oder einen `confirmed=True`-Link
  schreiben. Solche Schreibvorgänge gehören in die menschlich angestoßenen
  Aktions-Endpoints.
- Feedback nicht pro Tastendruck auslösen – pro abgeschlossenem Satz/Absatz.
  Sonst kommentiert das LLM Halbsätze (Rauschen) und belastet das lokale Modell.
- Für den Live-Linter ein kleines, schnelles Modell (3–8B) verwenden.
