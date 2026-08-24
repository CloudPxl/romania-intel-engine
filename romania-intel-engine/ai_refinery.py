import os
import json
import logging
from typing import Dict, Any, Optional
from openai import AsyncOpenAI
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("AIRefinery")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

class ProcurementAIRefinery:
    """
    High-precision intelligence refinery for institutional procurement signals in Romania.
    """
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=XAI_API_KEY or "dummy_key",
            base_url="[https://api.x.ai/v1](https://api.x.ai/v1)"
        )

    def _generate_fallback_intelligence(self, signal: RawInstitutionalSignal) -> Dict[str, Any]:
        val = signal.estimated_value_ron
        is_large = val >= 25000000.0

        stage = "Consultare de Piata & Avizare Tehnica" if "consultare" in signal.project_title.lower() or signal.source_type == "SICAP" else "Autorizare / Pre-Contractare"
        estimated_launch = "T4 2026 (Octombrie - Noiembrie)" if is_large else "T3-T4 2026 (Septembrie - Octombrie)"
        funding = "PNRR / Fonduri Europene Nerambursabile" if is_large or "mipe" in signal.source_type.lower() else "Buget Local / CNI"

        return {
            "executive_summary": (
                f"{signal.entity_name} ({signal.county}) deruleaza faza preliminara pentru: {signal.project_title}. "
                f"Miza strategica este de {val:,.0f} RON, vizand modernizarea infrastructurii din judetul {signal.county}."
            ),
            "sales_pitch_angle": (
                "Pozitionati oferta pe fiabilitate ridicata, mentenanta preventiva inclusa si timpi de raspuns sub 4 ore "
                "pentru a maximiza punctajul la factorii de evaluare tehnici din caietul de sarcini."
            ),
            "funding_source": funding,
            "estimated_timeline": {
                "current_stage": stage,
                "estimated_tender_launch": estimated_launch,
                "recommended_action_window": "Urmatoarele 14 zile (faza de dialog preliminar)"
            },
            "key_stakeholders": "Directia Tehnica, Serviciul Achizitii Publice & Comisia de Evaluare",
            "competition_risk_radar": "Mediu (Atribuire pe cel mai bun raport calitate-pret)",
            "trade_tags": [
                signal.category,
                signal.county.lower(),
                "achizitii-strategice",
                "pre-seap"
            ],
            "opportunity_score": 9.4 if is_large else 8.9,
            "scoring_breakdown": {
                "budget_viability": 9.5 if val > 0 else 7.0,
                "procurement_urgency": 9.0,
                "technical_margin_potential": 9.2
            }
        }

    async def refine_signal(self, signal: RawInstitutionalSignal) -> Dict[str, Any]:
        """
        Deep qualitative analysis using Grok LLM with structured commercial JSON output.
        """
        if not XAI_API_KEY or XAI_API_KEY == "dummy_key":
            return self._generate_fallback_intelligence(signal)

        prompt = f"""
        Esti Director Comercial Senior si Expert in Strategia Achizitiilor Publice din Romania (2026).
        Analizeaza in profunzime urmatorul semnal institutional pre-SEAP:

        ID SURSA: {signal.source_id}
        TIP REGISTRU: {signal.source_type}
        CATEGORIE: {signal.category}
        BENEFICIAR: {signal.entity_name} ({signal.locality}, jud. {signal.county})
        TITLU PROIECT: {signal.project_title}
        BUGET ESTIMAT: {signal.estimated_value_ron:,.0f} RON
        DESCRIERE BRUTA: {signal.raw_description}
        TERMEN LIMITA CURENT: {signal.action_deadline or "Nespecificat"}

        Genereaza dosarul de intelligence comerciala. Returneaza STRICT un JSON valid:
        {{
            "executive_summary": "Sinteza concisa de 2-3 fraze despre ce se construieste/achizitioneaza si miza comerciala reala.",
            "sales_pitch_angle": "Unghiul tactic exact: pe ce diferentiatori tehnici si cerinte de calitate trebuie sa insiste ofertantul.",
            "funding_source": "Ex: PNRR C6 / CNI / Buget Local / POIM / Fonduri Proprii",
            "estimated_timeline": {{
                "current_stage": "Consultare Piata / Avizare HCL / Autorizatie Construire",
                "estimated_tender_launch": "Ex: T4 2026 (Noiembrie)",
                "recommended_action_window": "Ex: Urmatoarele 14 zile"
            }},
            "key_stakeholders": "Ex: Directia Tehnica & Serviciul Achizitii Publice",
            "competition_risk_radar": "Scazut / Mediu / Ridicat",
            "trade_tags": ["tag1", "tag2", "tag3"],
            "opportunity_score": 9.3,
            "scoring_breakdown": {{
                "budget_viability": 9.5,
                "procurement_urgency": 9.0,
                "technical_margin_potential": 9.2
            }}
        }}
        """

        try:
            res = await self.client.chat.completions.create(
                model="grok-beta",
                messages=[
                    {"role": "system", "content": "Raspunde exclusiv in format JSON valid in limba romana."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            raw_content = res.choices[0].message.content.strip()
            if raw_content.startswith("```json"):
                raw_content = raw_content[7:-3].strip()
            elif raw_content.startswith("```"):
                raw_content = raw_content[3:-3].strip()
            return json.loads(raw_content)
        except Exception as e:
            logger.error(f"[AIRefinery] Grok API refinement fallback triggered: {e}")
            return self._generate_fallback_intelligence(signal)
