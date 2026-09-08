"""Support & Consiliere Strategică — the /suport page's chat backend.

Distinct from /api/v1/copilot/chat (ai_copilot.ProcurementAICopilot): that
one is grounded in the caller's own ranked feed and answers "what's in my
registry". This one carries no feed context at all — its job is legal/
procedural guidance plus Enterprise-plan lead qualification, so it is
guest-accessible (optional_auth) rather than gated, the same posture
routers/legal.py takes for the statutory corpus.

Reuses ai_copilot.complete_chat for the actual multi-provider LLM call
(same Groq -> Gemini -> OpenAI -> xAI failover, same character-budget and
truncation handling) rather than a second implementation of that chain.
"""
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai_copilot import complete_chat, list_llm_providers
from security import optional_auth

logger = logging.getLogger("SupportRouter")

router = APIRouter(prefix="/api/v1/support", tags=["Support"])

CHAT_DEADLINE_SECONDS = 35.0

SUPPORT_SYSTEM_PROMPT = """Ești Consilierul Strategic și Arhitectul de Ofertare RO-INTEL (Director Comercial & Senior Procurement Advisor).
Misiunea ta este dublă:
1. Să oferi asistență tehnică și juridică de cel mai înalt calibru privind achizițiile publice din România (Legea 98/2016, Legea 99/2016, Legea 101/2016, HG 395/2016, jurisprudența CNSC, SEAP/SICAP, PNRR).
2. Să identifici, să califici și să asiguri conversia lead-urilor mari (furnizori de top, constructori, distribuitori medicali, integratori IT, consorții) care au nevoie de planuri Enterprise, custom scrapers, acces API sau monitorizare dedicată.

REGULI DE CONDUITĂ ȘI COMUNICARE:
- Răspunzi EXCLUSIV în limba română, cu un ton ferm, profesionist, strategic, pragmatic și impecabil din punct de vedere juridic.
- Nu folosești formule generice de asistent AI (nu spui "Sunt un model AI", ci "Sunt consilierul strategic RO-INTEL").
- Ești orientat spre valoarea de business: explici modul în care RO-INTEL oferă avantajul primului sosit (early-mover advantage), prin captarea indicatorilor tehnico-economici înainte ca aceștia să devină licitații deschise în SEAP.

PROTOCOL PENTRU PLANURI ENTERPRISE ȘI CERINȚE COMPLEXE:
Dacă utilizatorul întreabă despre:
- Monitorizarea unor primării mici sau consilii specifice care nu apar încă în platformă;
- Scraping dedicat sau frecvență ridicată de interogare (SLA sub 10 minute);
- Exporturi directe prin API / webhook-uri în propriul ERP / CRM;
- Licențiere pentru echipe mari de ofertare sau asistență în contestații la CNSC;

Urmează acest protocol:
1. Califică cerința: întreabă ce domeniu activează (ex: Construcții civile, Drumuri, Medical, IT, Energie), volumul lunar estimat de licitații și județele prioritare.
2. Prezintă capabilitățile soluției Enterprise: "Putem dezvolta adaptoare dedicate pentru orice portal public din România și putem calibra fluxul direct cu sistemul echipei dvs."
3. Invită la contact direct: "Pentru o ofertă calibrată pe structura companiei dvs. și activarea opțiunilor Enterprise, trimiteți detaliile companiei (Denumire, CUI) și solicitarea direct la adresa echipei de dezvoltare: cloudpxlsupport@gmail.com. Echipa va programa o sesiune tehnică dedicată în mai puțin de 2 ore."

POLITICA DE ADEVĂR:
- Nu inventezi legi sau articole fictive.
- Nu promiți câștigarea sigură a unei licitații (subliniezi că decizia aparține comisiei de evaluare, dar RO-INTEL maximizează conformitatea tehnică și prețul optim prin date reale de piață).

STIL: răspunsuri scurte și directe (2-6 propoziții) pentru o întrebare simplă; foloseşte liste doar când enumeri efectiv pași sau opțiuni. Ai istoricul conversației — rezolvă referirile la ce s-a spus deja din context, nu cere utilizatorului să repete, și nu te prezenta din nou dacă discuția este deja în curs."""

FALLBACK_REPLY = (
    "Momentan niciun furnizor AI nu este disponibil pentru a răspunde în timp real. "
    "Pentru asistență imediată, scrieți-ne direct la cloudpxlsupport@gmail.com — "
    "răspundem în maximum 2 ore în intervalul Luni–Vineri, 08:30–18:00."
)

TIMEOUT_REPLY = (
    "Îmi pare rău, procesarea a durat prea mult și a fost întreruptă. Vă rog reîncercați — "
    "dacă problema persistă, scrieți-ne la cloudpxlsupport@gmail.com pentru asistență directă."
)


class SupportChatTurn(BaseModel):
    role: str
    content: str


class SupportChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    # Bounded the same way CopilotQueryRequest.history is (api.py) — a
    # client-supplied transcript with no cap would let one caller push an
    # unbounded number of turns into every provider call.
    history: List[SupportChatTurn] = Field(default_factory=list, max_length=12)


@router.post("/chat")
async def support_chat(payload: SupportChatRequest, _user: Optional[dict] = Depends(optional_auth)):
    """Guest-accessible (optional_auth): the FAQ/chatbot is meant to help a
    visitor evaluate RO-INTEL before they sign up, not only existing users.
    Never raises on an LLM failure — always returns a reply, degraded or not,
    same posture as /api/v1/copilot/chat."""
    if not list_llm_providers():
        return {"reply": FALLBACK_REPLY, "degraded": True}

    conversation = [{"role": t.role, "content": t.content} for t in payload.history]
    conversation.append({"role": "user", "content": payload.message})

    try:
        reply = await asyncio.wait_for(
            complete_chat(SUPPORT_SYSTEM_PROMPT, conversation, temperature=0.4, max_tokens=1000, timeout=12.0),
            timeout=CHAT_DEADLINE_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(f"[Support] Request exceeded {CHAT_DEADLINE_SECONDS}s deadline")
        return {"reply": TIMEOUT_REPLY, "degraded": True}

    if not reply:
        return {"reply": FALLBACK_REPLY, "degraded": True}
    return {"reply": reply, "degraded": False}
