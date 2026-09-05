from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from addons import company_registry, qualification_scenarios
from addons.business_eligibility import BusinessEligibilityEngine
from security import require_auth

router = APIRouter(prefix="/api/v1/business-eligibility", tags=["Eligibility"])


class CompanyLookupRequest(BaseModel):
    cui_fiscal: str
    # Optional: when supplied it is compared against the registry's own
    # name, which is how a CUI belonging to somebody else gets caught.
    company_name: Optional[str] = None


class QualificationRequest(BaseModel):
    cui_fiscal: str
    estimated_value_ron: float
    # The turnover the documentation actually demands. It lives in the fișa
    # de date and exists in no machine-readable source, so it is optional:
    # supplied, it is compared against both the company and the art. 175
    # alin. (2) lit. a) ceiling; absent, the analysis reports against the
    # ceiling and says which question it could not answer.
    required_turnover_ron: Optional[float] = None
    company_name: Optional[str] = None


class BusinessScanRequest(BaseModel):
    company_name: str
    cui_fiscal: str
    # All four were required and self-declared. They are now filled from
    # ANAF's register and the company's own filed balance sheet whenever
    # the CUI resolves, so they are optional: what the user types is a
    # fallback for the cases the registry cannot answer (a company too new
    # to have filed, or a legal form with no filing obligation).
    caen_code: Optional[str] = None
    turnover_ron: Optional[float] = None
    employee_count: Optional[int] = None
    county: Optional[str] = None
    # Set false to score strictly on what was typed, without contacting
    # ANAF — kept so the engine stays testable and usable offline.
    verify_with_registry: Optional[bool] = True
    # Mandatory exclusion grounds under Legea 98/2016 (Art. 164/165/167).
    # Optional and defaulting to False so existing callers are unaffected,
    # but exposed because a company that trips any of them is barred from
    # public procurement regardless of how well it scores financially.
    has_criminal_conviction: Optional[bool] = False
    has_unpaid_taxes: Optional[bool] = False
    is_insolvent: Optional[bool] = False
    has_professional_misconduct: Optional[bool] = False


@router.post("/verify-company")
async def verify_company_route(payload: CompanyLookupRequest, _user: dict = Depends(require_auth)):
    """Look the company up in the state's own registers, by CUI.

    This is the lookup behind "Verificarea profilului companiei": identity
    and CAEN from ANAF's taxpayer register, turnover and headcount from the
    balance sheet the company itself filed. Returns `verified: false` with
    a reason when ANAF does not know the code or cannot be reached — never
    a plausible-looking company it made up.
    """
    return await company_registry.verify_company(
        payload.cui_fiscal, declared_name=payload.company_name
    )


@router.post("/qualification-scenarios")
async def qualification_scenarios_route(
    payload: QualificationRequest, _user: dict = Depends(require_auth)
):
    """Which participation routes are open for THIS company on THIS contract.

    Distinct from /evaluate, which scores a company against grant
    programmes. This one answers the procurement question — can you bid
    alone, and if not, what does the law leave open — from the company's
    real ANAF profile rather than what was typed into a form, with every
    threshold quoted from the ingested consolidated texts.
    """
    verification = await company_registry.verify_company(
        payload.cui_fiscal, declared_name=payload.company_name
    )
    if not verification.get("found"):
        # No invented profile to reason over. The caller gets the lookup's
        # own reason rather than a scenario map built on nothing.
        return {
            "available": False,
            "reason": verification.get("reason") or "Compania nu a putut fi identificată la ANAF.",
            "verification": verification,
        }
    return {
        "available": True,
        "verification": verification,
        **qualification_scenarios.evaluate_qualification(
            verification,
            estimated_value_ron=payload.estimated_value_ron,
            required_turnover_ron=payload.required_turnover_ron,
        ),
    }


@router.post("/evaluate")
async def evaluate_company_eligibility(payload: BusinessScanRequest, _user: dict = Depends(require_auth)):
    """Grant/procurement eligibility, scored against verified facts.

    Every figure that drives the verdict — CAEN code, development region,
    IMM size class — is taken from the register rather than from the form
    whenever the CUI resolves. What the user typed is kept alongside it and
    any disagreement is reported: being told "the CAEN you entered is not
    the one ANAF has on file" is far more useful than a confident verdict
    computed from the wrong code.
    """
    verification: Optional[Dict[str, Any]] = None
    declared = {
        "caen_code": payload.caen_code,
        "turnover_ron": payload.turnover_ron,
        "employee_count": payload.employee_count,
        "county": payload.county,
    }
    effective = dict(declared)
    discrepancies = []
    exclusion_flags = {
        "has_criminal_conviction": bool(payload.has_criminal_conviction),
        "has_unpaid_taxes": bool(payload.has_unpaid_taxes),
        "is_insolvent": bool(payload.is_insolvent),
        "has_professional_misconduct": bool(payload.has_professional_misconduct),
    }

    if payload.verify_with_registry:
        verification = await company_registry.verify_company(
            payload.cui_fiscal, declared_name=payload.company_name
        )
        if verification.get("verified"):
            company = verification.get("company") or {}
            financials = verification.get("financials") or {}

            for field, registry_value in (
                ("caen_code", company.get("caen_code")),
                ("county", company.get("county")),
                ("turnover_ron", financials.get("turnover_ron") if financials.get("found") else None),
                ("employee_count", financials.get("employee_count") if financials.get("found") else None),
            ):
                if registry_value in (None, ""):
                    continue
                typed = declared.get(field)
                effective[field] = registry_value
                if typed not in (None, "") and str(typed).strip().lower() != str(registry_value).strip().lower():
                    discrepancies.append({
                        "field": field,
                        "declared": typed,
                        "registry": registry_value,
                        "note": "S-a folosit valoarea din registrul oficial, nu cea introdusă manual.",
                    })

            # An inactive taxpayer cannot truthfully certify the tax
            # obligation of Art. 165 — established from the register here
            # rather than left to a self-declaration checkbox.
            if company.get("is_inactive_taxpayer"):
                exclusion_flags["has_unpaid_taxes"] = True

    result = BusinessEligibilityEngine.evaluate_company(
        company_name=payload.company_name,
        cui_fiscal=payload.cui_fiscal,
        caen_code=effective.get("caen_code") or "",
        turnover_ron=float(effective.get("turnover_ron") or 0.0),
        employee_count=int(effective.get("employee_count") or 0),
        county=effective.get("county") or "",
        exclusion_flags=exclusion_flags,
    )

    result["registry_verification"] = verification or {
        "verified": False,
        "skipped": True,
        "note": "Verificarea în registre a fost dezactivată pentru această cerere.",
    }
    result["declared_vs_registry"] = discrepancies
    result["data_provenance"] = (
        "Date verificate în registrele ANAF"
        if (verification or {}).get("verified")
        else "Date declarate de utilizator — neverificate în registre"
    )
    return result
