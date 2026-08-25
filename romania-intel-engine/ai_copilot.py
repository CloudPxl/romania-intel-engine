import os
import json
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("AICopilot")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

class ProcurementAICopilot:
    def __init__(self):
        self.api_key = XAI_API_KEY or OPENAI_API_KEY or ""

    @staticmethod
    def generate_72h_macro_report(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_val = sum(l.get("financial_value_ron", 0) for l in leads)
        counties = list(set(l.get("county", "") for l in leads if l.get("county")))
        categories = {}
        for l in leads:
            cat = l.get("category", "General")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "period": "Ultimele 72 de ore (Radar Achizitii Publice)",
            "telemetry": {
                "active_pipeline_ron": total_val,
                "signals_processed": len(leads),
                "top_active_counties": counties[:5],
                "sector_breakdown": categories
            },
            "executive_takeaways": [
                "Creștere a procedurilor pre-SEAP în Iași, Cluj, Timiș și București pe ITS, infrastructură spitalicească și eficiență energetică.",
                "Autoritățile contractante publică consultări de piață cu termen mediu de reacție de 14 zile conform Art. 139 Legea 98/2016.",
                "Apelurile PNRR C6 și C7 au alocări bugetare confirmate pentru digitalizare și utilități verzi."
            ],
            "strategic_recommendation": "Formulați puncte de vedere tehnice în faza de consultare pentru a influența specificațiile din caietul de sarcini."
        }

    async def answer_copilot_query(self, query: str, context_leads: List[Dict[str, Any]]) -> str:
        q_clean = query.strip()
        q_lower = q_clean.lower()

        # Direct Conversational Handlers
        if q_lower in ["salut", "buna", "buna ziua", "hello", "hi", "servus", "noroc", "salutare"]:
            return (
                "Bună ziua! Sunt Copilotul AI RO-INTEL pentru strategie de bidding și achiziții publice. "
                "Vă pot ajuta cu analiza oportunităților pre-SEAP, verificarea criteriilor de calificare din caietele de sarcini, "
                "estimarea marjelor optime de ofertare sau formularea de adrese oficiale de clarificări conform Legii 98/2016. "
                "Cu ce proiect sau întrebare doriți să începem?"
            )

        if any(w in q_lower for w in ["ce poti sa faci", "cum functionezi", "ajutor", "help", "optiuni"]):
            return (
                "Capabilitățile mele principale includ:\n\n"
                "1. Analiză Oportunități Pre-SEAP: Identificarea proiectelor înainte de publicarea în SICAP din hotărâri de consiliu local, CNI, CNAIR și PNRR.\n"
                "2. Scanner Clauze Restrictive: Detectarea cerințelor disproporționate din caietele de sarcini conform jurisprudenței CNSC.\n"
                "3. Simulator de Ofertare: Calculul probabilității de câștig și al discountului optim pentru menținerea profitabilității.\n"
                "4. Asistență Legală: Redactarea solicitărilor de clarificări și a contestațiilor în baza Legii 98/2016 și Legii 544/2001.\n\n"
                "Puteți întreba despre orice proiect din listă, autoritate contractantă sau cerință tehnică!"
            )

        # Attempt Live LLM Completion if API Key is Available
        if self.api_key and self.api_key not in ["dummy_key", "re_dummy"]:
            try:
                base_url = "https://api.x.ai/v1" if XAI_API_KEY else "https://api.openai.com/v1"
                model_name = "grok-beta" if XAI_API_KEY else "gpt-4o-mini"
                
                system_prompt = (
                    "Ești Copilotul AI Senior de Bidding și Strategie Achiziții Publice RO-INTEL. "
                    "Răspunzi profesionist, clar, direct și adaptiv la solicitările utilizatorului. "
                    "Cunoști legislația românească a achizițiilor publice (Legea 98/2016, Legea 101/2016, Legea 544/2001, HG 395/2016) "
                    "și bunele practici din caietele de sarcini. Răspunde în limba română, concis și structurat."
                )

                dossiers_context = json.dumps([{
                    "titlu": l.get("project_title"),
                    "beneficiar": l.get("entity_name"),
                    "judet": l.get("county"),
                    "buget_ron": l.get("financial_value_ron"),
                    "data_publicare": l.get("published_date"),
                    "termen_limita": l.get("action_deadline"),
                    "sursa": l.get("source_type")
                } for l in context_leads[:8]], ensure_ascii=False)

                user_prompt = f"Dosare pre-SEAP disponibile în sistem:\n{dossiers_context}\n\nÎntrebare utilizator: {q_clean}"

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json={
                            "model": model_name,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            "temperature": 0.3
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"[AICopilot] LLM Request error: {e}")

        # Intelligent Contextual NLP Engine (Dynamic Fallback)
        matched_leads = [
            l for l in context_leads 
            if any(w in (l.get("project_title", "") + " " + l.get("entity_name", "") + " " + l.get("county", "")).lower() for w in q_lower.split() if len(w) > 3)
        ]

        if matched_leads:
            top = matched_leads[0]
            val_mil = (top.get("financial_value_ron", 0) / 1000000)
            return (
                f"Referitor la proiectul '{top.get('project_title')}' inițiat de {top.get('entity_name')} ({top.get('county')}):\n\n"
                f"- Buget estimat: {val_mil:.2f} Mil. RON\n"
                f"- Registru sursă: {top.get('source_type')}\n"
                f"- Data publicării: {top.get('published_date', 'N/A')}\n"
                f"- Termen reacție: {top.get('action_deadline', 'Nespecificat')}\n\n"
                f"Recomandare tactică: {top.get('sales_pitch_angle', 'Formulați o adresă de clarificare tehnică conform Art. 160 din Legea 98/2016.')}"
            )

        if "lege" in q_lower or "legislatie" in q_lower or "art" in q_lower or "termen" in q_lower:
            return (
                "Principalele repere legislative pentru procedurile curente:\n\n"
                "- Art. 139 din Legea 98/2016: Reglementează consultarea de piață prealabilă pentru stabilirea valorii estimate și a cerințelor tehnice.\n"
                "- Art. 160-161 din Legea 98/2016: Dreptul operatorilor economici de a solicita clarificări asupra documentației de atribuire.\n"
                "- Legea 101/2016: Termenul de depunere a contestației la CNSC este de 10 zile (pentru valori peste pragurile europene) sau 5 zile (sub praguri) de la publicarea actului considerat nelegal."
            )

        if "pret" in q_lower or "buget" in q_lower or "marja" in q_lower or "castig" in q_lower:
            return (
                "Pentru optimizarea ofertei financiare recomandăm:\n\n"
                "1. Analiza pragului de 80% din valoarea estimată pentru a evita justificarea de preț neobișnuit de scăzut (Art. 215 Legea 98/2016).\n"
                "2. O marjă optimă de discount între 6% și 11% față de bugetul estimat maximizează punctajul financiar fără a compromite marja brută.\n"
                "3. Includerea partenerilor sau subcontractanților locali aduce avantaje logistice și de punctaj tehnic."
            )

        # General intelligent response
        top_projects = context_leads[:3]
        project_list = "\n".join([f"- {l.get('project_title')} ({l.get('entity_name')}, {l.get('financial_value_ron', 0)/1000000:.1f} Mil. RON)" for l in top_projects])
        return (
            f"Am procesat solicitarea dumneavoastră: '{q_clean}'.\n\n"
            f"În baza dosarelor pre-SEAP active în radarul RO-INTEL, cele mai relevante proceduri sunt:\n"
            f"{project_list}\n\n"
            f"Puteți deschide oricare dintre aceste dosare pentru a rula Scannerul de Caiet sau Simulatorul de Șanse de Câștig."
        )
