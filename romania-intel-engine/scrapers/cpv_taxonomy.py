"""The EU Common Procurement Vocabulary's Division tier, and pure
code-arithmetic to decompose any 8-digit CPV code into its Division/Group/
Class/Category ancestors.

CPV_DIVISIONS below is not a hand-typed guess: it was parsed directly out of
the official TED eForms reference table
(docs.ted.europa.eu/eforms/1.12/reference/code-lists/cpv.html — the
Commission's live CPV 2008 code list, Regulation (EC) No 213/2008), by
extracting every row whose code ends in "000000" and reading its label
verbatim. All 45 entries were cross-checked one by one; there are no other
CPV divisions in the current vocabulary — the gaps you'd expect (36, 40, 49,
74, 93 and others) are genuinely absent from the standard, not omissions.
Labels are the Commission's own English wording; `label_ro` is this
project's own concise Romanian gloss for display, not a second official
source, since Romania's own CPV register was not independently verified this
pass.

Group/Class/Category codes below (see cpv_hierarchy) are derived by pure
string slicing on a real, already-scraped CPV code — no lookup table is
needed or provided for those tiers, since the codes themselves carry the
hierarchy and this module never asserts what a Group/Class *means*, only
what it *is*.
"""

import re
from typing import Dict, Optional, TypedDict

# code -> (English official label, Romanian display gloss)
CPV_DIVISIONS: Dict[str, "DivisionInfo"] = {}


class DivisionInfo(TypedDict):
    label_en: str
    label_ro: str


def _division(code: str, label_en: str, label_ro: str) -> None:
    CPV_DIVISIONS[code] = {"label_en": label_en, "label_ro": label_ro}


_division("03", "Agricultural, farming, fishing, forestry and related products", "Agricultură, pescuit și silvicultură")
_division("09", "Petroleum products, fuel, electricity and other sources of energy", "Combustibili, electricitate și energie")
_division("14", "Mining, basic metals and related products", "Minerit și metale de bază")
_division("15", "Food, beverages, tobacco and related products", "Alimente, băuturi și tutun")
_division("16", "Agricultural machinery", "Utilaje agricole")
_division("18", "Clothing, footwear, luggage articles and accessories", "Îmbrăcăminte și încălțăminte")
_division("19", "Leather and textile fabrics, plastic and rubber materials", "Piele, textile, plastic și cauciuc")
_division("22", "Printed matter and related products", "Materiale tipărite")
_division("24", "Chemical products", "Produse chimice")
_division("30", "Office and computing machinery, equipment and supplies except furniture and software packages", "Echipamente de birou și calcul")
_division("31", "Electrical machinery, apparatus, equipment and consumables; lighting", "Echipamente electrice și iluminat")
_division("32", "Radio, television, communication, telecommunication and related equipment", "Echipamente radio, TV și telecomunicații")
_division("33", "Medical equipments, pharmaceuticals and personal care products", "Echipamente medicale și farmaceutice")
_division("34", "Transport equipment and auxiliary products to transportation", "Echipamente de transport")
_division("35", "Security, fire-fighting, police and defence equipment", "Echipamente de securitate, pompieri, poliție și apărare")
_division("37", "Musical instruments, sport goods, games, toys, handicraft, art materials and accessories", "Instrumente muzicale, articole sportive și jocuri")
_division("38", "Laboratory, optical and precision equipments (excl. glasses)", "Echipamente de laborator și precizie")
_division("39", "Furniture (incl. office furniture), furnishings, domestic appliances (excl. lighting) and cleaning products", "Mobilier și electrocasnice")
_division("41", "Collected and purified water", "Apă captată și purificată")
_division("42", "Industrial machinery", "Utilaje industriale")
_division("43", "Machinery for mining, quarrying, construction equipment", "Utilaje pentru minerit și construcții")
_division("44", "Construction structures and materials; auxiliary products to construction (except electric apparatus)", "Structuri și materiale de construcții")
_division("45", "Construction work", "Lucrări de construcții")
_division("48", "Software package and information systems", "Pachete software și sisteme informatice")
_division("50", "Repair and maintenance services", "Servicii de reparații și întreținere")
_division("51", "Installation services (except software)", "Servicii de instalare")
_division("55", "Hotel, restaurant and retail trade services", "Servicii hoteliere și de restaurant")
_division("60", "Transport services (excl. Waste transport)", "Servicii de transport")
_division("63", "Supporting and auxiliary transport services; travel agencies services", "Servicii auxiliare de transport")
_division("64", "Postal and telecommunications services", "Servicii poștale și de telecomunicații")
_division("65", "Public utilities", "Utilități publice")
_division("66", "Financial and insurance services", "Servicii financiare și de asigurări")
_division("70", "Real estate services", "Servicii imobiliare")
_division("71", "Architectural, construction, engineering and inspection services", "Servicii de arhitectură, construcții și inginerie")
_division("72", "IT services: consulting, software development, Internet and support", "Servicii IT")
_division("73", "Research and development services and related consultancy services", "Cercetare și dezvoltare")
_division("75", "Administration, defence and social security services", "Administrație publică și apărare")
_division("76", "Services related to the oil and gas industry", "Servicii pentru industria petrolului și gazelor")
_division("77", "Agricultural, forestry, horticultural, aquacultural and apicultural services", "Servicii agricole și forestiere")
_division("79", "Business services: law, marketing, consulting, recruitment, printing and security", "Servicii pentru întreprinderi")
_division("80", "Education and training services", "Servicii de învățământ")
_division("85", "Health and social work services", "Servicii de sănătate și asistență socială")
_division("90", "Sewage, refuse, cleaning and environmental services", "Salubritate și mediu")
_division("92", "Recreational, cultural and sporting services", "Servicii recreative, culturale și sportive")
_division("98", "Other community, social and personal services", "Alte servicii comunitare și sociale")

# Divisions mapped to this app's five existing domains (aparare, sanatate,
# energie, digitalizare, infrastructura — the closed set both the backend's
# CATEGORY_KEYWORDS and the frontend's onboarding picker understand). This
# is deliberately a small, conservative subset of the 45 divisions above:
# only divisions whose *entire* label maps unambiguously onto one existing
# domain are included. Divisions left out on purpose, and why:
#   - "75" (Administration, defence and social security services) bundles
#     ordinary public administration together with defence in one division
#     — mapping it to "aparare" would misfile routine county-council admin
#     contracts as defence procurement.
#   - "34" (Transport equipment) is too generic (city buses, forklifts,
#     office cars) to safely imply "infrastructura" (this app's meaning is
#     roads/bridges/buildings, not vehicle purchasing).
#   - "32" (Radio/TV/telecom equipment) mixes broadcasting hardware with
#     genuine IT/telecom, which is a weaker signal than "48"/"72" for
#     "digitalizare".
# Anything not listed here falls through to the existing keyword classifier
# unchanged — this table only ever adds a *more confident* signal, never
# removes the fallback.
DIVISION_TO_DOMAIN: Dict[str, str] = {
    "33": "sanatate",
    "85": "sanatate",
    "09": "energie",
    "65": "energie",
    "48": "digitalizare",
    "72": "digitalizare",
    "35": "aparare",
    "45": "infrastructura",
    "71": "infrastructura",
    "44": "infrastructura",
    "43": "infrastructura",
}

_CPV_CODE_RE = re.compile(r"^\d{8}")


class CpvHierarchy(TypedDict):
    division: str
    group: str
    class_: str
    category: str


def _normalize(cpv_code: Optional[str]) -> Optional[str]:
    """Real CPV codes in the wild carry a check-digit suffix
    ("45233120-6") or stray whitespace. Returns the bare 8-digit code, or
    None if `cpv_code` doesn't start with one — never raises, since this
    runs on scraper output that this codebase never trusts by default."""
    if not cpv_code:
        return None
    match = _CPV_CODE_RE.match(cpv_code.strip())
    return match.group(0) if match else None


def cpv_hierarchy(cpv_code: Optional[str]) -> Optional[CpvHierarchy]:
    """Decomposes a real 8-digit CPV code into its Division/Group/Class/
    Category ancestor codes by string slicing — CPV's tree structure is
    encoded in the code itself (XX-division, XXX-group, XXXX-class,
    XXXXX-category, then 3 more digits of sub-category detail), so this
    needs no lookup table and cannot drift from CPV_DIVISIONS above.
    Returns None for anything that isn't a recognizable 8-digit code.
    """
    code = _normalize(cpv_code)
    if code is None:
        return None
    return {
        "division": code[:2] + "000000",
        "group": code[:3] + "00000",
        "class_": code[:4] + "0000",
        "category": code[:5] + "000",
    }


def division_code(cpv_code: Optional[str]) -> Optional[str]:
    """The bare 2-digit division key used to index CPV_DIVISIONS /
    DIVISION_TO_DOMAIN (e.g. "45"), not the 8-digit "45000000" form
    cpv_hierarchy() returns — the two are used in different places
    (this for a dict lookup, that for display/storage) and are kept as
    separate helpers so callers don't have to slice either string by hand.
    """
    code = _normalize(cpv_code)
    return code[:2] if code else None


def domain_from_cpv(cpv_code: Optional[str]) -> Optional[str]:
    """The one function scrapers/category_classifier.py actually calls:
    resolves straight to one of the app's five domains, or None if this
    CPV code's division isn't in the conservative DIVISION_TO_DOMAIN map
    above — callers are expected to fall back to keyword classification in
    that case, exactly as if no CPV code had been available at all."""
    division = division_code(cpv_code)
    return DIVISION_TO_DOMAIN.get(division) if division else None


def division_label(cpv_code: Optional[str]) -> Optional[DivisionInfo]:
    """The human-readable division this code belongs to, for surfacing on
    a lead's dossier (e.g. "72 — Servicii IT") independent of whether it
    maps to one of the app's five domains."""
    division = division_code(cpv_code)
    return CPV_DIVISIONS.get(division) if division else None
