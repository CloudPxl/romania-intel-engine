import logging
from typing import List, Dict, Any

logger = logging.getLogger("MatchingEngine")

TENANT_ORGANIZATIONS = {
    "t1_infra_transilvania": {
        "name": "SC Infra Construct Transilvania SRL",
        "products": [
            {
                "product_id": "prod_heavy_infra",
                "name": "Divizia Infrastructură Grea & Drumuri Județene",
                "domain": "infrastructura",
                "target_counties": ["Cluj", "Iasi", "Bihor", "Timis", "Bucuresti"],
                "min_value_ron": 10000000.0,
                "keywords": ["drum", "pod", "pasaj", "asfalt", "reabilitare", "infrastructura", "metrou", "sala"]
            },
            {
                "product_id": "prod_smart_traffic",
                "name": "Divizia Smart City & Sisteme ITS SCATS",
                "domain": "infrastructura",
                "target_counties": ["Iasi", "Cluj", "Bucuresti", "Timis", "Brasov"],
                "min_value_ron": 3000000.0,
                "keywords": ["its", "trafic", "semaforizare", "anpr", "senzori", "scats", "monitorizare"]
            }
        ]
    },
    "t2_medtech_bucuresti": {
        "name": "SC MedTech Pharma SRL",
        "products": [
            {
                "product_id": "prod_oncology_hardware",
                "name": "Divizia Radioterapie & Acceleratoare Liniare",
                "domain": "sanatate",
                "target_counties": ["Bucuresti", "Iasi", "Cluj", "Timis", "Dolj"],
                "min_value_ron": 15000000.0,
                "keywords": ["radioterapie", "accelerator", "oncologie", "stereotaxica"]
            },
            {
                "product_id": "prod_imaging_pacs",
                "name": "Divizia Imagistică Avansată & PACS Cloud",
                "domain": "sanatate",
                "target_counties": ["Bucuresti", "Iasi", "Cluj", "Timis", "Constanta"],
                "min_value_ron": 5000000.0,
                "keywords": ["rmn", "ct", "imagistica", "pacs", "servere medicale", "spital"]
            }
        ]
    },
    "t3_vest_consulting_grants": {
        "name": "SC Vest Project Consulting",
        "products": [
            {
                "product_id": "prod_solar_bess_grants",
                "name": "Divizia Parcuri Solare & Sisteme BESS Industriale",
                "domain": "energie",
                "target_counties": ["Cluj", "Timis", "Iasi", "Arad", "Bihor"],
                "min_value_ron": 5000000.0,
                "keywords": ["fotovoltaic", "solar", "bess", "stocare", "energie", "parc industrial"]
            },
            {
                "product_id": "prod_pnrr_consulting",
                "name": "Divizia Consultanță Nerambursabilă PNRR / MIPE",
                "domain": "energie",
                "target_counties": ["Cluj", "Iasi", "Bucuresti", "Timis"],
                "min_value_ron": 2000000.0,
                "keywords": ["pnrr", "mipe", "grant", "ghid", "cogenerare", "eficienta"]
            }
        ]
    }
}

class TenantMatchingEngine:
    @staticmethod
    def evaluate_opportunity_for_tenant(opportunity: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        org = TENANT_ORGANIZATIONS.get(tenant_id)
        if not org:
            return {"is_match": True, "tenant_opportunity_score": 8.5, "product_matches": []}

        matched_products = []
        highest_score = 6.0

        for prod in org["products"]:
            score = 6.0
            reasons = []
            target_domain = prod.get("domain", "")

            # 1. Geographic match
            opp_county = opportunity.get("county", "")
            if opp_county in prod["target_counties"]:
                score += 1.2
                reasons.append(f"Zonă vizată: {opp_county}")

            # 2. Domain category match
            if opportunity.get("category", "") == target_domain:
                score += 1.5
                reasons.append(f"Domeniu: {target_domain.capitalize()}")

            # 3. Budget threshold
            val = opportunity.get("financial_value_ron", 0)
            if val >= prod["min_value_ron"]:
                score += 1.0
                reasons.append(f"Buget eligibil: {val:,.0f} RON")

            # 4. Keyword relevance
            text = f"{opportunity.get('project_title', '')} {opportunity.get('executive_summary', '')}".lower()
            matched_kws = [kw for kw in prod["keywords"] if kw in text]
            if matched_kws:
                score += min(1.3, len(matched_kws) * 0.4)
                reasons.append(f"Cuvinte-cheie divizie: {matched_kws[:3]}")

            final_prod_score = min(10.0, round(score, 1))
            if final_prod_score >= 7.8:
                matched_products.append({
                    "product_id": prod["product_id"],
                    "product_name": prod["name"],
                    "product_score": final_prod_score,
                    "reasons": reasons
                })
                if final_prod_score > highest_score:
                    highest_score = final_prod_score

        return {
            "tenant_id": tenant_id,
            "is_match": len(matched_products) > 0,
            "tenant_opportunity_score": highest_score,
            "product_matches": matched_products,
            "match_reasons": matched_products[0]["reasons"] if matched_products else ["Aliniere generală"]
        }
