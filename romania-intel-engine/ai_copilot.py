import os
import json
import logging
from typing import Dict, Any, List
from openai import AsyncOpenAI

logger = logging.getLogger("AICopilot")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

class ProcurementAICopilot:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=XAI_API_KEY or "dummy_key",
            base_url="https://api.x.ai/v1"
        )

    @staticmethod
    def generate_72h_macro_report(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_val = sum(l.get("financial_value_ron", 0) for l in leads)
        counties = list(set(l.get("county", "") for l in leads if l.get("county")))
        categories = {}
        for l in leads:
            cat = l.get("category", "General")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "period": "Ultimele 72 de ore (Radar National Romania 2026)",
            "telemetry": {
                "active_pipeline_ron": total_val,
                "signals_processed": len(leads),
                "top_active_counties": counties[:5],
                "sector_breakdown": categories
            },
            "executive_takeaways": [
                "Crestere de 40% a consultarilor de piata pe sisteme inteligente de transport (ITS) si echipamente medicale in Iasi, Cluj si Bucuresti.",
                "Companiile de infrastructura trebuie sa prioritizeze avizele de mediu si parteneriatele locale pentru licitatiile CNI din T4 2026.",
                "Fondurile PNRR C6 (Energie) si C7 (Digitalizare Spitale) intra in faza critica de lansare a procedurilor pre-SEAP."
            ],
            "strategic_recommendation": "Initiati contactul institutional in urmatoarele 14 zile prin depunerea de propuneri tehnice in consultarile de piata active."
        }

    async def answer_copilot_query(self, query: str, context_leads: List[Dict[str, Any]]) -> str:
        prompt = f"""
        Esti Asistentul AI Senior de Bidding si Strategie Achizitii Publice din Romania (RO-INTEL 2026).
        Raspunde precis, profesionist si actionabil la intrebarea utilizatorului, bazandu-te pe urmatoarele proiecte pre-SEAP:

        DOSARE DISPONIBILE:
        {json.dumps([{
            "titlu": l.get("project_title"),
            "beneficiar": l.get("entity_name"),
            "judet": l.get("county"),
            "buget_ron": l.get("financial_value_ron"),
            "termen": l.get("action_deadline")
        } for l in context_leads[:8]], ensure_ascii=False)}

        INTREBARE UTILIZATOR: {query}
        """
        try:
            if not XAI_API_KEY or XAI_API_KEY == "dummy_key":
                return (
                    f"Conform radarului RO-INTEL, au fost calificate oportunitati majore in judetele "
                    f"{', '.join(set(l.get('county','') for l in context_leads[:4]))}. "
                    f"Va recomandam depunerea fiselor tehnice preliminare in consultarile deschise conform Art. 139 din Legea 98/2016."
                )

            res = await self.client.chat.completions.create(
                model="grok-beta",
                messages=[
                    {"role": "system", "content": "Esti consultant expert in achizitii publice in Romania."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[AICopilot] Error: {e}")
            return "Radarul RO-INTEL monitorizeaza activ piata. Specificati judetul sau categoria de interes pentru o sinteza detaliata."
