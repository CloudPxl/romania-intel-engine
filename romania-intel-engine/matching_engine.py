import logging
from typing import Dict, Any, List

logger = logging.getLogger("MatchingEngine")

TENANT_ORGANIZATIONS = {
    "t1_infra_transilvania": {
        "name": "SC Infra Construct Transilvania SRL",
        "primary_domain": "infrastructura",
        "alert_emails": ["director@infraconstruct.ro"],
        "telegram_chat_id": None,
        "min_alert_score": 9.0,
        "products": [
            {
                "product_id": "prod_heavy_infra",
                "name": "Divizia Infrastructură Grea & Drumuri Județene",
                "domain": "infrastructura",
                "target_counties": ["Cluj", "Iasi", "Bihor", "Timis", "Bucuresti", "Constanta"],
                "min_value_ron": 10000000.0,
                "keywords": ["drum", "pod", "pasaj", "asfalt", "reabilitare", "infrastructura", "metrou", "sala"]
            },
            {
                "product_id": "prod_smart_traffic",
                "name": "Divizia Smart City & Sisteme ITS SCATS",
                "domain": "infrastructura",
                "target_counties": ["Iasi", "Cluj", "Bucuresti", "Timis", "Constanta"],
                "min_value_ron": 3000000.0,
                "keywords": ["its", "trafic", "semaforizare", "anpr", "senzori", "scats", "monitorizare"]
            }
        ]
    },
    "t2_medtech_bucuresti": {
        "name": "SC MedTech Pharma SRL",
        "primary_domain": "sanatate",
        "alert_emails": ["office@ro-intel.xyz"],
        "telegram_chat_id": None,
        "min_alert_score": 9.0,
        "products": [
            {
                "product_id": "prod_radiology_advanced",
                "name": "Divizia Imagistică Avansată & Radioterapie",
                "domain": "sanatate",
                "target_counties": ["Bucuresti", "Iasi", "Cluj", "Timis", "Dolj"],
                "min_value_ron": 5000000.0,
                "keywords": ["rmn", "ct", "radioterapie", "accelerator", "imagistica", "spital", "oncologie"]
            }
        ]
    },
    "t3_vest_consulting_grants": {
        "name": "SC Vest Project Consulting",
        "primary_domain": "energie",
        "alert_emails": ["office@ro-intel.xyz"],
        "telegram_chat_id": None,
        "min_alert_score": 9.0,
        "products": [
            {
                "product_id": "prod_green_energy",
                "name": "Divizia Consultanță Parcuri Solare & BESS",
                "domain": "energie",
                "target_counties": ["Timis", "Cluj", "Iasi", "Constanta", "Bihor"],
                "min_value_ron": 5000000.0,
                "keywords": ["fotovoltaic", "solar", "energie", "baterii", "stocare", "cogenerare", "pnrr"]
            }
        ]
    }
}

class TenantMatchingEngine:
    @staticmethod
    def evaluate_opportunity_for_tenant(opportunity: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        tenant = TENANT_ORGANIZATIONS.get(tenant_id)
        if not tenant:
            return {"is_match": True, "tenant_opportunity_score": 8.5, "product_matches": [], "match_reasons": ["Aliniere generală"]}

        matched_products = []
        highest_score = 0.0

        for prod in tenant["products"]:
            score = 7.0
            reasons = []

            if opportunity.get("county") in prod["target_counties"]:
                score += 1.2
                reasons.append(f"Zonă vizată: {opportunity.get('county')}")

            if opportunity.get("category") == prod["domain"]:
                score += 1.0
                reasons.append(f"Domeniu: {prod['domain'].capitalize()}")

            if opportunity.get("financial_value_ron", 0) >= prod["min_value_ron"]:
                score += 0.8
                reasons.append(f"Buget eligibil: {opportunity.get('financial_value_ron', 0):,.0f} RON")

            text = f"{opportunity.get('project_title', '')} {opportunity.get('executive_summary', '')}".lower()
            matched_kws = [kw for kw in prod["keywords"] if kw in text]
            if matched_kws:
                score += min(1.2, len(matched_kws) * 0.4)
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
            "tenant_opportunity_score": highest_score or 8.5,
            "product_matches": matched_products,
            "match_reasons": matched_products[0]["reasons"] if matched_products else ["Aliniere regională"]
        }
