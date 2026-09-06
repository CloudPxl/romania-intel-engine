"""One Romanian money parser, instead of seven.

Romanian institutional sources render values as `1.234.567,89 lei` — dot
for thousands, comma for the decimal, the reverse of the JSON/US
convention. Getting that backwards does not raise; it silently produces a
number that is wrong by three orders of magnitude, and that number flows
straight into `estimated_value_ron`, the 0-10 score's value bands, the
`min_value_ron` matching gate, and the alerts a user acts on.

This module exists because that is exactly what happened. The same parser
had been copy-pasted into five modules with a byte-identical regex, and a
sixth hand-rolled variant in `infra_scrapers.UrbanismAcScraper._parse_ron`
did `float(value.replace(",", ""))`, which:

    '9.844.025,00'  ->  0.0        (silently "value not published")
    '2.500.000'     ->  0.0
    '150.000'       ->  150.0      (worse — a 150k contract reads as 150 RON
                                    and sinks below every min_value filter,
                                    looking entirely legitimate)

Five identical copies is how the sixth got written instead of imported.

NOT everything is folded in here. `digital_scrapers._parse_value` stays
separate on purpose: its source feed emits plain decimals (`10302905.76`),
so stripping dots there would corrupt correct data in the other direction.
The convention is a property of the source, not of the country.
"""
import re
from typing import Optional

# "1.234.567,89 lei" / "150.000 lei". The {2,} guards against matching a
# bare digit or two out of surrounding prose.
VALUE_WITH_CURRENCY_RE = re.compile(r"([\d][\d.,]{2,})\s*lei", re.IGNORECASE)


def parse_ro_number(raw: Optional[str]) -> float:
    """Parses a bare Romanian-formatted number. No currency suffix needed.

    Returns 0.0 rather than raising: every caller is a scraper, and the
    honest report for an unparseable value is "not published" — which is
    what 0.0 means throughout this codebase.
    """
    if raw is None:
        return 0.0
    cleaned = str(raw).replace("lei", "").replace("LEI", "").replace("RON", "")
    cleaned = cleaned.replace("\xa0", " ").strip().replace(" ", "")
    if not cleaned:
        return 0.0
    # A comma present means it is the decimal separator, so every dot is a
    # thousands separator.
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") == 1:
        # One dot and no comma is the genuinely ambiguous case, and it is
        # resolvable: a Romanian thousands group is ALWAYS exactly three
        # digits. So "150.000" is one hundred fifty thousand, while
        # "1234567.89" (two trailing digits) can only be a plain decimal —
        # which is what a JSON feed emits. Treating every dot as thousands
        # inflated those by 100x.
        head, _, tail = cleaned.partition(".")
        cleaned = head + tail if (len(tail) == 3 and head.isdigit()) else cleaned
    else:
        # Several dots: unambiguously grouped thousands ("2.500.000").
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_ro_value(text: Optional[str]) -> float:
    """Finds the first `<number> lei` in a block of text and parses it."""
    if not text:
        return 0.0
    match = VALUE_WITH_CURRENCY_RE.search(text)
    if not match:
        return 0.0
    return parse_ro_number(match.group(1))
