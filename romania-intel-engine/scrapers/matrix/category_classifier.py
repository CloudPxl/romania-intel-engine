"""Shared heuristic classifier mapping a procurement notice into one of
the app's five domains.

Several live sources are general-purpose feeds — e-licitatie's market
consultations, a municipality's whole procurement list — and carry no
structured domain field, so the domain has to be inferred from the text.
Keeping one classifier means a hospital tender is filed under "sanatate"
whether it arrives from SICAP or from a city hall mirror, instead of each
scraper inventing its own rules.

Matching goes through text_utils, so keywords are written once without
diacritics and still match the accented forms that real Romanian notices
use. The previous copy of this logic used raw substring matching and had
to list both spellings by hand ("apărăr" and "aparare"), which silently
missed every form nobody remembered to add.
"""

from typing import Dict, List

from text_utils import matching_terms

# Order matters: the first domain with a hit wins, so the more specific
# domains are tested before the broad "infrastructura" construction terms
# that would otherwise absorb hospital and power-plant building works.
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "aparare": [
        "aparare", "mapn", "armata", "militar", "nato", "cibernetic",
        "politia de frontiera", "jandarmerie", "munitie", "armament",
        "supraveghere frontiera", "clasificate",
    ],
    "sanatate": [
        "sanatate", "sanitar", "spital", "spitalicesc", "medical", "medicala",
        "chirurgical", "farmaceutic", "medicament", "ambulatoriu", "dispensar",
        "oncologic", "imagistica", "radiologie", "policlinica", "maternitate",
    ],
    "energie": [
        "energie", "energetic", "energetica", "electric", "electrica", "termic",
        "termica", "termoficare", "gaz natural", "fotovoltaic", "fotovoltaice",
        "regenerabil", "regenerabila", "cogenerare", "eficienta energetica",
        "panouri solare", "eolian", "biomasa",
    ],
    "digitalizare": [
        "software", "informatic", "informatica", "digitalizare", "digital",
        "cloud", "server", "licente", "aplicatie informatica", "sistem informatic",
        "interoperabilitate", "cybersecurity", "securitate cibernetica", "gis",
        "ticketing", "date deschise",
    ],
    "infrastructura": [
        "drum", "drumuri", "pod", "poduri", "pasaj", "asfalt", "canalizare",
        "alimentare cu apa", "constructie", "construire", "cladire", "urban",
        "reabilitare", "modernizare", "extindere", "consolidare", "viaduct",
        "tunel", "sala de sport", "iluminat public",
    ],
}

# Falls through to infrastructure rather than digital: on a general
# municipal feed, an unclassifiable notice is far more often public works
# than an IT contract, and the previous default sent all of them to
# "digitalizare", inflating that domain with unrelated procurements.
DEFAULT_CATEGORY = "infrastructura"


def classify_category(entity_name: str, title: str, description: str = "") -> str:
    text = f"{entity_name} {title} {description}"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if matching_terms(text, keywords):
            return category
    return DEFAULT_CATEGORY


def classify_with_evidence(entity_name: str, title: str, description: str = "") -> tuple:
    """Same decision, but also returns the terms that drove it, so a
    misclassification can be diagnosed from the stored signal rather than
    by re-running the classifier by hand."""
    text = f"{entity_name} {title} {description}"
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = matching_terms(text, keywords)
        if hits:
            return category, hits[:4]
    return DEFAULT_CATEGORY, []
