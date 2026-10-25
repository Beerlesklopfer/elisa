"""
Extraktion normativer Verweise aus den indexierten Normtexten.

Deterministisch (Regex über die ChromaDB-Chunks) – kein LLM. Jede Norm
referenziert im Abschnitt „Normative Verweisungen" weitere Normen; daraus
ergibt sich der echte Beschaffungsbedarf: referenzierte Normen, die wir noch
nicht besitzen.

Matching über den „Kern" einer Norm (Nummer + Teil, z. B. 61508-4), unabhängig
vom Gremium-Präfix (IEC/CEI/EN/DIN/ISO) und vom Jahr. So gilt „CEI 61508-2"
(italienisch) als dieselbe Norm wie „IEC 61508-2", und „DIN EN ISO 13849-2:2013"
zählt als vorhanden, wenn wir 13849-2 besitzen.
"""
from __future__ import annotations

import re
from collections import Counter

from app import rag_service

_BODY = r"(?:DIN\s+)?(?:EN\s+)?(?:ISO/IEC|IEC|ISO|EN|VDE|CEI|CENELEC)"
# Bezeichner inkl. optionalem Gremium-Präfix, Nummer, Teilen und Jahr.
_STD_RE = re.compile(
    rf"\b({_BODY}\s?\d{{3,5}}(?:[-‑–]\d+){{0,3}}(?::\d{{4}})?)\b", re.IGNORECASE)
# Kern = führende Nummer + Teile (ohne Gremium, ohne Jahr).
_CORE_RE = re.compile(r"(\d{3,5})((?:[-‑–]\d+){0,3})")


def _core(token: str):
    """('61508-4') aus 'CEI 61508-4:2010' – oder None bei Jahres-/Müll-Treffern."""
    m = _CORE_RE.search(token)
    if not m:
        return None
    base, parts = m.group(1), m.group(2).replace("‑", "-").replace("–", "-")
    # Jahreszahlen ohne Teil aussortieren (z. B. 'IEC 2017').
    if not parts and 1900 <= int(base) <= 2099:
        return None
    # Als „Teil" fehlinterpretierte Jahre am Ende entfernen (z. B. 61131-2-2017).
    segs = parts.split("-")[1:] if parts else []
    segs = [s for s in segs if not (len(s) == 4 and 1900 <= int(s) <= 2099)]
    return base + ("".join("-" + s for s in segs))


def _series(core: str) -> str:
    return core.split("-", 1)[0]


def _display(token: str) -> str:
    t = re.sub(r"\s+", " ", token.strip().upper()).replace("‑", "-").replace("–", "-")
    return re.sub(r":\d{4}$", "", t)   # Jahr für die Anzeige weglassen


def _lang(filename: str) -> str:
    """Sprache aus Dateiname/Gremium ableiten (Heuristik)."""
    f = filename.lower()
    for suf, lang in [("_en", "en"), ("-en", "en"), ("_de", "de"), ("-de", "de"),
                      ("_fr", "fr"), ("_it", "it")]:
        if suf in f:
            return lang
    if "din" in f:
        return "de"
    if "cei" in f:
        return "it"
    return "?"


def _label_for(filename: str, core: str) -> str:
    """
    Anzeigeform 'IEC 61508-2' aus Gremium (im Dateinamen) + kanonischem Kern.
    Robust gegen Unterstriche/Jahre im Dateinamen (kein \\b-Regex auf den Namen).
    """
    up = filename.upper().replace("-", " ")
    for body in ["ISO/IEC", "IEC", "ISO", "EN", "DIN", "VDE", "CEI"]:
        if body in up:
            return f"{body} {core}"
    return core


def available_norms_grouped():
    """
    Gruppiert die vorhandenen Normen nach kanonischem Kern und führt
    Sprachen/Ausgaben (Dateien) zusammen. Liefert sortierte Liste:
      {core, label, langs:[...], files:[...]}
    """
    groups: dict[str, dict] = {}
    for name in rag_service.available_norms():
        core = _core(name) or name
        g = groups.setdefault(core, {"core": core, "label": _label_for(name, core),
                                     "langs": set(), "files": []})
        g["langs"].add(_lang(name))
        g["files"].append(name)
    out = []
    for g in groups.values():
        g["langs"] = sorted(x for x in g["langs"] if x != "?") or ["?"]
        out.append(g)
    out.sort(key=lambda x: x["label"])
    return out


def norm_file_map():
    """({kanonischer Kern: Datei}, {Serie: Datei}) der vorhandenen Normen."""
    core_to_file, series_to_file = {}, {}
    try:
        for g in available_norms_grouped():
            files = g.get("files") or []
            if files:
                core_to_file[g["core"]] = files[0]
                series_to_file.setdefault(_series(g["core"]), files[0])
    except Exception:
        pass
    return core_to_file, series_to_file


def file_for(token, maps=None):
    """Verfügbare Norm-Datei für einen Referenz-Token (oder '' wenn nicht im System)."""
    core = _core(token)
    if not core:
        return ""
    c2f, s2f = maps if maps is not None else norm_file_map()
    f = c2f.get(core)
    if not f and "-" not in core:
        f = s2f.get(core)
    return f or ""


def cited_norms(text):
    """
    Im Text zitierte Normen/Regelwerke (Regex) + – falls im System vorhanden –
    die Datei für den eingebetteten Viewer (Direktlink). Dedupliziert nach
    kanonischem Kern, in Auftretensreihenfolge.
    Liefert [{label, name, in_system}].
    """
    text = text or ""
    core_to_file, series_to_file = {}, {}
    try:
        for g in available_norms_grouped():
            files = g.get("files") or []
            if files:
                core_to_file[g["core"]] = files[0]
                series_to_file.setdefault(_series(g["core"]), files[0])
    except Exception:
        pass
    seen, out = set(), []
    for m in _STD_RE.finditer(text):
        core = _core(m.group(1))
        if not core or core in seen:
            continue
        seen.add(core)
        file = core_to_file.get(core)
        if not file and "-" not in core:          # bare Serie (z. B. 61508) → Ausgabe der Serie
            file = series_to_file.get(core)
        out.append({"label": _display(m.group(1)), "name": file or "",
                    "in_system": bool(file)})
    return out


def possessed_cores():
    """Kerne der vorhandenen Normen (aus den Index-Dateinamen)."""
    cores, series = set(), set()
    for name in rag_service.available_norms():
        c = _core(name)
        if c:
            cores.add(c)
            series.add(_series(c))
    return cores, series


_CACHE = {"key": None, "value": None}

# „Informative" (nicht-normative) Dokumenttypen: Technical Report / Technical
# Specification / Guide. Diese sind nicht verbindlich und können bei der
# Beschaffung ausgeblendet werden.
_INFORMATIVE_RE = re.compile(
    r"\b(TR|TS|Guide|Technical Report|Technical Specification)\b", re.IGNORECASE)


def procurement_gap(min_count: int = 3, ignore_informative: bool = False):
    """
    Beschaffungsbedarf: in den Normtexten referenzierte Normen, die wir nicht
    besitzen. `min_count` filtert Zufallstreffer. `ignore_informative` blendet
    nicht-normative Dokumente (TR/TS/Guide) aus. Liefert {standard, core, count}.

    Gecacht über (Chunk-Anzahl, min_count, ignore_informative).
    """
    try:
        cache_key = (rag_service.total_chunks(), min_count, ignore_informative)
        if _CACHE["key"] == cache_key:
            return _CACHE["value"]
        docs = rag_service.all_norm_documents()
    except Exception:
        docs, cache_key = [], None

    have_cores, have_series = possessed_cores()

    # Pro Kern: Häufigkeit + repräsentative Anzeigeform.
    counts: Counter = Counter()
    labels: dict[str, str] = {}
    for doc in docs:
        for token in _STD_RE.findall(doc or ""):
            core = _core(token)
            if not core:
                continue
            counts[core] += 1
            # Anzeigeform bevorzugt mit IEC/ISO-Präfix (nicht CEI).
            disp = _display(token)
            cur = labels.get(core)
            if cur is None or (cur.startswith("CEI") and not disp.startswith("CEI")):
                labels[core] = disp

    gap = []
    for core, cnt in counts.items():
        if cnt < min_count:
            continue
        if core in have_cores:
            continue                      # exakt vorhanden
        if "-" not in core and core in have_series:
            continue                      # Basis-Nr., Teile davon vorhanden
        label = labels.get(core, core)
        if ignore_informative and _INFORMATIVE_RE.search(label):
            continue                      # nicht-normativ (TR/TS/Guide) ausblenden
        gap.append({"standard": label, "core": core, "count": cnt})
    gap.sort(key=lambda x: (-x["count"], x["standard"]))
    if cache_key is not None:
        _CACHE.update(key=cache_key, value=gap)
    return gap
