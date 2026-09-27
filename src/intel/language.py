"""Dependency-free local language detection (M015).

No external service/model is required. Detection uses unicode script ranges,
language-specific diacritics and high-frequency stopword profiles for the
priority languages (FR/DE/EN) plus several common ones. Short or ambiguous text
returns an explicit ``UNKNOWN``/``INSUFFICIENT_TEXT``/``CODE`` state instead of a
confident wrong answer.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

METHOD = "stopword-script-v1"
MIN_TOKENS = 8
MIN_STOPWORD_RATIO = 0.04

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Public, high-frequency function words (no private corpus text).
_STOPWORDS: dict[str, set[str]] = {
    "en": set("the of and to in is are was were be been being a an for on with as by at from that this these those it its his her their our your my not no but or if then than so do does did has have had will would can could should may might must about into over after before between under more most other some such only own same too very".split()),
    "fr": set("le la les de des du un une et est sont était être à au aux en dans pour par sur avec sans que qui quoi dont où il elle ils elles nous vous je tu ne pas plus moins mais ou donc car ce cet cette ces son sa ses leur leurs mon ma mes ton ta tes notre nos votre vos".split()),
    "de": set("der die das den dem des ein eine einen einem einer und ist sind war waren sein nicht mit für auf von zu aus bei nach über unter durch gegen ohne dass weil wenn als auch nur noch schon sehr wie wo was wer welche dieser diese dieses im in am an muss werden wird wurde hat haben hatte bei ieder".split()),
    "es": set("el la los las de del un una unos unas y es son era fueron ser estar en para por con sin que quien donde no mas pero o porque como se su sus mi mis tu tus nuestro vuestra este esta estos estas".split()),
    "it": set("il lo la i gli le di del un una e è sono era erano essere in per con senza che chi dove non ma o perché come si suo sua suoi mie tuo nostra questo questa questi queste".split()),
    "pt": set("o a os as de do da um uma uns umas e é são era eram ser estar em para por com sem que quem onde não mas ou porque como se seu sua seus minha nosso este esta estes estas".split()),
    "nl": set("de het een en van in is zijn was waren op voor met zonder dat die deze dit niet maar of omdat als waar wie hoe haar hun mijn jouw onze uw moet moeten jaar bij worden wordt ieder alle heeft hebben naar om dan meer ook".split()),
}

# Diacritics that strongly hint at a Latin language.
_DIACRITIC_HINTS = {
    "fr": set("éèêëàâçîïôùûœ"),
    "de": set("äöüß"),
    "es": set("ñ¿¡"),
    "pt": set("ãõáâàçéêíóôú"),
    "it": set("ìòàùèé"),
}

# Characteristic substrings (weak tie-breaker for short/ambiguous text).
_NGRAM_HINTS = {
    "nl": ["ij", "aa", "ee", "oo", "uu", "lijk", "heid", "sch"],
    "de": ["sch", "ich", "ung", "ei", "ie", "ß", "ein", "zu"],
    "fr": ["que", "ent", "ion", "eau", "aux", "oi", "ez", "ç"],
    "en": ["th", "ing", "tion", "the", "and", "ght"],
    "es": ["ción", "que", "os", "ar", "el", "ñ"],
    "it": ["zione", "che", "gli", "tt", "zz"],
    "pt": ["ção", "que", "nh", "ão", "lh"],
}

_SCRIPTS = {
    "ru": ("CYRILLIC",),
    "el": ("GREEK",),
    "he": ("HEBREW",),
    "ar": ("ARABIC",),
    "hi": ("DEVANAGARI",),
}

_CODE_HINTS = re.compile(r"(def |class |import |function |const |var |return |#include|public static|</?[a-z]+>|\{\s*\"|=>|;\s*$)", re.M)


def _script_of(ch: str) -> str:
    try:
        return unicodedata.name(ch).split(" ")[0]
    except ValueError:
        return ""


def detect_language(text: str, *, min_tokens: int = MIN_TOKENS,
                    min_stopword_ratio: float = MIN_STOPWORD_RATIO) -> dict[str, Any]:
    raw = (text or "").strip()
    words = _WORD_RE.findall(raw)
    tokens = [w.lower() for w in words]
    n = len(tokens)
    if n < min_tokens:
        return {"lang": "und", "confidence": 0.0, "status": "INSUFFICIENT_TEXT",
                "mixed": [], "method": METHOD, "token_count": n}

    letters = [c for c in raw if c.isalpha()]
    script_counts: dict[str, int] = {}
    for ch in letters:
        s = _script_of(ch)
        if s:
            script_counts[s] = script_counts.get(s, 0) + 1
    if letters:
        top_script, top_count = max(script_counts.items(), key=lambda kv: kv[1])
        if top_script != "LATIN" and top_count / len(letters) >= 0.30:
            for lang, scripts in _SCRIPTS.items():
                if top_script in scripts:
                    return {"lang": lang, "confidence": round(top_count / len(letters), 3),
                            "status": "OK", "mixed": [], "method": METHOD, "token_count": n}
            # CJK: distinguish Japanese kana from Chinese Han.
            if top_script in {"CJK", "HIRAGANA", "KATAKANA"}:
                kana = script_counts.get("HIRAGANA", 0) + script_counts.get("KATAKANA", 0)
                return {"lang": "ja" if kana else "zh",
                        "confidence": round(top_count / len(letters), 3), "status": "OK",
                        "mixed": [], "method": METHOD, "token_count": n}

    # Code-like content is not natural language.
    symbol_ratio = sum(1 for c in raw if c in "{}()[]<>=;:/*") / max(len(raw), 1)
    if symbol_ratio > 0.08 or len(_CODE_HINTS.findall(raw)) >= 3:
        return {"lang": "code", "confidence": 0.5, "status": "CODE", "mixed": [],
                "method": METHOD, "token_count": n}

    scores: dict[str, float] = {}
    for lang, stops in _STOPWORDS.items():
        hits = sum(1 for t in tokens if t in stops)
        ratio = hits / n
        hint = sum(1 for c in raw.lower() if c in _DIACRITIC_HINTS.get(lang, set()))
        ratio += min(0.05, hint / max(len(letters), 1))
        low = raw.lower()
        ngram_hits = sum(low.count(ng) for ng in _NGRAM_HINTS.get(lang, []))
        ratio += min(0.10, ngram_hits / max(len(tokens), 1))
        scores[lang] = ratio
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_lang, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if top < min_stopword_ratio:
        return {"lang": "und", "confidence": round(top, 3), "status": "UNKNOWN",
                "mixed": [lg for lg, s in ranked[:3] if s >= min_stopword_ratio], "method": METHOD,
                "token_count": n}
    confidence = max(0.0, min(1.0, 0.5 + (top - second) * 3.0))
    confidence = round(min(1.0, max(confidence, top)), 3)
    mixed = [lg for lg, s in ranked[:3] if s >= max(min_stopword_ratio, 0.6 * top) and lg != top_lang]
    return {"lang": top_lang, "confidence": confidence, "status": "OK",
            "mixed": mixed, "method": METHOD, "token_count": n}


LANGUAGE_NAMES = {
    "en": "English", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "ar": "Arabic", "zh": "Chinese",
    "ja": "Japanese", "el": "Greek", "he": "Hebrew", "hi": "Hindi", "code": "Source code",
    "und": "Unknown",
}
