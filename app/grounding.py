"""
Quellenpflicht im Chat: Personas und der RAG-Assistent dürfen NUR aussagen, was durch
Treffer im RAG belegt ist – jede Antwort trägt nummerierte Quellen mit klickbaren Links.

Ablauf (rein mechanisch, kein Vertrauen ins Modell):
  1. Treffer holen (search_norms), nach Relevanz (Abstand) filtern, nummerieren.
  2. Keine relevante Quelle → feste Absage, das Modell wird gar nicht gefragt.
  3. Das Modell bekommt NUR diese Quellen und muss mit [n] belegen.
  4. Die Antwort wird geprüft: ≥ 1 gültige Quellennummer, keine ungültigen Nummern,
     keine Normverweise (IEC/ISO/EN/DIN …), die in den Quellen nicht vorkommen.
  5. Besteht sie die Prüfung nicht → deterministische Ersatzantwort aus den Quellen
     (wörtliche Auszüge). So kann nichts Erfundenes im Chat landen.
Reines Python (keine Django-Importe), damit der MCP-Worker es ohne Django nutzen kann.
"""
import os
import re
from urllib.parse import quote

MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.62"))   # Cosinus-Abstand, kleiner = ähnlicher
MAX_SOURCES = 5

RULES = (
    "QUELLENPFLICHT (hat Vorrang vor allem anderen): Beantworte NUR mit Aussagen, die in den "
    "unten stehenden QUELLEN stehen, und belege JEDE Aussage direkt dahinter mit der "
    "Quellennummer, z. B. [1] oder [2][3]. Nenne keine Normen, Klauseln, Zahlen oder Fakten, die "
    "nicht in den QUELLEN stehen – auch nicht aus eigenem Wissen. Reicht keine Quelle für die "
    "Frage, antworte genau: KEINE_QUELLE. Fasse dich kurz (höchstens 8 Sätze oder Stichpunkte)."
)

NO_SOURCE = ("Dazu finde ich im RAG keine passende Quelle – deshalb beantworte ich es nicht und "
             "erfinde nichts. Formuliere die Frage gern anders oder lade das passende Dokument "
             "auf der Normen-Seite hoch.")

_SMALLTALK = re.compile(
    r"^\s*(hi|hallo|hey|moin|servus|guten (morgen|tag|abend)|danke|dankesch[öo]n|ok|okay|"
    r"wer bist du|wer seid ihr|was (machst|kannst|bist) du|stell(t)? (dich|euch) vor|"
    r"was ist deine aufgabe)\b.{0,40}$", re.I)

_STD = re.compile(r"\b(?:ISO/IEC|DIN\s+EN\s+ISO|EN\s+ISO|DIN\s+EN|IEC|ISO|EN|DIN|VDE)\s*"
                  r"\d[\d.\-:/]*\d", re.I)


def is_smalltalk(text):
    """Begrüßung/Selbstvorstellung: wird ohne Modell und ohne Quellen beantwortet."""
    return bool(_SMALLTALK.match((text or "").strip()))


def numbered(hits, max_distance=None):
    """Treffer [{source,page,text,distance?}] → nummerierte, relevante, deduplizierte Quellen."""
    lim = MAX_DISTANCE if max_distance is None else max_distance
    out, seen = [], set()
    for h in hits or []:
        d = h.get("distance")
        if d is not None and d > lim:
            continue
        key = (h.get("source"), h.get("page"))
        if key in seen or not h.get("source"):
            continue
        seen.add(key)
        out.append({"n": len(out) + 1, "source": h["source"], "page": h.get("page"),
                    "text": (h.get("text") or "").strip(), "kind": h.get("kind", "norm")})
        if len(out) >= MAX_SOURCES:
            break
    return out


def sources_block(sources):
    return "QUELLEN (nur diese darfst du verwenden):\n" + "\n\n".join(
        f"[{s['n']}] {s['source']}, S. {s['page']}:\n{s['text'][:700]}" for s in sources)


def link(s):
    """Klickbarer Link auf die Stelle in der Quelle (Normen-Viewer, Seite per #page)."""
    if s.get("kind", "norm") != "norm":
        return None
    return f"/normen/download/?name={quote(s['source'])}&inline=1#page={s.get('page') or 1}"


def footer(used, sources):
    lines = []
    for s in sources:
        if s["n"] in used:
            url = link(s)
            label = f"{s['source']}, S. {s['page']}"
            lines.append(f"[{s['n']}] " + (f"[{label}]({url})" if url else label))
    return ("\n\n**Quellen:**\n" + "\n".join(lines)) if lines else ""


def _norm(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def unsupported_refs(answer, sources):
    """Normverweise im Antworttext, deren Nummer in keiner Quelle vorkommt."""
    hay = _norm(" ".join(f"{s['source']} {s['text']}" for s in sources))
    bad = []
    for m in _STD.finditer(answer or ""):
        core = _norm(re.sub(r"^[A-Za-z/\s]+", "", m.group(0)))
        if len(core) >= 3 and core not in hay:
            bad.append(m.group(0).strip())
    return bad


def check(answer, sources):
    """(ok, Probleme) – Pflicht: gültige Quellennummern und nur belegte Normverweise."""
    valid = {s["n"] for s in sources}
    cited = {int(n) for n in re.findall(r"\[(\d{1,2})\]", answer or "")}
    problems = []
    if not (cited & valid):
        problems.append("keine Quellenangabe")
    if cited - valid:
        problems.append("ungültige Quellennummer " + ", ".join(f"[{n}]" for n in sorted(cited - valid)))
    bad = unsupported_refs(answer, sources)
    if bad:
        problems.append("nicht belegte Normverweise: " + ", ".join(bad))
    return (not problems), problems


def extract_answer(sources):
    """Deterministische Ersatzantwort: wörtliche Auszüge aus den Quellen (nichts Erfundenes)."""
    parts = ["Ich konnte keine geprüfte Antwort formulieren. Diese Stellen im RAG passen zur Frage "
             "(wörtliche Auszüge):"]
    for s in sources[:3]:
        snippet = re.sub(r"\s+", " ", s["text"])[:320].rstrip()
        parts.append(f"- „{snippet} …“ [{s['n']}]")
    return "\n".join(parts)


def finalize(answer, sources):
    """Antwort + Quellenfuß, oder die Ersatzantwort. Rückgabe: (text, genutzte Quellennummern, ok)."""
    answer = (answer or "").strip()
    if "KEINE_QUELLE" in answer:
        return NO_SOURCE, set(), False
    ok, _problems = check(answer, sources)
    if ok:
        used = {int(n) for n in re.findall(r"\[(\d{1,2})\]", answer)} & {s["n"] for s in sources}
        return answer + footer(used, sources), used, True
    used = {s["n"] for s in sources[:3]}
    return extract_answer(sources) + footer(used, sources), used, False


def cited_payload(used, sources):
    """Für ChatMessage.cited_sources (klickbare Quellenzeile unter der Nachricht)."""
    return [{"quelle": s["source"], "seite": s["page"]} for s in sources if s["n"] in used]
