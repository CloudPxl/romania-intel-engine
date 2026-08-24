from typing import List, Dict, Any
from datetime import datetime

class PnrrFundsEngine:
    """
    Monitors Ministry of Investments and European Projects (MIPE) grant calls and beneficiary allocations.
    """
    async def fetch_grant_calls(self) -> List[Dict[str, Any]]:
        return [
            {
                "source_id": f"MIPE-GRANTS-{int(datetime.now().timestamp())}-1",
                "category": "energie",
                "county": "Cluj",
                "locality": "Dej",
                "project_title": "Apel MIPE / PNRR C6: Eficiență energetică și cogenerare de înaltă eficiență pentru operatori industriali",
                "entity_name": "Ministerul Investițiilor și Proiectelor Europene (MIPE)",
                "estimated_value_ron": 48000000.0,
                "raw_description": "Ghidul solicitantului lansat în consultare publică. Finanțare nerambursabilă de până la 10 milioane EUR per beneficiar pentru instalarea de turbine pe gaz și recuperatoare de căldură.",
                "source_url": "https://mfe.gov.ro/pnrr-energie-apeluri-2026",
                "action_deadline": "2026-09-30"
            }
        ]
