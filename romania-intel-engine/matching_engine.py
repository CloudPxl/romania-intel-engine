import logging
from typing import List, Dict, Any

logger = logging.getLogger("MatchingEngine")

TENANT_PROFILES = {
    "t1_infra_transilvania": {
        "name": "SC Infra Construct Transilvania SRL",
        "primary_domains": ["infrastructura", "constructii", "smart-city"],
        "target_counties": ["Cluj", "Iasi", "Bihor", "Timis", "Bucuresti"],
        "min_deal_value_ron": 5000000.0,
        "keywords": ["drum", "trafic", "its", "pod", "complex", "sala", "asfalt", "reabilitare", "infrastructura"]
    },
    "t2_medtech_bucuresti": {
        "name": "SC MedTech Pharma SRL",
        "primary_domains": ["sanatate", "medtech", "medical"],
        "target_counties": ["Bucuresti", "Iasi", "Cluj", "Timis", "Dolj"],
        "min_deal_value_ron": 1000000.0,
        "keywords": ["radioterapie", "rmn", "ct", "spital", "imagistica", "medical", "oncologie", "laborator"]
    },
    "t3_vest_consulting_grants": {
        "name": "SC Vest Project Consulting",
        "primary_domains": ["energie", "granturi", "consultanta", "infrastructura"],
        "target_counties": ["Cluj", "Timis", "Iasi", "Arad", "Bihor"],
        "min_deal_value_ron": 2000000.0,
        "keywords": ["pnrr", "energie", "fotovoltaic", "cogenerare", "mipe", "grant", "bess", "eficienta"]
    }
}

class TenantMatchingEngine:
    """
    Evaluates raw qualified opportunities against tenant business profiles and products.
    """
    @staticmethod
    def calculate_tenant_fit(opportunity: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        profile = TENANT_PROFILES.get(tenant_id)
        if not profile:
            return {"match": True, "tenant_score": 8.0, "reasons": ["Default workspace access"]}

        reasons = []
        score_boost = 0.0

        # 1. County geographic alignment
        opp_county = opportunity.get("county", "")
        if opp_county in profile["target_counties"]:
            score_boost += 1.0
            reasons.append(f"Zonă prioritară de acțiune ({opp_county})")

        # 2. Domain matching
        opp_cat = opportunity.get("category", "")
        if opp_cat in profile["primary_domains"]:
            score_boost += 1.5
            reasons.append(f"Domeniu principal ({opp_cat.capitalize()})")

        # 3. Budget threshold
        val = opportunity.get("financial_value_ron", 0)
        if val >= profile["min_deal_value_ron"]:
            score_boost += 1.0
            reasons.append(f"Valoare peste prag ({val:,.0f} RON)")

        # 4. Deep keyword match in title & description
        combined_text = f"{opportunity.get('project_title', '')} {opportunity.get('executive_summary', '')}".lower()
        matched_kw = [kw for kw in profile["keywords"] if kw in combined_text]
        if matched_kw:
            score_boost += min(1.5, len(matched_kw) * 0.5)
            reasons.append(f"Cuvinte-cheie identificate: {matched_kw[:3]}")

        final_score = min(10.0, round(6.0 + score_boost, 1))
        is_match = final_score >= 7.5

        return {
            "tenant_id": tenant_id,
            "is_match": is_match,
            "tenant_opportunity_score": final_score,
            "match_reasons": reasons
        }
