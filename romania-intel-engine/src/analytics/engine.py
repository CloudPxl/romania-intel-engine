import os
import json
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime
from src.database.models import get_db_connection, is_postgres

class TenantAIAnalyticsEngine:
    def __init__(self):
        self.grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")

    def aggregate_tenant_market_data(self, tenant_id: str) -> Dict[str, Any]:
        conn = get_db_connection()
        cursor = conn.cursor()
        ph = "%s" if is_postgres() else "?"

        cursor.execute(f"""
            SELECT s.source_id, s.category, s.county, s.locality, s.project_title, s.entity_name,
                   s.financial_value_ron, s.trade_tags, s.opportunity_score, s.action_deadline, s.source_url
            FROM tenant_dispatches d
            JOIN structured_intel s ON d.source_id = s.source_id
            WHERE d.tenant_id = {ph}
            ORDER BY s.opportunity_score DESC, s.financial_value_ron DESC NULLS LAST
        """, (tenant_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return {
                "total_leads": 0,
                "total_pipeline_ron": 0.0,
                "avg_opportunity_score": 0.0,
                "county_distribution": [],
                "top_spenders": [],
                "tag_density": {},
                "raw_leads": []
            }

        total_val = 0.0
        scores = []
        counties = {}
        entities = {}
        tag_density = {}
        raw_leads = []

        for r in rows:
            val = float(r[6]) if r[6] is not None else 0.0
            total_val += val
            scores.append(int(r[8] or 1))

            c = r[2] or "National"
            counties[c] = counties.get(c, 0.0) + val

            ent = r[5] or "Autoritate Publică"
            entities[ent] = entities.get(ent, 0.0) + (val if val > 0 else 50000.0)

            tags = json.loads(r[7]) if isinstance(r[7], str) else (r[7] or [])
            for t in tags:
                tag_density[t] = tag_density.get(t, 0) + 1

            raw_leads.append({
                "title": r[4],
                "entity": ent,
                "county": c,
                "value_ron": val,
                "score": r[8]
            })

        top_counties = sorted([{"county": k, "total_ron": v} for k, v in counties.items()], key=lambda x: x["total_ron"], reverse=True)[:5]
        top_spenders = sorted([{"entity": k, "estimated_volume_ron": v} for k, v in entities.items()], key=lambda x: x["estimated_volume_ron"], reverse=True)[:5]

        return {
            "total_leads": len(rows),
            "total_pipeline_ron": total_val,
            "avg_opportunity_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "county_distribution": top_counties,
            "top_spenders": top_spenders,
            "tag_density": tag_density,
            "sample_high_yield_leads": raw_leads[:5]
        }

    def generate_ai_executive_briefing(self, tenant_name: str, tier: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        total_leads = market_data["total_leads"]
        total_val = market_data["total_pipeline_ron"]
        top_c = ", ".join([c["county"] for c in market_data["county_distribution"][:3]]) or "România"

        if total_leads == 0:
            return {
                "executive_summary": f"Nu există suficiente dosare filtrate pentru contul {tenant_name}. Recomandăm extinderea ariei geografice sau a etichetelor industriale.",
                "tactical_actions": [
                    "Extindeți județele selectate în Setări Cont.",
                    "Includeți categorii conexe de achiziții directe și autorizații de construire."
                ],
                "procurement_trend": "Neutru"
            }

        if self.grok_key:
            try:
                headers = {
                    "Authorization": f"Bearer {self.grok_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": "grok-2-latest",
                    "messages": [
                        {
                            "role": "system",
                            "content": "Ești un Consilier Executiv B2B și Director de Ofertare Comercială în România. Răspunzi strict în format JSON."
                        },
                        {
                            "role": "user",
                            "content": f"""
Analizează pipeline-ul de oportunități pentru compania: "{tenant_name}" (Abonament: {tier}).

Metrici:
- Număr Oportunități: {total_leads}
- Volum Financiar Pipeline: {total_val:,.0f} RON
- Județe Principale: {top_c}
- Top Cumpărători/Dezvoltatori: {json.dumps(market_data['top_spenders'][:3], ensure_ascii=False)}

Răspunde STRICT în format JSON cu această schemă exactă:
{{
    "executive_summary": "Sinteză de piață în 3-4 fraze despre unde merită ofertat imediat",
    "tactical_actions": ["acțiunea 1", "acțiunea 2", "acțiunea 3"],
    "procurement_trend": "Tendință achiziții (ex: Accentuat pe PNRR / Energie Verde)"
}}
"""
                        }
                    ],
                    "temperature": 0.3
                }
                response = httpx.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=20.0)
                if response.status_code == 200:
                    raw_resp = response.json()["choices"][0]["message"]["content"].strip()
                    if raw_resp.startswith("```json"):
                        raw_resp = raw_resp[7:-3].strip()
                    elif raw_resp.startswith("```"):
                        raw_resp = raw_resp[3:-3].strip()
                    return json.loads(raw_resp)
            except Exception as e:
                print(f"[!] Grok API error: {e}. Falling back to default briefing.")

        return {
            "executive_summary": (
                f"Pentru portofoliul {tenant_name}, s-au identificat {total_leads} oportunități cu un buget total estimat de {total_val:,.0f} RON. "
                f"Polul principal de investiții este concentrat în județele {top_c}. "
                f"Se recomandă prioritizarea ofertelor în faza de consultare de piață și depunerea directă pe loturile cu scor peste 8/10."
            ),
            "tactical_actions": [
                f"Contactați direct echipele tehnice ale primilor dezvoltatori ({', '.join([s['entity'][:25] for s in market_data['top_spenders'][:2]])}).",
                "Pregătiți formularele de calificare tehnică pentru contractele aflate sub termen limită de 14 zile.",
                "Setați alerte instantanee pentru proiectele din faza de aviz de mediu (APM) pentru a securiza subcontractarea înainte de emiterea AC."
            ],
            "procurement_trend": "Accentuat pe Infrastructură & Fonduri Nerambursabile"
        }
