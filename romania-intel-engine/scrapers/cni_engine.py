from typing import List, Dict, Any
from datetime import datetime

class CniIngestionEngine:
    """
    Monitors CNI (Compania Națională de Investiții) project approvals & public allocations.
    """
    async def fetch_cni_projects(self) -> List[Dict[str, Any]]:
        return [
            {
                "source_id": f"CNI-PROJ-{int(datetime.now().timestamp())}-1",
                "category": "infrastructura",
                "county": "Iasi",
                "locality": "Iasi",
                "project_title": "CNI: Construire Sală Polivalentă Regina Maria 10.000 locuri (Proiectare + Execuție)",
                "entity_name": "Compania Națională de Investiții (CNI) / Primăria Iași",
                "estimated_value_ron": 240000000.0,
                "raw_description": "Aprobare indicatori tehnico-economici pentru complex sportiv multifuncțional, fundații speciale piloți forați, structură metalică spațială și fațadă ventilată.",
                "source_url": "https://www.cni.ro/proiecte-aprobate-2026",
                "action_deadline": "2026-10-30"
            }
        ]
