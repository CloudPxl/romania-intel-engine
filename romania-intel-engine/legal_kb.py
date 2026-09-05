"""Query layer over the ingested Romanian procurement legislation.

`data/legal_kb.json` is built by `scripts/build_legal_kb.py` from the
consolidated texts on legislatie.just.ro. Everything here reads that file;
nothing here contains a legal text written from memory, which is the whole
point — the drafting engines quote the operative sentence and name the
article, and both have to be the real ones.

Two things the grounding caught while this was being written, which are
exactly the class of error it exists to prevent:

* **Art. 6 of Legea 101/2016 is repealed** (by OUG 45/2018). It was the
  "notificare prealabilă" article, and it is still widely cited in
  procurement guidance and by LLMs. Anything drafted against it would cite
  a dead provision.
* **Art. 210 of Legea 98/2016 contains no 80% threshold.** The often-
  repeated "under 80% of the estimated value triggers Art. 210" is not in
  the article; the only 80% in the law is Art. 31, on in-house awards.
  What Art. 210 actually provides is the obligation to request
  clarifications and the six headings a justification must address —
  which is more useful, and is what TOPICS points at below.

The TOPICS index is curated (choosing which article answers which
product question is a judgement call), but every entry resolves to fetched
text: a mis-filed topic shows the reader what the article really says
rather than inventing what it ought to say.
"""
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("LegalKB")

KB_PATH = Path(__file__).resolve().parent / "data" / "legal_kb.json"

_lock = threading.Lock()
_kb: Optional[Dict[str, Any]] = None


def _load() -> Dict[str, Any]:
    """Loaded once per process, on first use.

    A missing knowledge base degrades to empty rather than raising: the
    drafting engines produce a complete document from their templates on
    their own, and citations are additive. Same convention as every other
    optional capability here — an unconfigured feature returns nothing and
    says so, it does not take a route down with it.
    """
    global _kb
    if _kb is not None:
        return _kb
    with _lock:
        if _kb is not None:
            return _kb
        try:
            _kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning(
                "[LegalKB] data/legal_kb.json not found — run scripts/build_legal_kb.py. "
                "Documents will be generated without statutory citations."
            )
            _kb = {"laws": {}, "articles": {}}
        except Exception as e:
            logger.error(f"[LegalKB] Could not read the knowledge base: {e}")
            _kb = {"laws": {}, "articles": {}}
    return _kb


def is_available() -> bool:
    return bool(_load().get("articles"))


def stats() -> Dict[str, Any]:
    kb = _load()
    return {
        "available": bool(kb.get("articles")),
        "generated_at": kb.get("generated_at"),
        "laws": [
            {"key": k, "name": v.get("name"), "articles": v.get("article_count")}
            for k, v in (kb.get("laws") or {}).items()
        ],
        "article_count": len(kb.get("articles") or {}),
    }


def get_article(key: str) -> Optional[Dict[str, Any]]:
    """`key` is "<law>:<article>", e.g. "L98/2016:210"."""
    return (_load().get("articles") or {}).get(key)


def is_repealed(key: str) -> bool:
    """True for an article whose consolidated text is just a repeal note.

    Worth its own check rather than leaving callers to eyeball the text:
    the portal keeps repealed articles in place with their history, so a
    naive lookup returns a perfectly real-looking entry for a provision
    that no longer exists (see Art. 6 of Legea 101/2016 in this module's
    docstring).
    """
    article = get_article(key)
    if not article:
        return False
    return article["text"].strip().lower().startswith("abrogat")


def quote(key: str, max_chars: int = 700) -> Optional[str]:
    """The operative text, trimmed for use inside a generated document.

    The portal interleaves amendment history — "(la 22-12-2017, Alineatul
    (1) ... a fost modificat de ...)" — into the body. That is provenance,
    not obligation, and quoting it into a formal letter reads as noise, so
    it is stripped here while the full text stays available via
    get_article() for anyone who needs the history.
    """
    article = get_article(key)
    if not article:
        return None
    import re

    # The history blocks nest parentheses — "(la 22-12-2017, Alineatul (1)
    # din Articolul 210 ... a fost modificat de ...)" — so a lazy `.*?\)`
    # stops at the inner "(1)" and leaves the rest of the amendment note
    # stranded in the middle of the quotation. This tolerates one level of
    # nesting, which is all these notes use.
    text = re.sub(r"\(la \d{2}-\d{2}-\d{4},(?:[^()]|\([^()]*\))*\)", " ", article["text"])
    # A few articles carry the same note without its opening bracket.
    text = re.sub(
        r"\s*din Articolul\s+\d+[^.]*?a fost (?:modificat|abrogat|completat|introdus)[^)]*\)", " ", text
    )
    text = re.sub(r"\s*\.\.\.\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars)
        text = text[: cut if cut > 0 else max_chars].rstrip(" ,;") + " […]"
    return text


def citation(key: str) -> Optional[str]:
    article = get_article(key)
    return article["citation"] if article else None


def cite_with_text(key: str, max_chars: int = 700) -> Optional[Dict[str, str]]:
    """Everything a generated paragraph needs to quote a provision."""
    article = get_article(key)
    if not article:
        return None
    return {
        "key": key,
        "citation": article["citation"],
        "law": article["law_name"],
        "article": str(article["article"]),
        "text": quote(key, max_chars) or "",
        "source_url": article["source_url"],
        "repealed": is_repealed(key),
    }


def search(term: str, law_keys: Optional[List[str]] = None, limit: int = 8) -> List[Dict[str, Any]]:
    """Plain substring search across the corpus.

    Deliberately not fuzzy: this backs "which article actually says this",
    where a near-miss is worse than no answer. Repealed articles are
    excluded — a search for a concept should not surface the dead
    provision that used to carry it.
    """
    needle = (term or "").strip().lower()
    if not needle:
        return []
    results: List[Dict[str, Any]] = []
    for key, article in (_load().get("articles") or {}).items():
        if law_keys and article["law_key"] not in law_keys:
            continue
        if needle in article["text"].lower():
            if is_repealed(key):
                continue
            results.append(
                {
                    "key": key,
                    "citation": article["citation"],
                    "law": article["law_name"],
                    "article": article["article"],
                    "excerpt": quote(key, 320) or "",
                    "source_url": article["source_url"],
                }
            )
            if len(results) >= limit:
                break
    return results


# ---------------------------------------------------------------- topics
#
# Product concept -> the articles that actually govern it. Verified against
# the fetched text one by one; the `note` is what the article is being
# relied on for, so a reviewer can check the mapping without re-reading the
# statute.
TOPICS: Dict[str, Dict[str, Any]] = {
    "technical_specifications": {
        "label": "Specificații tehnice și interdicția favorizării",
        "articles": ["L98/2016:155", "L98/2016:156"],
        "note": (
            "Modul în care se stabilesc specificațiile tehnice și interdicția de a indica "
            "o anumită producție, provenienţă sau procedeu fără mențiunea 'sau echivalent'."
        ),
    },
    "exclusion_grounds": {
        "label": "Motive de excludere",
        "articles": ["L98/2016:164", "L98/2016:165", "L98/2016:167"],
        "note": "Condamnări, obligații fiscale restante și celelalte situații de excludere.",
    },
    "qualification_criteria": {
        "label": "Criterii de calificare și selecție",
        "articles": ["L98/2016:172", "L98/2016:175", "L98/2016:178"],
        "note": (
            "Ce criterii de capacitate pot fi impuse și cerința ca acestea să fie "
            "proporționale cu obiectul contractului."
        ),
    },
    "award_criteria": {
        "label": "Criterii de atribuire",
        "articles": ["L98/2016:187"],
        "note": "Criteriul de atribuire și factorii de evaluare.",
    },
    "abnormally_low_price": {
        "label": "Preț aparent neobișnuit de scăzut",
        "articles": ["L98/2016:210"],
        "note": (
            "Obligația autorității de a cere clarificări și cele șase capitole pe care "
            "justificarea prețului trebuie să le acopere — alin. (2) lit. a)-f). "
            "Atenție: articolul NU conține un prag procentual de 80%."
        ),
    },
    "clarification_requests": {
        "label": "Solicitări de clarificări privind documentația de atribuire",
        "articles": ["L98/2016:160", "L98/2016:161"],
        "note": "Dreptul de a solicita clarificări și termenul în care autoritatea răspunde.",
    },
    "remedies": {
        "label": "Căi de atac și termene de contestare",
        "articles": ["L101/2016:4", "L101/2016:8"],
        "note": (
            "Unde se depune contestația (CNSC sau instanță) și termenele de 10 zile / 7 zile "
            "după cum valoarea estimată este peste sau sub pragurile de publicare în JOUE."
        ),
    },
    "contract_modification": {
        "label": "Modificarea contractului de achiziție publică",
        "articles": ["L98/2016:221"],
        "note": "Situațiile în care contractul poate fi modificat fără o nouă procedură.",
    },
}


def topic(name: str, max_chars: int = 700) -> Dict[str, Any]:
    """Resolves a topic to its articles, with text, skipping any repealed."""
    spec = TOPICS.get(name)
    if not spec:
        return {"label": name, "note": None, "articles": []}
    resolved = []
    for key in spec["articles"]:
        entry = cite_with_text(key, max_chars)
        if entry and not entry["repealed"]:
            resolved.append(entry)
    return {"label": spec["label"], "note": spec["note"], "articles": resolved}


def topic_citation_block(name: str, max_chars: int = 520) -> str:
    """A ready-to-paste block of citations for a generated document."""
    data = topic(name, max_chars)
    if not data["articles"]:
        return ""
    lines = []
    for entry in data["articles"]:
        lines.append(f"{entry['citation']}:\n„{entry['text']}”")
    return "\n\n".join(lines)
