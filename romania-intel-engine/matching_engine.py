import logging
from typing import Any, Dict, List, Optional

from text_utils import counties_match, matching_terms

logger = logging.getLogger("MatchingEngine")

# Default per-tenant alerting bar on the 0-10 tenant-match scale below.
# Calibrated to the current weights: clearing it needs domain alignment
# plus real keyword evidence plus either the right county or a qualifying
# budget — i.e. a lead worth interrupting someone for, not merely a
# plausible one. Tenants may override `min_alert_score` individually.
#
# This was 9.0 when match scores started from a 7.0 baseline. Both scales
# were rebuilt from evidence, so the old literal no longer means what it
# used to and is defined here once rather than repeated per tenant.
ALERT_THRESHOLD = 7.5

# Tenant/product configuration.
#
# `keywords`      — terms that make an opportunity relevant to this division.
# `exclude_keywords` — terms that disqualify it outright even if other
#                   signals look good (a "reabilitare" that turns out to be
#                   a cleaning-services contract is not a roadworks lead).
# `min_value_ron` — a floor applied only when the value is actually known;
#                   see UNKNOWN_VALUE handling in the engine.
TENANT_ORGANIZATIONS = {
    "t1_infra_transilvania": {
        "name": "SC Infra Construct Transilvania SRL",
        "primary_domain": "infrastructura",
        "alert_emails": ["director@infraconstruct.ro"],
        "telegram_chat_id": None,
        "min_alert_score": ALERT_THRESHOLD,
        "products": [
            {
                "product_id": "prod_heavy_infra",
                "name": "Divizia Infrastructură Grea & Drumuri Județene",
                "domain": "infrastructura",
                "target_counties": ["Cluj", "Iasi", "Bihor", "Timis", "Bucuresti", "Constanta"],
                "min_value_ron": 10000000.0,
                "keywords": [
                    "drum", "drumuri", "pod", "poduri", "pasaj", "asfalt", "asfaltare",
                    "reabilitare", "modernizare", "infrastructura", "metrou", "sala de sport",
                    "sala polivalenta", "viaduct", "tunel", "consolidare", "terasamente",
                    "constructie", "construire", "extindere",
                ],
                "exclude_keywords": [
                    "curatenie", "igienizare", "papetarie", "rechizite", "catering",
                    "asigurare", "medicina muncii", "formare profesionala",
                ],
            },
            {
                "product_id": "prod_smart_traffic",
                "name": "Divizia Smart City & Sisteme ITS SCATS",
                "domain": "infrastructura",
                "target_counties": ["Iasi", "Cluj", "Bucuresti", "Timis", "Constanta"],
                "min_value_ron": 3000000.0,
                "keywords": [
                    "its", "trafic", "semaforizare", "semafor", "anpr", "senzori",
                    "scats", "monitorizare video", "supraveghere video", "smart city",
                    "management al traficului", "parcari",
                ],
                "exclude_keywords": ["curatenie", "papetarie", "catering"],
            },
        ],
    },
    "t2_medtech_bucuresti": {
        "name": "SC MedTech Pharma SRL",
        "primary_domain": "sanatate",
        "alert_emails": ["office@ro-intel.xyz"],
        "telegram_chat_id": None,
        "min_alert_score": ALERT_THRESHOLD,
        "products": [
            {
                "product_id": "prod_radiology_advanced",
                "name": "Divizia Imagistică Avansată & Radioterapie",
                "domain": "sanatate",
                "target_counties": ["Bucuresti", "Iasi", "Cluj", "Timis", "Dolj"],
                "min_value_ron": 5000000.0,
                "keywords": [
                    "rmn", "ct", "radioterapie", "accelerator", "imagistica", "imagistic",
                    "spital", "spitalicesc", "oncologie", "oncologic", "radiologie",
                    "tomograf", "angiograf", "mamograf", "ecograf", "dispensar",
                    "unitate sanitara", "ambulatoriu", "bloc operator",
                ],
                "exclude_keywords": [
                    "papetarie", "curatenie", "paza", "formare profesionala", "catering",
                ],
            }
        ],
    },
    "t3_vest_consulting_grants": {
        "name": "SC Vest Project Consulting",
        "primary_domain": "energie",
        "alert_emails": ["office@ro-intel.xyz"],
        "telegram_chat_id": None,
        "min_alert_score": ALERT_THRESHOLD,
        "products": [
            {
                "product_id": "prod_green_energy",
                "name": "Divizia Consultanță Parcuri Solare & BESS",
                "domain": "energie",
                "target_counties": ["Timis", "Cluj", "Iasi", "Constanta", "Bihor"],
                "min_value_ron": 5000000.0,
                "keywords": [
                    "fotovoltaic", "fotovoltaice", "solar", "solara", "energie",
                    "energetica", "baterii", "stocare", "cogenerare", "eficienta energetica",
                    "regenerabil", "regenerabila", "panouri", "bess", "termoficare",
                    "pompe de caldura", "eolian",
                ],
                "exclude_keywords": ["papetarie", "curatenie", "catering"],
            }
        ],
    },
}

# Opportunities whose budget the publisher never states arrive as 0.0.
# 0.0 means "not disclosed", not "worth nothing" — most CNI register rows,
# every ms.ro notice and every MFE funding call land this way — so the
# value floor must not be applied to them as if they had failed it.
UNKNOWN_VALUE = 0.0

# A product must clear this to count as a match. Scores are built from
# weighted evidence below rather than nudged off a high baseline, so this
# sits mid-scale instead of just above the old 7.0 floor.
MATCH_THRESHOLD = 6.0


class TenantMatchingEngine:
    @staticmethod
    def _score_product(opportunity: Dict[str, Any], prod: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Scores one product line against one opportunity.

        Returns None when the opportunity is not relevant to *this specific
        product*. Relevance is gated on keyword evidence, not domain: a
        tenant can have several products in the same domain (t1's
        heavy-infrastructure roads division and its separate ITS/smart-
        traffic division are both "infrastructura"), and domain membership
        alone doesn't say which one an opportunity actually belongs to.

        This used to also accept domain-alone as sufficient, which meant a
        plain road-resurfacing contract — zero overlap with the ITS
        product's keywords (its/trafic/semaforizare/scats/...) — still
        cleared the match threshold on domain (+3.4) plus county (+1.6)
        plus budget (+1.5) alone, attributing a roads lead to the smart-
        traffic product line. The earlier, related fix removed geography
        as a sufficient signal on its own (an energy tenant was matching
        defence contracts by county); this closes the same hole one layer
        down, at the product rather than the domain.
        """
        title = opportunity.get("project_title", "") or ""
        summary = opportunity.get("executive_summary", "") or opportunity.get("raw_description", "") or ""
        sub_category = opportunity.get("sub_category", "") or ""
        text = f"{title} {summary} {sub_category}"

        # Hard exclusions first — a disqualifying term ends it regardless of
        # how well everything else lines up.
        blocked = matching_terms(text, prod.get("exclude_keywords", []))
        if blocked:
            return None

        domain_hit = opportunity.get("category") == prod["domain"]
        matched_kws = matching_terms(text, prod.get("keywords", []))

        # Relevance gate: keyword evidence is mandatory. Domain match alone
        # no longer clears it — it remains a scoring bonus below, so it can
        # reinforce a keyword-relevant match but never create one by itself.
        if not matched_kws:
            return None

        score = 0.0
        reasons: List[str] = []

        # Domain alignment — the strongest single signal.
        if domain_hit:
            score += 3.4
            reasons.append(f"Domeniu: {prod['domain'].capitalize()}")

        # Keyword evidence, with diminishing returns so one very generic
        # term can't outweigh genuine domain alignment.
        if matched_kws:
            score += min(3.0, 1.4 + 0.55 * (len(matched_kws) - 1))
            reasons.append(f"Relevanță tehnică: {', '.join(matched_kws[:4])}")

        # Geography now *reinforces* a match instead of creating one.
        if any(counties_match(opportunity.get("county", ""), c) for c in prod.get("target_counties", [])):
            score += 1.6
            reasons.append(f"Zonă vizată: {opportunity.get('county')}")
        elif opportunity.get("county"):
            reasons.append(f"În afara zonei prioritare ({opportunity.get('county')})")

        # Budget. Unknown budgets neither reward nor penalise — they're
        # flagged so the user knows the figure still has to be confirmed.
        value = opportunity.get("financial_value_ron") or opportunity.get("estimated_value_ron") or UNKNOWN_VALUE
        min_value = prod.get("min_value_ron", 0.0)
        if value == UNKNOWN_VALUE:
            score += 0.5
            reasons.append("Buget nepublicat — de confirmat la sursă")
        elif value >= min_value:
            score += 1.5
            reasons.append(f"Buget eligibil: {value:,.0f} RON")
        else:
            score -= 1.5
            reasons.append(f"Sub pragul diviziei ({value:,.0f} < {min_value:,.0f} RON)")

        # Pre-tender stages are worth more to a consultancy than a notice
        # that is already out to bid, because the specification can still
        # be influenced. Set by the CNI scrapers (see cni_common.py).
        stage = (opportunity.get("metadata") or {}).get("procurement_stage")
        if stage in ("pre_tender_approved_indicators", "pre_tender_documentation_review"):
            score += 0.8
            reasons.append("Fază pre-licitație — specificațiile pot fi încă influențate")

        final_score = max(0.0, min(10.0, round(score, 1)))
        if final_score < MATCH_THRESHOLD:
            return None

        return {
            "product_id": prod["product_id"],
            "product_name": prod["name"],
            "product_score": final_score,
            "reasons": reasons,
        }

    @staticmethod
    def evaluate_opportunity_for_tenant(opportunity: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        tenant = TENANT_ORGANIZATIONS.get(tenant_id)
        if not tenant:
            # Fail closed. This previously returned is_match=True, so an
            # unrecognised tenant id matched every opportunity in the feed
            # and would have been alerted about all of them.
            logger.warning(f"[Matching] Unknown tenant_id '{tenant_id}' — no match returned.")
            return {
                "tenant_id": tenant_id,
                "is_match": False,
                "tenant_opportunity_score": 0.0,
                "product_matches": [],
                "match_reasons": ["Tenant necunoscut — configurație lipsă"],
            }

        matched_products = [
            match
            for match in (
                TenantMatchingEngine._score_product(opportunity, prod)
                for prod in tenant.get("products", [])
            )
            if match is not None
        ]
        matched_products.sort(key=lambda m: m["product_score"], reverse=True)

        return {
            "tenant_id": tenant_id,
            "is_match": bool(matched_products),
            "tenant_opportunity_score": matched_products[0]["product_score"] if matched_products else 0.0,
            "product_matches": matched_products,
            "match_reasons": matched_products[0]["reasons"] if matched_products else ["Nu corespunde profilului diviziilor"],
        }
