"""Ingests Romanian procurement legislation into a local knowledge base.

The drafting engines used to produce documents that *referred* to the law
in general terms. A clarification request or technical proposal that
cites nothing is easy to dismiss; one that quotes the operative sentence
and names the article is not. The obvious way to fix that — writing the
article numbers into the templates from memory — is exactly the wrong one
for a product that generates formal documents: a confidently wrong
citation in a notificare prealabilă is worse than no citation at all.

So nothing here is written from memory. This fetches the consolidated
texts from `legislatie.just.ro` — the Ministry of Justice's own
legislative portal, the authoritative published source — splits them per
article, and writes `data/legal_kb.json`. `legal_kb.py` then serves that
text to the generators, so every quotation in a drafted document is the
real one.

    python scripts/build_legal_kb.py

Re-run when a law is amended; the portal serves the consolidated (current)
version, so the output tracks whatever is in force at fetch time. The
generated file carries `generated_at` and the source URL per law so the
vintage of any quotation is always recoverable.
"""
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT_PATH = ROOT / "data" / "legal_kb.json"

# Fetched pages are kept so a re-run costs the portal nothing. This is not
# an optimisation: legislatie.just.ro rate-limited this machine outright
# after a burst of requests while the document ids were being identified,
# and a build script that re-downloads four multi-megabyte laws every time
# it runs would keep earning that. Delete the directory to force a refetch.
CACHE_DIR = ROOT / "data" / ".legal_source_cache"

# Deliberately unhurried — there is no reason for this to be fast.
DELAY_BETWEEN_FETCHES_SECONDS = 5.0

BASE_URL = "https://legislatie.just.ro/Public/DetaliiDocument/{doc_id}"

# Document ids confirmed one by one against the portal's own titles before
# being written down here — see the `verify` step at the bottom, which
# refuses to write a law whose fetched title does not match what we expect.
LAWS = [
    {
        "key": "L98/2016",
        "doc_id": 178667,
        "name": "Legea nr. 98/2016 privind achizițiile publice",
        "title_contains": "LEGE",
        "title_number": "98",
        "scope": "Achiziții publice clasice — procedura, criteriile de calificare, motivele de excludere, atribuirea.",
    },
    {
        "key": "L99/2016",
        "doc_id": 178661,
        "name": "Legea nr. 99/2016 privind achizițiile sectoriale",
        "title_contains": "LEGE",
        "title_number": "99",
        "scope": "Achiziții sectoriale (utilități: apă, energie, transport, servicii poștale).",
    },
    {
        "key": "L100/2016",
        "doc_id": 178689,
        "name": "Legea nr. 100/2016 privind concesiunile de lucrări și de servicii",
        "title_contains": "LEGE",
        "title_number": "100",
        "scope": "Concesiuni de lucrări și servicii.",
    },
    {
        "key": "L101/2016",
        "doc_id": 178680,
        "name": "Legea nr. 101/2016 privind remediile și căile de atac",
        "title_contains": "LEGE",
        "title_number": "101",
        "scope": "Notificarea prealabilă, contestația la CNSC, termenele de exercitare a căilor de atac.",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def _visible_lines(raw_html: str) -> list:
    """Portal pages are server-rendered tables; stripping tags to newlines
    keeps each article heading on its own line, which is what the split
    below keys on."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text)
    return [ln for ln in (re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")) if ln]


def extract_articles(raw_html: str) -> dict:
    """Splits a consolidated law into {article_number: text}.

    Each page carries the article headings twice — once in the table of
    contents at the top, once above the actual body — so the longest text
    found for a given number wins. Taking the first occurrence would
    silently harvest the table of contents and produce a knowledge base of
    empty articles that still looked populated.
    """
    lines = _visible_lines(raw_html)
    headings = [
        (i, int(m.group(1)))
        for i, line in enumerate(lines)
        if (m := re.fullmatch(r"Articolul\s+(\d+)", line))
    ]

    articles: dict = {}
    for position, (line_index, number) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = " ".join(lines[line_index + 1 : end]).strip()
        # Drop the trailing heading noise the portal appends between
        # articles (section/chapter titles), keeping the operative text.
        body = re.sub(r"\s*(Secţiunea|Secțiunea|Capitolul|Titlul)\s+[^ ]+\s*$", "", body).strip()

        # FIRST substantial body wins, not the longest.
        #
        # A consolidated page is the law followed by the texts of the acts
        # that amended it, and those have their own "Articolul 1/2/3…".
        # Taking the longest body therefore silently replaced Legea
        # 98/2016's Article 2 with an amending ordinance's Article 2 — the
        # quoted text even said "prezentei ordonanțe de urgență" — which is
        # precisely the kind of confidently-wrong citation this whole
        # knowledge base exists to prevent. The law's own article always
        # comes before any amending act's, so the first body past the
        # table-of-contents stubs is the right one.
        if len(body) > 80 and number not in articles:
            articles[number] = body
    return {n: t for n, t in articles.items() if len(t) > 40}


def fetch_law_html(client: httpx.Client, law: dict, url: str) -> str:
    """Cache-first. Returns the page text, fetching only on a cache miss."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{law['doc_id']}.html"
    if cached.exists():
        print("  (from cache)")
        return cached.read_text(encoding="utf-8", errors="ignore")

    time.sleep(DELAY_BETWEEN_FETCHES_SECONDS)
    resp = client.get(url)
    resp.raise_for_status()
    cached.write_text(resp.text, encoding="utf-8")
    return resp.text


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    kb = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Texte preluate din versiunile consolidate publicate pe legislatie.just.ro "
            "(Ministerul Justiției). Verificați forma în vigoare la data utilizării."
        ),
        "laws": {},
        "articles": {},
    }

    with httpx.Client(timeout=60.0, headers=HEADERS, follow_redirects=True) as client:
        for law in LAWS:
            url = BASE_URL.format(doc_id=law["doc_id"])
            print(f"fetching {law['name']} ({url}) …")
            try:
                page = fetch_law_html(client, law, url)
            except Exception as e:
                # The portal rate-limits, and a law we could not fetch this
                # run must not silently drop out of a knowledge base the
                # generators then cite from as if it were complete.
                print(f"  ! could not fetch: {type(e).__name__} — skipping (re-run to complete)")
                kb.setdefault("incomplete", []).append({"law": law["name"], "reason": type(e).__name__})
                continue

            title_match = re.search(r"<title>([^<]*)</title>", page)
            title = (title_match.group(1) if title_match else "").strip()
            # Refuses to ingest the wrong document: the portal's ids are not
            # stable across its own reorganisations, and silently ingesting
            # whatever sits at an id would poison every citation downstream.
            if law["title_contains"] not in title or law["title_number"] not in title:
                print(f"  ! title mismatch — got '{title}', expected {law['title_contains']} {law['title_number']}")
                return 1

            articles = extract_articles(page)
            if len(articles) < 20:
                print(f"  ! only {len(articles)} articles parsed — refusing to write a truncated law")
                return 1

            kb["laws"][law["key"]] = {
                "key": law["key"],
                "name": law["name"],
                "scope": law["scope"],
                "source_url": url,
                "portal_title": title,
                "article_count": len(articles),
            }
            for number, text in articles.items():
                kb["articles"][f"{law['key']}:{number}"] = {
                    "law_key": law["key"],
                    "law_name": law["name"],
                    "article": number,
                    "citation": f"art. {number} din {law['name']}",
                    "text": text,
                    "source_url": url,
                }
            print(f"  {len(articles)} articles")

    OUTPUT_PATH.write_text(json.dumps(kb, ensure_ascii=False, indent=1), encoding="utf-8")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nwrote {OUTPUT_PATH.relative_to(ROOT)} — {len(kb['articles'])} articles, {size_kb:,.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
