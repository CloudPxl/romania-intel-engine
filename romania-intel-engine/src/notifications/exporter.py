import csv
import json
import io
from typing import List, Dict, Any
from pathlib import Path
from src.config import DATA_DIR

class LeadExporter:
    @staticmethod
    def export_to_csv_string(matched_leads: List[Dict[str, Any]]) -> str:
        """Generates a RFC 4180 compliant CSV string for CRM imports."""
        output = io.StringIO()
        fieldnames = [
            "Scor Oportunitate",
            "Judet",
            "Entitate / Dezvoltator",
            "Titlu Proiect",
            "Valoare Estimata (RON)",
            "Domenii Comerciale",
            "Plan de Actiune Vanzari",
            "Termen Limita",
            "Link Dosar Oficial"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for lead in matched_leads:
            tags = ", ".join(json.loads(lead["trade_tags"])) if isinstance(lead["trade_tags"], str) else ", ".join(lead["trade_tags"])
            val = f"{lead['financial_value_ron']:,.0f}" if lead.get("financial_value_ron") else "N/A"
            
            writer.writerow({
                "Scor Oportunitate": lead.get("opportunity_score", 5),
                "Judet": lead.get("county", "RO"),
                "Entitate / Dezvoltator": lead.get("entity_name", "Necunoscut"),
                "Titlu Proiect": lead.get("project_title", ""),
                "Valoare Estimata (RON)": val,
                "Domenii Comerciale": tags,
                "Plan de Actiune Vanzari": lead.get("sales_pitch_angle", ""),
                "Termen Limita": lead.get("action_deadline") or "In desfasurare",
                "Link Dosar Oficial": lead.get("source_url") or ""
            })

        return output.getvalue()

    @staticmethod
    def save_client_export(tenant_name: str, matched_leads: List[Dict[str, Any]]) -> Path:
        """Saves a tenant-specific CSV file to the data directory."""
        export_dir = DATA_DIR / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        safe_name = "".join(c for c in tenant_name if c.isalnum() or c in (' ', '_', '-')).strip().replace(" ", "_")
        file_path = export_dir / f"Leads_{safe_name}.csv"
        
        csv_content = LeadExporter.export_to_csv_string(matched_leads)
        file_path.write_text(csv_content, encoding="utf-8-sig") # utf-8-sig opens cleanly in Excel
        return file_path