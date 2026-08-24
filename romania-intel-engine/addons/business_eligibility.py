import logging
from typing import Dict, Any

logger = logging.getLogger("EligibilityScanner")

ELIGIBLE_GRANT_PROGRAMS = [
    {
        "program_id": "PNRR-C6-ENERGIE",
        "name": "PNRR C6: Eficienta Energetica & Productie Energie Regenerabila",
        "target_caen": ["3511", "3512", "2711", "2712", "4222", "4321", "7112"],
        "min_turnover_ron": 1500000,
        "max_grant_eur": 15000000,
        "co_financing_pct": 35,
        "legal_basis": "Ghidul Solicitantului MIPE / PNRR Componenta 6 - Energie"
    },
    {
        "program_id": "PNRR-C7-DIGITALIZARE",
        "name": "PNRR C7: Digitalizarea Avansata a IMM-urilor & Sectorului Medical",
        "target_caen": ["6201", "6202", "6209", "6311", "3313", "8610"],
        "min_turnover_ron": 500000,
        "max_grant_eur": 3000000,
        "co_financing_pct": 10,
        "legal_basis": "Ordinul MCID / MIPE nr. 2026/C7"
    },
    {
        "program_id": "POR-INFRA-2026",
        "name": "Programul Regional: Competitivitate & Infrastructura Tehnologica",
        "target_caen": ["4120", "4211", "4213", "4299", "7111", "7112"],
        "min_turnover_ron": 2500000,
        "max_grant_eur": 5000000,
        "co_financing_pct": 25,
        "legal_basis": "Ghid Specific Agentiile pentru Dezvoltare Regionala (ADR)"
    }
]

class BusinessEligibilityEngine:
    @staticmethod
    def evaluate_company(
        company_name: str,
        cui_fiscal: str,
        caen_code: str,
        turnover_ron: float,
        employee_count: int,
        county: str
    ) -> Dict[str, Any]:
        matched_grants = []

        for p in ELIGIBLE_GRANT_PROGRAMS:
            is_caen_match = caen_code in p["target_caen"] or any(caen_code.startswith(c[:2]) for c in p["target_caen"])
            is_turnover_match = turnover_ron >= p["min_turnover_ron"]
            
            if is_caen_match and is_turnover_match:
                matched_grants.append({
                    "program_id": p["program_id"],
                    "program_name": p["name"],
                    "eligible_grant_up_to": f"EUR {p['max_grant_eur']:,.0f}",
                    "required_co_financing": f"{p['co_financing_pct']}%",
                    "legal_basis": p["legal_basis"],
                    "eligibility_score": 9.5 if is_caen_match and is_turnover_match else 7.8,
                    "action_required": "Constituiti dosarul de finantare conform cerintelor din Ghid."
                })

        overall_score = 9.2 if len(matched_grants) > 0 else 5.0

        return {
            "company_profile": {
                "name": company_name,
                "cui": cui_fiscal,
                "caen": caen_code,
                "turnover_ron": turnover_ron,
                "employee_count": employee_count,
                "county": county
            },
            "qualification_status": "Eligibil pentru Fonduri Nerambursabile & Licitatii Strategice" if matched_grants else "Necesita Ajustare CAEN / Cifra Afaceri",
            "overall_eligibility_score": overall_score,
            "matched_programs_count": len(matched_grants),
            "matched_grants": matched_grants,
            "advisory_summary": (
                f"Compania {company_name} (CUI {cui_fiscal}) intruneste criteriile de eligibilitate pentru {len(matched_grants)} linii majore de finantare nerambursabila din Romania."
            )
        }
