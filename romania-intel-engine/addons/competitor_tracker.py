import logging
import statistics
from typing import Any, Dict, List, Optional

from text_utils import normalize_county

logger = logging.getLogger("CompetitorTracker")

# Below this many local procedures a county median is noise, not a
# measurement — one contract would move it by half its own value. At or
# above it the analysis is scoped to the county; below, it falls back to
# the national set and says so.
MIN_COUNTY_SAMPLE = 3

# What this module used to contain, and why it was removed:
#
# A MARKET_BENCHMARKS table asserted, per sector, an "avg_discount_pct"
# (e.g. 8.4%), a "cnsc_dispute_rate" (e.g. 28%) and a list of
# "frequent_players" naming real companies — Strabag, Siemens Healthcare,
# Medist, Romarm, Teamnet International and others — presented to the user
# as "identified_key_competitors" for whatever procedure they were looking
# at. None of it came from any dataset. We have never ingested award
# results, bid histories or CNSC rulings, so none of those figures could
# have been derived, and the named companies had no connection to the
# opportunity being analysed. At least one of them (Teamnet) has not been
# an active bidder for years.
#
# Invented statistics are bad in any product; invented statistics that name
# real competitors and feed a pricing decision are a different category of
# risk. They were removed rather than adjusted.
#
# What replaces them is narrower and true: benchmarks computed from the
# opportunities this system has actually ingested. Where we have no data,
# the response says so instead of filling the gap.

# Pricing guidance. The article numbers below are no longer withheld: both
# texts are now ingested from the consolidated versions on
# legislatie.just.ro (scripts/build_legal_kb.py) and can be quoted rather
# than recalled. What that ingestion settled, and what this text is careful
# to say correctly: neither art. 210 of Legea 98/2016 nor art. 136 of the
# HG 395/2016 norms contains a percentage threshold. The "under 80% of the
# estimate is automatically abnormally low" rule is a survival from the
# repealed OUG 34/2006 and is stated nowhere in force.
UNUSUALLY_LOW_GUIDANCE = (
    "Dacă prețul dvs. pare neobișnuit de scăzut raportat la prețurile pieței, comisia de evaluare "
    "este obligată să vă ceară explicații (art. 210 din Legea nr. 98/2016, art. 136 din normele "
    "aprobate prin HG nr. 395/2016) și poate respinge oferta doar dacă dovezile nu justifică "
    "nivelul prețului. Legea nu prevede un prag procentual — testul este calitativ — dar pregătiți "
    "fundamentarea costurilor înainte de a coborî substanțial sub estimarea autorității."
)

SECTOR_QUALITATIVE_NOTES = {
    "infrastructura": "Punctajul tehnic depinde de obicei de capacitatea de mobilizare, personalul atestat (RTE, CQ) și termenele de execuție.",
    "sanatate": "Garanția extinsă, timpul de intervenție în service și compatibilitatea cu sistemele existente ale unității sanitare cântăresc frecvent alături de preț.",
    "energie": "Randamentul echipamentelor, condițiile de racordare și garanția de performanță sunt diferențiatorii tehnici uzuali.",
    "aparare": "Calificarea depinde de autorizațiile de securitate industrială și de conformitatea cu standardele aplicabile, înaintea criteriului de preț.",
    "digitalizare": "Arhitectura deschisă, interoperabilitatea și nivelurile de serviciu (SLA) sunt criteriile tehnice uzuale.",
}


class CompetitorTrackerEngine:
    @staticmethod
    def analyze_landscape(
        category: str,
        county: str,
        budget_ron: float,
        observed_opportunities: Optional[List[Dict[str, Any]]] = None,
        award_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Builds a sector view from opportunities this system has ingested.

        `observed_opportunities` is the real feed (see routers/analysis.py
        and cache_engine.newsletter_store). When it is not supplied, the
        response reports that no comparable data is available rather than
        substituting invented figures.
        """
        cat_key = (category or "").strip().lower()
        pool = observed_opportunities or []

        comparable = [
            o for o in pool
            if (o.get("category") or "").lower() == cat_key
            and (o.get("financial_value_ron") or 0) > 0
        ]

        # County matching goes through the same normaliser the ranked feed
        # uses, not `.lower()`. `"Iași".lower()` is `"iași"`, which never
        # equals the `"iasi"` a user types — so the county the caller asked
        # for silently matched only those sources that happen to publish
        # without diacritics, and missed the rest.
        county_key = normalize_county(county or "")
        same_county = [o for o in comparable if normalize_county(o.get("county") or "") == county_key]

        # The analysis is now actually *of* the requested county.
        #
        # Previously the county was counted and then thrown away: the value
        # distribution and the authority list were both computed over the
        # nationwide `comparable` set. Asking about Iași returned a median
        # from 54 national procedures and named Compania de Apă Oradea and
        # Primăria Municipiului București as the authorities observed —
        # correct numbers answering a question nobody asked, which is
        # indistinguishable from invented data at the point of use.
        #
        # Below the floor there is not enough local data to say anything,
        # so it falls back to the national set and the response states that
        # in `scope`, rather than quietly presenting one as the other.
        scoped_to_county = bool(county_key) and len(same_county) >= MIN_COUNTY_SAMPLE
        analysed = same_county if scoped_to_county else comparable
        # Echo the county the way the sources spell it ("Iași"), not the way
        # it was typed ("iasi") — the whole point of normalising is that the
        # user should not have to.
        county_display = (same_county[0].get("county") if same_county else None) or county
        values = sorted(o["financial_value_ron"] for o in analysed)

        authorities = sorted({o.get("entity_name") for o in analysed if o.get("entity_name")})

        observed: Dict[str, Any] = {
            "comparable_procedures_ingested": len(comparable),
            "in_requested_county": len(same_county),
            "analysed_procedures": len(analysed),
            # Names, in the payload itself, which set every figure below was
            # computed over — so a national fallback can never be read as a
            # local finding.
            "scope": "county" if scoped_to_county else "national",
            "scope_note": (
                f"Cifrele de mai jos sunt calculate din cele {len(same_county)} proceduri "
                f"din {county_display}."
                if scoped_to_county
                else (
                    f"Doar {len(same_county)} proceduri din {county_display} au valoare publicată — "
                    f"prea puține pentru o analiză locală, așa că cifrele de mai jos acoperă "
                    f"întreaga țară ({len(comparable)} proceduri)."
                    if county_key
                    else f"Analiză națională: {len(comparable)} proceduri în acest domeniu."
                )
            ),
            # These are the authorities we have actually seen publishing in
            # this sector — not a competitor list. We hold no bidder data,
            # and the distinction is stated explicitly because the previous
            # version blurred exactly this line.
            "contracting_authorities_observed": authorities[:10],
            # The procedures behind the numbers, so the UI can link straight
            # to each dossier instead of leaving the reader to search a
            # figure back out of the register by hand.
            "procedures": [
                {
                    "source_id": o.get("source_id"),
                    "project_title": o.get("project_title"),
                    "entity_name": o.get("entity_name"),
                    "county": o.get("county"),
                    "financial_value_ron": o.get("financial_value_ron"),
                    "published_date": o.get("published_date"),
                }
                for o in sorted(
                    analysed, key=lambda x: x.get("financial_value_ron") or 0, reverse=True
                )[:12]
            ],
        }
        if values:
            observed["value_distribution_ron"] = {
                "min": values[0],
                "median": statistics.median(values),
                "max": values[-1],
                "count": len(values),
            }
        else:
            observed["value_distribution_ron"] = None
            observed["note"] = (
                "Nu există proceduri comparabile cu valoare publicată în datele colectate "
                "pentru acest sector; nu se poate calcula o distribuție de valori."
            )

        pricing: Dict[str, Any] = {
            "guidance": UNUSUALLY_LOW_GUIDANCE,
            "sector_technical_note": SECTOR_QUALITATIVE_NOTES.get(
                cat_key, "Criteriile tehnice se citesc din fișa de date a achiziției."
            ),
        }
        awards = award_stats or {"available": False, "sample_size": 0}
        has_awards = bool(awards.get("available"))

        if budget_ron and budget_ron > 0:
            # Arithmetic reference points, labelled as such. These are
            # percentages of the stated estimate, so the user can reason
            # about their own margin.
            pricing["reference_points_ron"] = {
                "at_estimate_100pct": round(budget_ron, 2),
                "minus_5pct": round(budget_ron * 0.95, 2),
                "minus_10pct": round(budget_ron * 0.90, 2),
                "minus_15pct": round(budget_ron * 0.85, 2),
            }
            pricing["reference_points_note"] = (
                "Procente aplicate valorii estimate publicate — repere de calcul, nu prognoze de câștig."
            )
            # Where real award data exists, the observed winning discount is
            # a far better reference point than an arbitrary 5/10/15% ladder,
            # so it is added as its own labelled figure rather than replacing
            # the ladder (the two answer different questions: "what did
            # winners actually bid" vs "what would my margin be at X%").
            if has_awards:
                median = awards["winning_discount_pct"]["median"]
                pricing["observed_winning_price_ron"] = {
                    "at_median_observed_discount": round(budget_ron * (1 - median / 100), 2),
                    "median_discount_pct": median,
                    "sample_size": awards["sample_size"],
                }
                pricing["observed_winning_price_note"] = (
                    f"Calculat din {awards['sample_size']} atribuiri reale ingerate pentru acest filtru "
                    f"(discount median {median:.1f}%). Este o observație istorică, nu o garanție."
                )
        else:
            pricing["reference_points_ron"] = None
            pricing["reference_points_note"] = "Valoarea estimată nu este publicată; nu se pot calcula repere de preț."

        return {
            "sector": (category or "").capitalize(),
            "county": county_display,
            "estimated_budget_ron": budget_ron or None,
            "observed_market": observed,
            "pricing": pricing,
            # Real outcomes, where we have them. Always present as a block
            # so the frontend renders the same shape either way, with
            # `available` and `sample_size` carrying whether anything in it
            # can be relied on.
            "award_intelligence": awards,
            "data_limitations": (
                (
                    "Rezultatele de atribuire acoperă doar achizițiile directe (anunțuri SEAP de tip CAN) — "
                    "singurele pentru care acest sistem ingerează câștigători și prețuri. "
                    "Nu includem deciziile CNSC, deci nu raportăm rate de contestare."
                )
                if has_awards
                else (
                    "Analiza se bazează pe anunțurile colectate de acest sistem. Pentru filtrul curent "
                    "nu avem suficiente anunțuri de atribuire, deci nu raportăm discounturi câștigătoare "
                    "sau competitori. Nu includem deciziile CNSC."
                )
            ),
        }
