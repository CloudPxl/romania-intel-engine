import logging
from typing import Dict, Any, List

logger = logging.getLogger("CompetitorTracker")

MARKET_BENCHMARKS = {
    "infrastructura": {
        "avg_discount_pct": 8.4,
        "undercut_risk": "Mediu-Ridicat",
        "cnsc_dispute_rate": "28%",
        "frequent_players": ["Strabag SRL", "Porr Construct", "Con-A Sibiu", "Ness Proiect Europe", "UTI Facility Management"],
        "pricing_strategy": "Evitati discounturi sub 82% din valoarea estimata pentru a preveni cererile de justificare de pret neobisnuit de scazut (Art. 215 Legea 98/2016)."
    },
    "sanatate": {
        "avg_discount_pct": 4.8,
        "undercut_risk": "Scazut",
        "cnsc_dispute_rate": "34%",
        "frequent_players": ["Medist SRL", "Siemens Healthcare", "General Electric Medical", "Deltamed SRL", "Gral Medical"],
        "pricing_strategy": "Punctajul tehnic (garantie extinsa, SLA service sub 4 ore) cantareste adesea 40-50% din decizia finala de atribuire."
    },
    "energie": {
        "avg_discount_pct": 6.2,
        "undercut_risk": "Mediu",
        "cnsc_dispute_rate": "19%",
        "frequent_players": ["Electrogrup SA", "EnergoBit SA", "Eroup", "Restart Energy One", "Adrem Engineering"],
        "pricing_strategy": "Accentul este pus pe randamentul panourilor (>22%) si eficienta sistemelor de stocare BESS."
    },
    "aparare": {
        "avg_discount_pct": 3.1,
        "undercut_risk": "Scazut",
        "cnsc_dispute_rate": "12%",
        "frequent_players": ["Interactive Systems & Business", "Rasirom RA", "Mira Technologies", "Romarm SA", "Lockheed Martin Partner Network"],
        "pricing_strategy": "Calificarea este conditionata strict de autorizatii ORNISS/NATO si conformitate STANAG."
    },
    "digitalizare": {
        "avg_discount_pct": 9.8,
        "undercut_risk": "Ridicat",
        "cnsc_dispute_rate": "31%",
        "frequent_players": ["Teamnet International", "Siveco / TotalSoft", "Maguay Computers", "Asseco SEE", "Connections Consult"],
        "pricing_strategy": "Diferentiatorul major il reprezinta arhitectura deschisa (API REST) si timpii de implementare agili."
    }
}

class CompetitorTrackerEngine:
    @staticmethod
    def analyze_landscape(category: str, county: str, budget_ron: float) -> Dict[str, Any]:
        cat_key = category.lower() if category.lower() in MARKET_BENCHMARKS else "infrastructura"
        benchmark = MARKET_BENCHMARKS[cat_key]

        avg_discount = benchmark["avg_discount_pct"]
        optimal_price = budget_ron * (1 - (avg_discount / 100.0))
        aggressive_price = budget_ron * 0.82
        safe_price = budget_ron * 0.94

        return {
            "sector": category.capitalize(),
            "county": county,
            "estimated_budget_ron": budget_ron,
            "benchmark": {
                "historical_avg_discount": f"{avg_discount}%",
                "undercutting_risk": benchmark["undercut_risk"],
                "cnsc_dispute_frequency": benchmark["cnsc_dispute_rate"],
                "identified_key_competitors": benchmark["frequent_players"],
                "tactical_guidance": benchmark["pricing_strategy"]
            },
            "pricing_recommendations": {
                "safe_margin_bid_ron": safe_price,
                "optimal_competitive_bid_ron": optimal_price,
                "aggressive_limit_bid_ron": aggressive_price
            }
        }
