import logging
from typing import List, Dict, Any

logger = logging.getLogger("FreemiumShield")
FREE_TIER_MAX_VISIBLE_LEADS = 2

class FreemiumGatekeeper:
    @staticmethod
    def enforce_paywall_tier(leads: List[Dict[str, Any]], has_active_subscription: bool = True) -> List[Dict[str, Any]]:
        if has_active_subscription:
            return leads

        sanitized_leads = []
        for index, lead in enumerate(leads):
            if index < FREE_TIER_MAX_VISIBLE_LEADS:
                lead_copy = dict(lead)
                lead_copy["is_freemium_preview"] = True
                lead_copy["is_locked"] = False
                sanitized_leads.append(lead_copy)
            else:
                locked_lead = {
                    "source_id": f"LOCKED-{lead.get('source_id', '')[:8]}",
                    "source_type": lead.get("source_type"),
                    "category": lead.get("category"),
                    "county": lead.get("county"),
                    "locality": lead.get("locality"),
                    "project_title": lead.get("project_title"),
                    "entity_name": lead.get("entity_name"),
                    "financial_value_ron": 0.0,
                    "opportunity_score": lead.get("opportunity_score"),
                    "executive_summary": "🔒 Conținut protejat. Disponibil în abonamentul Acces Complet (499 RON) sau VIP Founder (1499 RON).",
                    "sales_pitch_angle": "🔒 Deblocați planul pentru unghiul comercial tactic xAI Grok.",
                    "funding_source": "🔒 Sursă Protejată",
                    "estimated_timeline": {"current_stage": "🔒 Disponibil în Abonament", "estimated_tender_launch": "🔒 Blocat"},
                    "is_locked": True,
                    "is_freemium_preview": False
                }
                sanitized_leads.append(locked_lead)

        return sanitized_leads
