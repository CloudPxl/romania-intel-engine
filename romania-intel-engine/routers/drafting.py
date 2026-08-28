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

class ClarificationLetterRequest(BaseModel):
    authority_name: str
    project_title: str
    source_id: str
    company_name: str
    cui_fiscal: str
    clarification_points: str

@router.post("/generate-technical-proposal")
def generate_technical_proposal(payload: TechnicalProposalRequest):
    return TechnicalDossierGenerator.generate_draft(
        payload.project_title, payload.authority_name, payload.county, payload.category, payload.company_name, payload.cui
    )

@router.post("/generate-clarification")
def generate_clarification_letter(payload: ClarificationLetterRequest):
    return LegalClarificationGenerator.generate_clarification_letter(
        payload.authority_name, payload.project_title, payload.source_id, payload.company_name, payload.cui_fiscal, payload.clarification_points
    )
