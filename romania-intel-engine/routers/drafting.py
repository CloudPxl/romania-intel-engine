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


# ---------------------------------------------------------------------------
# Which legal instrument the timeline actually allows.
#
# The brief this implements asked for a "Notificare Prealabilă under Art. 6-8
# Legea 101/2016" for the urgent case. That instrument no longer exists:
# **art. 6 and art. 7 of Legea 101/2016 were both repealed** by OUG 45/2018,
# and a full-text search of the consolidated law returns no "notificare
# prealabilă" at all. The mandatory pre-notification step was abolished in
# 2018 — a bidder who spends two of their ten days sending one is not
# preserving a right, they are burning the contestation deadline.
#
# What is actually in force, and what this selects between:
#   * before the deadline, with time to spare — solicitare de clarificări
#     (art. 160-161 Legea 98/2016), which is free and often sufficient;
#   * when the deadline is close — contestație to the CNSC or the court
#     (art. 8 Legea 101/2016), 10 days above the JOUE publication
#     thresholds and 7 days below them, counted per art. 5 from the day
#     after you learned of the act.
# ---------------------------------------------------------------------------

CLARIFICATION_COMFORTABLE_DAYS = 10


class LegalInstrumentRequest(BaseModel):
    project_title: str
    days_until_deadline: int
    # Above the JOUE publication thresholds the contestation window is 10
    # days; below it is 7. The caller knows which applies to their
    # procedure; defaulting to the shorter one is the safe direction to be
    # wrong in.
    above_eu_thresholds: Optional[bool] = False
    issue_summary: Optional[str] = None


@router.post("/select-legal-instrument")
async def select_legal_instrument(
    payload: LegalInstrumentRequest, _user: dict = Depends(require_auth)
):
    """Names the right instrument for the time actually left, with the real
    deadline attached."""
    import legal_kb

    days = payload.days_until_deadline
    contest_window = 10 if payload.above_eu_thresholds else 7

    if days > CLARIFICATION_COMFORTABLE_DAYS:
        instrument = {
            "instrument": "clarification_request",
            "label": "Solicitare de clarificări",
            "urgency": "normal",
            "rationale": (
                f"Mai sunt {days} zile până la termenul de depunere. Solicitarea de clarificări este "
                "instrumentul potrivit: nu costă nimic, obligă autoritatea să răspundă și rezolvă "
                "majoritatea cerințelor restrictive fără contestație."
            ),
            "endpoint": "/api/v1/drafting/generate-clarification",
            "legal_basis": legal_kb.topic("clarification_requests")["articles"],
        }
    else:
        instrument = {
            "instrument": "cnsc_contestation",
            "label": "Contestație la CNSC sau instanță",
            "urgency": "urgent",
            "rationale": (
                f"Au mai rămas {days} zile. O solicitare de clarificări nu mai suspendă nimic — "
                f"dacă vizați actul autorității, termenul de contestare este de {contest_window} zile "
                "de la luarea la cunoștință (art. 8 din Legea 101/2016), calculat din ziua următoare "
                "(art. 5). Consultați un specialist înainte de depunere."
            ),
            "contestation_window_days": contest_window,
            "legal_basis": legal_kb.topic("remedies")["articles"],
        }

    return {
        **instrument,
        "days_until_deadline": days,
        "project_title": payload.project_title,
        "issue_summary": payload.issue_summary,
        # Stated because it is the single most common piece of stale advice
        # in Romanian procurement guidance, and following it costs days a
        # bidder does not have.
        "repealed_instrument_notice": (
            "Notificarea prealabilă NU mai există: art. 6 și art. 7 din Legea nr. 101/2016 au fost "
            "abrogate prin OUG nr. 45/2018. Nu este un pas obligatoriu înainte de contestație și nu "
            "prelungește niciun termen. Ghidurile care o menționează sunt depășite."
        ),
        "disclaimer": (
            "Acesta este un instrument de orientare, nu asistență juridică. Termenele se calculează "
            "pe procedura concretă și se confirmă în documentația de atribuire."
        ),
    }
