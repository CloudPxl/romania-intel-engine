from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from addons.dossier_generator import TechnicalDossierGenerator
from addons.foia_generator import LegalClarificationGenerator

router = APIRouter(prefix="/api/v1/addons", tags=["Document Drafting"])


class TechnicalProposalRequest(BaseModel):
    project_title: str
    authority_name: str
    county: str
    category: str
    company_name: str
    cui: str
    # Optional context. When supplied, the draft states the applicable
    # procedure type and echoes the procurement identifiers instead of
    # producing a generic document.
    estimated_value_ron: Optional[float] = None
    cpv_code: Optional[str] = None
    source_id: Optional[str] = None


class ClarificationLetterRequest(BaseModel):
    authority_name: str
    project_title: str
    source_id: str
    company_name: str
    cui_fiscal: str
    clarification_points: str
    # "clarification" = Legea 98/2016 request inside a live procedure;
    # "foia" = Legea 544/2001 public-information request. These are
    # different instruments with different deadlines and appeal paths.
    request_type: Literal["clarification", "foia"] = "clarification"
    contact_email: Optional[str] = None
    procedure_deadline: Optional[str] = None


@router.post("/generate-technical-proposal")
def generate_technical_proposal(payload: TechnicalProposalRequest):
    return TechnicalDossierGenerator.generate_draft(
        project_title=payload.project_title,
        authority_name=payload.authority_name,
        county=payload.county,
        category=payload.category,
        company_name=payload.company_name,
        cui=payload.cui,
        estimated_value_ron=payload.estimated_value_ron,
        cpv_code=payload.cpv_code,
        source_id=payload.source_id,
    )


@router.post("/generate-clarification")
def generate_clarification_letter(payload: ClarificationLetterRequest):
    return LegalClarificationGenerator.generate_clarification_letter(
        authority_name=payload.authority_name,
        project_title=payload.project_title,
        source_id=payload.source_id,
        company_name=payload.company_name,
        cui_fiscal=payload.cui_fiscal,
        clarification_points=payload.clarification_points,
        request_type=payload.request_type,
        contact_email=payload.contact_email,
        procedure_deadline=payload.procedure_deadline,
    )
