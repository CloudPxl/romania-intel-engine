import logging
from typing import Dict, Any, List

logger = logging.getLogger("CaietAnalyzer")

RESTRICTIVE_PATTERNS = [
    {"keyword": "experienta similara", "risk": "Mediu", "warning": "Verificați dacă cerința de experiență similară depășește valoarea maximă legală (max. 1x valoarea contractului conform Legii 98/2016)."},
    {"keyword": "termen de livrare sub", "risk": "Ridicat", "warning": "Termenul de livrare neobișnuit de scurt poate indica stocuri pre-aranjate de un competitor local."},
    {"keyword": "certificare specifica", "risk": "Ridicat", "warning": "Cerință de standard tehnic proprietar fără mențiunea expresă 'sau echivalent'. Risc de contestație CNSC."},
    {"keyword": "autorizatie producator", "risk": "Critic", "warning": "Obligativitatea autorizației directe de la producător (MAF) în faza de depunere este considerată clauză restrictivă conform jurisprudenței CNSC."}
]

class CaietDeSarciniAnalyzer:
    @staticmethod
    def analyze_specification_text(text: str, project_title: str) -> Dict[str, Any]:
        text_lower = text.lower()
        flagged_risks = []
        overall_risk_score = 1.0  # 1 (safe) to 10 (heavily biased)

        for item in RESTRICTIVE_PATTERNS:
            if item["keyword"] in text_lower:
                flagged_risks.append({
                    "pattern": item["keyword"],
                    "severity": item["risk"],
                    "tactical_advisory": item["warning"]
                })
                if item["risk"] == "Critic":
                    overall_risk_score += 3.5
                elif item["risk"] == "Ridicat":
                    overall_risk_score += 2.0
                else:
                    overall_risk_score += 1.0

        risk_level = "Scăzut (Specificații Deschise)"
        if overall_risk_score >= 7.0:
            risk_level = "Critic (Risc major de dedicație / Clauze restrictive)"
        elif overall_risk_score >= 4.0:
            risk_level = "Moderat (Necesită solicitare de clarificări)"

        return {
            "project_title": project_title,
            "bias_risk_level": risk_level,
            "bias_score": min(10.0, round(overall_risk_score, 1)),
            "detected_red_flags": flagged_risks if flagged_risks else [
                {"pattern": "Niciunul", "severity": "OK", "tactical_advisory": "Nu au fost identificate clauze restrictive evidente în textul analizat."}
            ],
            "recommended_action": (
                "Transmiteți o solicitare oficială de clarificări în baza Art. 160-161 din Legea 98/2016 "
                "pentru eliminarea barierelor tehnice identificate." if flagged_risks else "Caietul de sarcini este competitiv. Pregătiți dosarul tehnic."
            )
        }
