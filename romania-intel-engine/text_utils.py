"""Romanian-aware text normalisation shared by the matching, scoring,
eligibility and copilot engines.

Why this exists: the keyword lists in this codebase are written without
diacritics ("sanatate", "reabilitare"), but real published Romanian
procurement text is full of them ("sănătate", "reabilitări"). A plain
`"sanatate" in title.lower()` silently returns False on the genuine
article, so keyword matching quietly failed on exactly the documents it
was meant to catch.

Romanian also has two encodings in live use for the same two letters:
the correct comma-below forms (ș U+0219, ț U+021B) and the legacy
cedilla forms (ş U+015F, ţ U+0163). Institutional sites emit both, often
within one page, so both are folded here.
"""

import re
import unicodedata
from typing import Iterable, List, Set

# Explicit map first: NFKD alone does not decompose the legacy cedilla
# forms consistently across platforms, and Romanian â/î both fold to
# different base letters that we want to keep distinct from each other.
_DIACRITIC_MAP = str.maketrans({
    "ă": "a", "Ă": "a", "â": "a", "Â": "a",
    "î": "i", "Î": "i",
    "ș": "s", "Ș": "s", "ş": "s", "Ş": "s",
    "ț": "t", "Ț": "t", "ţ": "t", "Ţ": "t",
})

_WORD_RE = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    """Lowercase + strip Romanian diacritics, so 'Sănătate' and 'sanatate'
    compare equal."""
    if not text:
        return ""
    folded = text.translate(_DIACRITIC_MAP)
    # Catch any remaining accented characters from other languages that
    # show up in EU-funded project titles.
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return folded.lower()


def tokenize(text: str) -> List[str]:
    return _WORD_RE.findall(fold(text))


def token_set(text: str) -> Set[str]:
    return set(tokenize(text))


def contains_term(text: str, term: str) -> bool:
    """Whole-word, diacritic-insensitive containment.

    Whole-word matters as much as the folding: a substring test lets the
    keyword "sala" match "salariu" and "apa" match "apartament", which is
    how an unrelated opportunity ends up scored as a domain hit.
    Multi-word terms are matched as a phrase.
    """
    folded_term = fold(term).strip()
    if not folded_term:
        return False
    parts = _WORD_RE.findall(folded_term)
    if not parts:
        return False
    pattern = r"\b" + r"\s+".join(re.escape(p) for p in parts) + r"\b"
    return re.search(pattern, fold(text)) is not None


def matching_terms(text: str, terms: Iterable[str]) -> List[str]:
    """Every term from `terms` present in `text`, in the order given."""
    folded_text = fold(text)
    hits: List[str] = []
    for term in terms:
        parts = _WORD_RE.findall(fold(term))
        if not parts:
            continue
        pattern = r"\b" + r"\s+".join(re.escape(p) for p in parts) + r"\b"
        if re.search(pattern, folded_text):
            hits.append(term)
    return hits


RO_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}


def parse_ro_long_date(value: str) -> str:
    """'27 August 2024' or 'Marți, 04 August 2026' -> '2024-08-27'.

    Returns '' when the source's date element is missing or in a shape we
    don't recognise, so the caller stores nothing rather than a guessed
    date. Used by every scraper whose publisher renders dates as Romanian
    prose instead of an ISO attribute.
    """
    import re as _re
    from datetime import datetime as _dt

    match = _re.search(r"(\d{1,2})\s+([A-Za-zăâîșşțţĂÂÎȘŞȚŢ]+)\s+(\d{4})", value or "")
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = RO_MONTHS.get(fold(month_name).strip())
    if not month:
        return ""
    try:
        return _dt(int(year), month, int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def normalize_county(county: str) -> str:
    """County names arrive as 'Iași', 'Iasi', 'IAsi', and 'Bistrita Nasaud'
    vs 'Bistrița-Năsăud' depending on the publisher."""
    return re.sub(r"[\s\-]+", " ", fold(county)).strip()


def counties_match(a: str, b: str) -> bool:
    return bool(a) and bool(b) and normalize_county(a) == normalize_county(b)
