from fastapi import APIRouter
from pydantic import BaseModel

from addons.business_eligibility import BusinessEligibilityEngine

router = APIRouter(prefix="/api/v1/business-eligibility", tags=["Eligibility"])

class BusinessScanRequest(BaseModel):
    company_name: str
    cui_fiscal: str
    caen_code: str
    turnover_ron: float
    employee_count: int
    county: str

@router.post("/evaluate")
def evaluate_company_eligibility(payload: BusinessScanRequest):
    return BusinessEligibilityEngine.evaluate_company(
        payload.company_name, payload.cui_fiscal, payload.caen_code, payload.turnover_ron, payload.employee_count, payload.county
    )
