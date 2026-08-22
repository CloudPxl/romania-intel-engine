import json
from typing import List, Dict, Any, Optional

class ClientDossierFormatter:
    """Formats structured leads into high-impact executive summaries for clients."""

    @staticmethod
    def _safe_tags(raw_tags: Any) -> str:
        if isinstance(raw_tags, list):
            return ", ".join(str(t) for t in raw_tags)
        try:
            parsed = json.loads(raw_tags or "[]")
            if isinstance(parsed, list):
                return ", ".join(str(t) for t in parsed)
        except (json.JSONDecodeError, TypeError):
            pass
        return "general"

    @staticmethod
    def format_email_digest(company_name: str, matched_leads: List[Dict[str, Any]]) -> str:
        """Generates a formatted text briefing for executive email delivery."""
        if not matched_leads:
            return f"Bună ziua,\n\nNu există alerte noi conform filtrelor companiei {company_name} pentru astăzi."

        output = [
            f"==================================================================",
            f" RAPORT INTELIGENȚĂ COMERCIALĂ B2B - {company_name.upper()}",
            f" Total Oportunități Noi Calificate: {len(matched_leads)}",
            f"==================================================================\n"
        ]

        for idx, lead in enumerate(matched_leads, 1):
            val_str = f"{lead['financial_value_ron']:,.0f} RON" if lead.get("financial_value_ron") else "Buget Consultare / Proiect"
            tags = ClientDossierFormatter._safe_tags(lead.get("trade_tags"))

            output.append(f"[{idx}] ⭐ PRIORITATE: {lead['opportunity_score']}/10 | {lead['county'].upper()}")
            output.append(f" • Proiect: {lead['project_title']}")
            output.append(f" • Entitate / Dezvoltator: {lead['entity_name']}")
            output.append(f" • Valoare Estimată: {val_str}")
            output.append(f" • Domenii Vizate: {tags}")
            output.append(f" • Unghi de Vânzare / Acțiune: {lead['sales_pitch_angle']}")
            output.append(f" • Termen Limită: {lead['action_deadline'] or 'Nespecificat'}")
            output.append(f" • Link Dosar Oficial: {lead['source_url'] or 'N/A'}")
            output.append("-" * 66 + "\n")

        return "\n".join(output)