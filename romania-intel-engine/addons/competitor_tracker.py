import logging
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger("CompetitorTracker")

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

# Pricing guidance that does not depend on data we lack. Legea 98/2016
# requires a contracting authority to seek justification for a tender that
# appears abnormally low; the exact article is deliberately not cited here
# because it must be confirmed against the version in force, and an
# incorrect citation in a pricing recommendation is worse than none.
UNUSUALLY_LOW_GUIDANCE = (
    "Ofertele semnificativ sub valoarea estimată pot atrage solicitarea de justificare a prețului "
    "(regimul ofertei cu preț neobișnuit de scăzut din Legea nr. 98/2016). Pregătiți fundamentarea "
    "costurilor înainte de a coborî substanțial sub estimarea autorității."
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
        values = sorted(o["financial_value_ron"] for o in comparable)

        same_county = [
            o for o in comparable
            if (o.get("county") or "").lower() == (county or "").lower()
        ]

        authorities = sorted({
            o.get("entity_name") for o in comparable if o.get("entity_name")
        })

        observed: Dict[str, Any] = {
            "comparable_procedures_ingested": len(comparable),
            "in_requested_county": len(same_county),
            # These are the authorities we have actually seen publishing in
            # this sector — not a competitor list. We hold no bidder data,
            # and the distinction is stated explicitly because the previous
            # version blurred exactly this line.
            "contracting_authorities_observed": authorities[:10],
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
        if budget_ron and budget_ron > 0:
            # Arithmetic reference points, labelled as such. These are not
            # predictions of a winning bid — we have no award data to
            # support one — they are simply percentages of the stated
            # estimate, so the user can reason about their own margin.
            pricing["reference_points_ron"] = {
                "at_estimate_100pct": round(budget_ron, 2),
                "minus_5pct": round(budget_ron * 0.95, 2),
                "minus_10pct": round(budget_ron * 0.90, 2),
                "minus_15pct": round(budget_ron * 0.85, 2),
            }
            pricing["reference_points_note"] = (
                "Procente aplicate valorii estimate publicate, nu prognoze de câștig. "
                "Sistemul nu colectează rezultate de atribuire, deci nu poate estima prețul câștigător."
            )
        else:
            pricing["reference_points_ron"] = None
            pricing["reference_points_note"] = "Valoarea estimată nu este publicată; nu se pot calcula repere de preț."

        return {
            "sector": (category or "").capitalize(),
            "county": county,
            "estimated_budget_ron": budget_ron or None,
            "observed_market": observed,
            "pricing": pricing,
            "data_limitations": (
                "Analiza se bazează exclusiv pe anunțurile colectate de acest sistem. "
                "Nu includem istoricul atribuirilor, ofertele concurenței sau deciziile CNSC, "
                "deci nu raportăm rate de contestare, discounturi istorice sau liste de competitori."
            ),
        }
