import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from ai_copilot import complete_text, list_llm_providers

logger = logging.getLogger("FOIAGenerator")

# Legea nr. 544/2001 art. 7 alin. (1): 10 working days to answer, extendable
# to 30 working days for information requiring complex research (with the
# applicant notified within 10 days). Tracking both lets the letter state a
# concrete expected-response date instead of leaving the deadline vague.
FOIA_STANDARD_WORKING_DAYS = 10
FOIA_EXTENDED_WORKING_DAYS = 30


def add_working_days(start: date, working_days: int) -> date:
    """Romanian legal deadlines in Legea 544/2001 run in working days.
    Public holidays are not modelled here — only weekends — so the result
    is the earliest possible date and is labelled as such in the letter."""
    current = start
    remaining = working_days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


class LegalClarificationGenerator:
    """Drafts two distinct instruments that the previous version conflated.

    A *clarification request* under Legea 98/2016 is addressed to a
    contracting authority inside a live procedure and is answered through
    SEAP. A *Legea 544/2001 request* is a public-information request that
    any person can file, with its own statutory deadline and its own appeal
    path. The old template cited both laws in one letter and titled the
    result as though it were both, which is not a document either regime
    actually recognises.
    """

    @staticmethod
    def generate_clarification_letter(
        authority_name: str,
        project_title: str,
        source_id: str,
        company_name: str,
        cui_fiscal: str,
        clarification_points: str,
        request_type: str = "clarification",
        contact_email: Optional[str] = None,
        procedure_deadline: Optional[str] = None,
    ) -> Dict[str, Any]:
        today = date.today()
        today_str = today.strftime("%d.%m.%Y")
        points = LegalClarificationGenerator._format_points(clarification_points)

        if request_type == "foia":
            return LegalClarificationGenerator._build_foia(
                authority_name, project_title, source_id, company_name,
                cui_fiscal, points, today, today_str, contact_email,
            )
        return LegalClarificationGenerator._build_clarification(
            authority_name, project_title, source_id, company_name,
            cui_fiscal, points, today_str, contact_email, procedure_deadline,
        )

    @staticmethod
    def _format_points(clarification_points: str) -> str:
        """Accepts free text or newline-separated items and renders them as
        a numbered list, so the authority can answer point by point."""
        raw = [p.strip(" -•\t") for p in (clarification_points or "").splitlines()]
        items = [p for p in raw if p]
        if len(items) <= 1:
            return clarification_points.strip()
        return "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))

    @staticmethod
    def _build_clarification(
        authority_name, project_title, source_id, company_name,
        cui_fiscal, points, today_str, contact_email, procedure_deadline,
    ) -> Dict[str, Any]:
        deadline_note = (
            f"Vă rugăm să aveți în vedere că termenul-limită de depunere a ofertelor este {procedure_deadline}, "
            "solicitarea fiind formulată în termen util pentru a permite publicarea răspunsului."
            if procedure_deadline else
            "Solicitarea este formulată cu respectarea termenului prevăzut în fișa de date a achiziției."
        )

        letter = f"""Către: {authority_name}
În atenția: Compartimentului Achiziții Publice

Referință: {source_id}
Obiect: Solicitare de clarificări privind documentația de atribuire — „{project_title}”
Data: {today_str}

Stimată doamnă / Stimate domnule,

Subscrisa {company_name}, cu sediul social în România, înregistrată la Oficiul Registrului Comerțului,
având CUI {cui_fiscal}, în calitate de operator economic interesat de participarea la procedura
menționată în referință,

În temeiul art. 160 și art. 161 din Legea nr. 98/2016 privind achizițiile publice, precum și al
prevederilor HG nr. 395/2016, formulăm prezenta

SOLICITARE DE CLARIFICĂRI

cu privire la documentația de atribuire, după cum urmează:

{points}

Solicitarea este întemeiată pe principiile prevăzute la art. 2 alin. (2) din Legea nr. 98/2016 —
nediscriminarea, tratamentul egal, recunoașterea reciprocă, transparența, proporționalitatea și
asumarea răspunderii — și urmărește asigurarea unui mediu concurențial real.

{deadline_note}

Conform art. 161 din Legea nr. 98/2016, vă rugăm să publicați răspunsul în SEAP, atașat anunțului
de participare, astfel încât acesta să fie accesibil tuturor operatorilor economici interesați.

Cu deosebită considerație,

{company_name}
CUI: {cui_fiscal}
{f"E-mail de contact: {contact_email}" if contact_email else "E-mail de contact: [a se completa]"}
"""

        return {
            "document_type": "Solicitare de clarificări — Legea nr. 98/2016 (art. 160-161)",
            "request_type": "clarification",
            "recipient": authority_name,
            "reference_id": source_id,
            "legal_basis": ["Legea nr. 98/2016, art. 160-161", "Legea nr. 98/2016, art. 2 alin. (2)", "HG nr. 395/2016"],
            "generated_letter": letter.strip(),
            "disclaimer": (
                "Schiță generată automat. Verificați termenul exact de depunere a solicitărilor din fișa "
                "de date a achiziției înainte de transmitere."
            ),
        }

    @staticmethod
    def _build_foia(
        authority_name, project_title, source_id, company_name,
        cui_fiscal, points, today, today_str, contact_email,
    ) -> Dict[str, Any]:
        standard_due = add_working_days(today, FOIA_STANDARD_WORKING_DAYS)
        extended_due = add_working_days(today, FOIA_EXTENDED_WORKING_DAYS)

        letter = f"""Către: {authority_name}
În atenția: Persoanei responsabile cu aplicarea Legii nr. 544/2001

Referință: {source_id}
Obiect: Solicitare de informații de interes public — „{project_title}”
Data: {today_str}

Stimată doamnă / Stimate domnule,

Subscrisa {company_name}, având CUI {cui_fiscal}, în temeiul art. 6 din Legea nr. 544/2001 privind
liberul acces la informațiile de interes public, cu modificările și completările ulterioare, și al
Normelor metodologice aprobate prin HG nr. 123/2002, solicităm comunicarea următoarelor informații
de interes public:

{points}

Menționăm că informațiile solicitate privesc utilizarea banilor publici și nu se încadrează în
categoriile exceptate de la accesul liber prevăzute la art. 12 din Legea nr. 544/2001.

Conform art. 7 alin. (1) din Legea nr. 544/2001, răspunsul urmează a fi comunicat în termen de
10 zile lucrătoare (estimat: {standard_due.strftime("%d.%m.%Y")}), respectiv în cel mult 30 de zile
lucrătoare (estimat: {extended_due.strftime("%d.%m.%Y")}) în situația în care informațiile solicitate
necesită o analiză mai amplă, caz în care vă rugăm să ne notificați în termen de 10 zile.

Solicităm comunicarea răspunsului în format electronic, la adresa de e-mail indicată mai jos.

Cu deosebită considerație,

{company_name}
CUI: {cui_fiscal}
{f"E-mail de contact: {contact_email}" if contact_email else "E-mail de contact: [a se completa]"}
"""

        return {
            "document_type": "Solicitare informații de interes public — Legea nr. 544/2001",
            "request_type": "foia",
            "recipient": authority_name,
            "reference_id": source_id,
            "legal_basis": ["Legea nr. 544/2001, art. 6-7", "HG nr. 123/2002"],
            "expected_response_by": standard_due.isoformat(),
            "extended_response_by": extended_due.isoformat(),
            "generated_letter": letter.strip(),
            "disclaimer": (
                "Termenele calculate exclud doar sfârșiturile de săptămână, nu și sărbătorile legale, "
                "deci reprezintă cea mai devreme dată posibilă. În caz de refuz sau lipsă a răspunsului, "
                "reclamația administrativă se depune în 30 de zile, iar acțiunea în contencios "
                "administrativ în 30 de zile de la expirarea termenului (art. 21-22 din Legea nr. 544/2001)."
            ),
        }

    @staticmethod
    async def expand_with_ai(
        draft: Dict[str, Any],
        clarification_points: str,
        caiet_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Optionally inserts an LLM-drafted legal/technical argumentation
        paragraph into an already-generated letter, justifying *why* each
        clarification point is being raised (tying it to the specific
        wording of the caiet de sarcini when supplied) rather than leaving
        the points as a bare numbered list. Additive and best-effort: the
        letter generated by generate_clarification_letter is a complete,
        legally valid instrument on its own — a missing or failed LLM call
        must leave it exactly as it was, never partially modified.
        """
        if not list_llm_providers():
            return draft

        context = f"Punctele de clarificare formulate:\n{clarification_points}\n"
        if caiet_text:
            context += f"\nExtras din caietul de sarcini / documentația de atribuire:\n{caiet_text[:6000]}\n"

        is_foia = draft.get("request_type") == "foia"
        system_prompt = (
            "Ești un expert în achiziții publice din România. Redactezi un paragraf de fundamentare "
            "(argumentare juridică și tehnică, 2-4 paragrafe) care justifică de ce solicitantul are dreptul "
            "și interesul legitim de a ridica exact aceste puncte de clarificare, raportându-te concret la "
            "textul documentației furnizate atunci când este disponibil. Nu inventa articole de lege sau "
            "fapte care nu rezultă din context. Scrii exclusiv în limba română, ton formal, fără titlu — "
            "doar paragrafele de conținut, gata de inserat într-o scrisoare oficială."
            + (" Nu folosi terminologie specifică Legii 98/2016 (proceduri de atribuire) — aceasta este o "
               "solicitare distinctă în temeiul Legii 544/2001 privind liberul acces la informații de interes public."
               if is_foia else "")
        )
        completion = await complete_text(system_prompt, context, temperature=0.4, max_tokens=900, timeout=35.0)
        if not completion:
            return draft

        anchor = "Cu deosebită considerație,"
        letter = draft["generated_letter"]
        if anchor in letter:
            insertion = f"\nFundamentare:\n{completion.strip()}\n\n"
            draft["generated_letter"] = letter.replace(anchor, insertion + anchor, 1)
            draft["ai_expanded"] = True
        return draft
