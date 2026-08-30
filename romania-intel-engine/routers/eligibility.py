from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from addons.business_eligibility import BusinessEligibilityEngine
from security import require_auth

router = APIRouter(prefix="/api/v1/business-eligibility", tags=["Eligibility"])


class BusinessScanRequest(BaseModel):
    company_name: str
    cui_fiscal: str
    caen_code: str
    turnover_ron: float
    employee_count: int
    county: str
    # Mandatory exclusion grounds under Legea 98/2016 (Art. 164/165/167).
    # Optional and defaulting to False so existing callers are unaffected,
    # but exposed because a company that trips any of them is barred from
    # public procurement regardless of how well it scores financially.
    has_criminal_conviction: Optional[bool] = False
    has_unpaid_taxes: Optional[bool] = False
    is_insolvent: Optional[bool] = False
    has_professional_misconduct: Optional[bool] = False


@router.post("/evaluate")
def evaluate_company_eligibility(payload: BusinessScanRequest, _user: dict = Depends(require_auth)):
    return BusinessEligibilityEngine.evaluate_company(
        company_name=payload.company_name,
        cui_fiscal=payload.cui_fiscal,
        caen_code=payload.caen_code,
        turnover_ron=payload.turnover_ron,
        employee_count=payload.employee_count,
        county=payload.county,
        exclusion_flags={
            "has_criminal_conviction": bool(payload.has_criminal_conviction),
            "has_unpaid_taxes": bool(payload.has_unpaid_taxes),
            "is_insolvent": bool(payload.is_insolvent),
            "has_professional_misconduct": bool(payload.has_professional_misconduct),
        },
    )
