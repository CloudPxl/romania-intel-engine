import io
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from addons.dossier_generator import TechnicalDossierGenerator
from addons.foia_generator import LegalClarificationGenerator
from addons.docx_export import render_docx
from security import require_auth

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
    # When true and an LLM provider is configured (ai_copilot.list_llm_providers),
    # the methodology and risk-management sections are expanded into
    # multi-paragraph, tender-specific text. Defaults to off since it adds
    # a multi-second LLM round trip; the template output is already a
    # complete document without it.
    use_ai_expansion: bool = False
    # Free-text excerpt from the caiet de sarcini, used only to make the
    # AI expansion specific to this tender. Ignored if use_ai_expansion is False.
    caiet_text: Optional[str] = None


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
    use_ai_expansion: bool = False
    caiet_text: Optional[str] = None


@router.post("/generate-technical-proposal")
async def generate_technical_proposal(payload: TechnicalProposalRequest, _user: dict = Depends(require_auth)):
    draft = TechnicalDossierGenerator.generate_draft(
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
    if payload.use_ai_expansion:
        draft = await TechnicalDossierGenerator.expand_with_ai(draft, caiet_text=payload.caiet_text)
    return draft


@router.post("/generate-clarification")
async def generate_clarification_letter(payload: ClarificationLetterRequest, _user: dict = Depends(require_auth)):
    draft = LegalClarificationGenerator.generate_clarification_letter(
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
    if payload.use_ai_expansion:
        draft = await LegalClarificationGenerator.expand_with_ai(
            draft, clarification_points=payload.clarification_points, caiet_text=payload.caiet_text,
        )
    return draft


def _filename_slug(text: str, fallback: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in (text or fallback))[:60].strip("_")
    return slug or fallback


@router.post("/export-dossier-docx")
async def export_dossier_docx(payload: TechnicalProposalRequest, _user: dict = Depends(require_auth)):
    draft = TechnicalDossierGenerator.generate_draft(
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
    if payload.use_ai_expansion:
        draft = await TechnicalDossierGenerator.expand_with_ai(draft, caiet_text=payload.caiet_text)

    docx_bytes = render_docx(
        doc_title="Propunere Tehnică",
        subtitle=draft["project_title"],
        company_name=draft["company_name"],
        authority_name=draft["authority_name"],
        sections=draft["structured_sections"],
        cui=draft.get("cui"),
        reference_id=draft.get("source_id"),
        compliance_rows=draft.get("compliance_rows"),
        disclaimer=draft.get("disclaimer"),
    )

    filename = f"propunere_tehnica_{_filename_slug(draft['project_title'], 'oferta')}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export-clarification-docx")
async def export_clarification_docx(payload: ClarificationLetterRequest, _user: dict = Depends(require_auth)):
    draft = LegalClarificationGenerator.generate_clarification_letter(
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
    if payload.use_ai_expansion:
        draft = await LegalClarificationGenerator.expand_with_ai(
            draft, clarification_points=payload.clarification_points, caiet_text=payload.caiet_text,
        )

    doc_title = "Solicitare de Clarificări" if payload.request_type == "clarification" else "Solicitare Informații Publice"
    sections = [{"heading": "Conținutul solicitării", "paragraphs": draft["generated_letter"].split("\n\n")}]

    docx_bytes = render_docx(
        doc_title=doc_title,
        subtitle=payload.project_title,
        company_name=payload.company_name,
        authority_name=draft["recipient"],
        sections=sections,
        cui=payload.cui_fiscal,
        reference_id=draft.get("reference_id"),
        disclaimer=draft.get("disclaimer"),
        signatory_role="Reprezentant legal / Împuternicit",
    )

    filename = f"{payload.request_type}_{_filename_slug(payload.project_title, 'solicitare')}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
