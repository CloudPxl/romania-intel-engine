"""Can this company actually bid for this contract — and if not alone, how?

`business_eligibility.py` answers a different question (which grant
programmes a company's CAEN and size fit). This answers the procurement
one: given a real company profile from ANAF and a real contract value,
which of the three legitimate participation routes are open, and what
specifically blocks the others.

Three things make this worth its own module rather than more branches in
the eligibility engine:

**It is grounded, article by article.** Every ceiling and every route
below quotes a provision from `legal_kb` — the consolidated texts ingested
from legislatie.just.ro — rather than a remembered rule. Two corrections
that grounding produced, both of which were in the brief this implements:

* The "annual turnover requirement may not exceed twice the estimated
  value" ceiling is **art. 175 alin. (2) lit. a)**, not art. 172. Art. 172
  is the general list of the three permitted capacity criteria; art. 175
  is the economic-and-financial one that carries the arithmetic. Art. 175
  alin. (3) then allows the authority to exceed it in duly justified
  cases, which is why a requirement above the ceiling is reported here as
  *challengeable*, never as automatically unlawful.
* Art. 172 alin. (4) says the authority may **not** set capacity
  requirements for proposed subcontractors at all. That is what makes the
  subcontractor route real rather than a consolation prize, and it is the
  provision the pivot below is built on.

**It reasons about the requirement, not just the company.** The figure
that decides Scenario A is the turnover the authority *demands*, which
lives in the fișa de date and cannot be scraped from anywhere. So it is an
optional input: supplied, it is checked against both the company and the
legal ceiling; absent, the analysis says exactly what it could not decide
instead of inventing a threshold.

**It never guesses at the exclusion grounds it cannot see.** ANAF tells us
one thing bearing on art. 164/165/167 — whether the taxpayer is declared
inactive. Insolvency, criminal convictions and outstanding tax debt are
not in any free public API, so they are reported as *unverified*, with the
document that proves each one named, rather than silently passed.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("QualificationScenarios")

# Art. 175 alin. (2) lit. a): the minimum annual turnover an authority may
# require "nu trebuie să depășească de două ori valoarea estimată a
# contractului". Named as a constant so the multiplier is inspectable and
# so the article it comes from travels with it everywhere it is used.
MAX_TURNOVER_REQUIREMENT_MULTIPLIER = 2.0
TURNOVER_CEILING_ARTICLE = "L98/2016:175"

# Legal anchors for each participation route, resolved to real text at
# response time. Keeping them as keys rather than prose means a wrong
# mapping shows the reader what the article actually says.
ROUTE_ARTICLES = {
    "leader": ["L98/2016:172", "L98/2016:175"],
    "subcontractor": ["L98/2016:172", "L98/2016:186"],
    "joint_venture": ["L98/2016:185"],
    "third_party_support": ["L98/2016:182"],
}

# What ANAF can and cannot answer about the exclusion grounds. Split
# explicitly, because "we checked and it is fine" and "we could not check"
# must never render the same way on an eligibility report.
EXCLUSION_CHECKS = [
    {
        "ground": "Obligații fiscale restante",
        "article": "L98/2016:165",
        "verifiable_from_anaf": False,
        "evidence_document": "Certificat de atestare fiscală (ANAF) și certificat fiscal de la bugetul local",
    },
    {
        "ground": "Contribuabil declarat inactiv",
        "article": "L98/2016:165",
        "verifiable_from_anaf": True,
        "evidence_document": "Registrul contribuabililor inactivi (ANAF) — verificat automat",
    },
    {
        "ground": "Condamnări penale ale societății sau ale administratorilor",
        "article": "L98/2016:164",
        "verifiable_from_anaf": False,
        "evidence_document": "Cazier judiciar al societății și al membrilor organului de administrare",
    },
    {
        "ground": "Insolvență, faliment sau lichidare",
        "article": "L98/2016:167",
        "verifiable_from_anaf": False,
        "evidence_document": "Certificat constatator ONRC (emis cu cel mult 30 de zile înainte)",
    },
    {
        "ground": "Conflict de interese",
        "article": "L98/2016:167",
        "verifiable_from_anaf": False,
        "evidence_document": "Declarație privind neîncadrarea în situațiile de conflict de interese",
    },
]


def _articles(keys: List[str], max_chars: int = 600) -> List[Dict[str, Any]]:
    """Resolves article keys to real quoted text, skipping repealed ones."""
    try:
        import legal_kb
    except Exception:  # pragma: no cover - legal_kb is always importable here
        return []
    out = []
    for key in keys:
        entry = legal_kb.cite_with_text(key, max_chars)
        if entry and not entry["repealed"]:
            out.append(entry)
    return out


def max_lawful_turnover_requirement(estimated_value_ron: float) -> Optional[float]:
    """The highest annual turnover an authority may demand for a contract
    of this value, under art. 175 alin. (2) lit. a).

    Returns None for an unpublished value: with no estimate there is no
    ceiling to compute, and returning 0.0 would read as "no turnover may be
    required", which is the opposite of the truth.
    """
    if not estimated_value_ron or estimated_value_ron <= 0:
        return None
    return round(estimated_value_ron * MAX_TURNOVER_REQUIREMENT_MULTIPLIER, 2)


def _scenario_a(
    turnover: Optional[float],
    estimated_value: float,
    required_turnover: Optional[float],
    is_inactive: bool,
) -> Dict[str, Any]:
    """Independent leader: bid alone, satisfy the criteria alone."""
    ceiling = max_lawful_turnover_requirement(estimated_value)
    findings: List[str] = []
    blockers: List[str] = []

    if is_inactive:
        blockers.append(
            "Societatea este declarată inactivă fiscal de ANAF. Aceasta este o situație de "
            "excludere (art. 165) și blochează participarea în orice calitate până la reactivare."
        )

    if turnover is None:
        status = "unknown"
        findings.append(
            "Cifra de afaceri nu a putut fi citită din bilanțurile depuse la ANAF — "
            "nu se poate evalua capacitatea economică."
        )
    elif required_turnover is not None:
        # The real requirement is known, so this is a direct comparison
        # rather than an inference.
        if required_turnover > (ceiling or 0):
            findings.append(
                f"Cerința de cifră de afaceri din documentație ({required_turnover:,.0f} RON) "
                f"depășește plafonul de {MAX_TURNOVER_REQUIREMENT_MULTIPLIER:g}× valoarea estimată "
                f"({ceiling:,.0f} RON) prevăzut la art. 175 alin. (2) lit. a). "
                "Poate fi contestată printr-o solicitare de clarificări, cu excepția cazului în care "
                "autoritatea a motivat depășirea conform art. 175 alin. (3)."
            )
        if turnover >= required_turnover:
            status = "eligible"
            findings.append(
                f"Cifra de afaceri ({turnover:,.0f} RON) acoperă cerința documentației "
                f"({required_turnover:,.0f} RON)."
            )
        else:
            status = "blocked"
            blockers.append(
                f"Cifra de afaceri ({turnover:,.0f} RON) este sub cerința documentației "
                f"({required_turnover:,.0f} RON). Diferență: {required_turnover - turnover:,.0f} RON."
            )
    elif ceiling is None:
        status = "unknown"
        findings.append(
            "Valoarea estimată a contractului nu este publicată, deci nu se poate calcula "
            "nici plafonul legal, nici capacitatea necesară."
        )
    else:
        # No stated requirement: report against the legal ceiling, which is
        # the worst case the authority may lawfully impose, and say so.
        if turnover >= ceiling:
            status = "eligible"
            findings.append(
                f"Cifra de afaceri ({turnover:,.0f} RON) depășește plafonul maxim pe care "
                f"autoritatea îl poate impune legal ({ceiling:,.0f} RON), deci acoperă orice "
                "cerință de cifră de afaceri conformă cu art. 175 alin. (2) lit. a)."
            )
        elif turnover >= estimated_value:
            status = "likely_eligible"
            findings.append(
                f"Cifra de afaceri ({turnover:,.0f} RON) depășește valoarea estimată "
                f"({estimated_value:,.0f} RON), dar nu și plafonul maxim de {ceiling:,.0f} RON. "
                "Verificați cerința exactă din fișa de date."
            )
        else:
            status = "at_risk"
            findings.append(
                f"Cifra de afaceri ({turnover:,.0f} RON) este sub valoarea estimată a contractului "
                f"({estimated_value:,.0f} RON). Multe documentații cer cel puțin valoarea estimată."
            )

    if blockers:
        status = "blocked"

    return {
        "scenario": "A",
        "route": "leader",
        "label": "Ofertant individual",
        "status": status,
        "max_lawful_turnover_requirement_ron": ceiling,
        "required_turnover_ron": required_turnover,
        "company_turnover_ron": turnover,
        "findings": findings,
        "blockers": blockers,
        "legal_basis": _articles(ROUTE_ARTICLES["leader"]),
    }


def _scenario_b(
    turnover: Optional[float],
    estimated_value: float,
    leader_status: str,
) -> Dict[str, Any]:
    """Subcontractor / joint venture / third-party support.

    Offered whatever the leader verdict is — a company that qualifies alone
    may still prefer to take one part of a large contract — but it is the
    *answer* when the leader route is blocked, which is why it carries the
    share arithmetic.
    """
    findings: List[str] = []
    routes: List[Dict[str, Any]] = []

    # Art. 172 alin. (4): no capacity requirements may be set for proposed
    # subcontractors. That is the whole basis of this route.
    routes.append({
        "route": "subcontractor",
        "label": "Subcontractant",
        "note": (
            "Autoritatea contractantă nu poate stabili cerințe de capacitate pentru "
            "subcontractanții propuși (art. 172 alin. (4)) — cifra de afaceri a "
            "subcontractantului nu se compară cu pragul procedurii. Se ia în calcul doar "
            "capacitatea tehnică pentru partea efectiv subcontractată."
        ),
        "legal_basis": _articles(ROUTE_ARTICLES["subcontractor"]),
    })

    routes.append({
        "route": "joint_venture",
        "label": "Asociere (ofertant asociat)",
        "note": (
            "Într-o asociere, criteriile economice și tehnice se demonstrează cumulat, prin "
            "resursele tuturor membrilor (art. 185 alin. (1)) — dar membrii răspund solidar "
            "pentru executarea întregului contract."
        ),
        "legal_basis": _articles(ROUTE_ARTICLES["joint_venture"]),
    })

    routes.append({
        "route": "third_party_support",
        "label": "Terț susținător",
        "note": (
            "Puteți invoca susținerea unui terț pentru criteriile economico-financiare și "
            "tehnice, indiferent de relația juridică cu acesta (art. 182 alin. (1)). Pentru "
            "experiența profesională, terțul trebuie să execute efectiv partea respectivă."
        ),
        "legal_basis": _articles(ROUTE_ARTICLES["third_party_support"]),
    })

    # How much of the contract this company's own turnover comfortably
    # supports, as a share. Deliberately conservative and labelled as a
    # planning figure: there is no statutory formula here, and presenting
    # an arithmetic ratio as a legal entitlement would be exactly the kind
    # of invention the rest of this codebase removes.
    supportable_share_pct = None
    if turnover and estimated_value > 0:
        supportable_share_pct = round(min(100.0, turnover / estimated_value * 100), 1)
        findings.append(
            f"Cifra de afaceri proprie ({turnover:,.0f} RON) reprezintă "
            f"{supportable_share_pct:.0f}% din valoarea estimată a contractului. Ca reper de "
            "planificare, aceasta este partea pe care o puteți susține din resurse proprii; "
            "nu este un procent prevăzut de lege."
        )

    if leader_status in ("blocked", "at_risk"):
        findings.append(
            "Traseul de ofertant individual este blocat sau riscant — asocierea sau "
            "subcontractarea sunt căile realiste de participare la această procedură."
        )

    return {
        "scenario": "B",
        "label": "Participare în asociere sau ca subcontractant",
        "status": "available",
        "supportable_share_pct": supportable_share_pct,
        "routes": routes,
        "findings": findings,
    }


def _exclusion_review(is_inactive: bool, company: Dict[str, Any]) -> Dict[str, Any]:
    """Art. 164/165/167, separating what was checked from what was not."""
    checked: List[Dict[str, Any]] = []
    for item in EXCLUSION_CHECKS:
        entry = {
            "ground": item["ground"],
            "citation": (_articles([item["article"]], 320) or [{}])[0].get("citation"),
            "evidence_document": item["evidence_document"],
        }
        if item["verifiable_from_anaf"]:
            entry["status"] = "fail" if is_inactive else "pass"
            entry["detail"] = (
                f"ANAF a declarat societatea inactivă la {company.get('inactivation_date') or 'dată nespecificată'}."
                if is_inactive
                else "Societatea nu figurează în registrul contribuabililor inactivi."
            )
        else:
            # The honest half. These cannot be answered from any free
            # public API, and reporting them as "pass" would be a
            # fabricated clearance on a legally consequential question.
            entry["status"] = "unverified"
            entry["detail"] = "Nu poate fi verificat automat — se dovedește cu documentul indicat."
        checked.append(entry)

    return {
        "grounds": checked,
        "verified_count": sum(1 for c in checked if c["status"] in ("pass", "fail")),
        "unverified_count": sum(1 for c in checked if c["status"] == "unverified"),
        "note": (
            "Verificăm automat doar starea de contribuabil inactiv, singura publicată de ANAF. "
            "Restul motivelor de excludere se dovedesc cu documentele indicate — declarația pe "
            "proprie răspundere din DUAE nu le înlocuiește la momentul atribuirii."
        ),
    }


def evaluate_qualification(
    verification: Dict[str, Any],
    estimated_value_ron: float,
    required_turnover_ron: Optional[float] = None,
) -> Dict[str, Any]:
    """Entry point. `verification` is a company_registry.verify_company()
    result — real ANAF data, not user-declared figures.

    Returns every scenario every time, each with its own status, so the
    caller renders a route map rather than a single pass/fail. A company
    that cannot lead can almost always still participate, and a report that
    only says "ineligible" hides that.
    """
    company = (verification or {}).get("company") or {}
    financials = (verification or {}).get("financials") or {}

    turnover = financials.get("turnover_ron") if financials.get("found") else None
    employees = financials.get("employee_count") if financials.get("found") else None
    is_inactive = bool(company.get("is_inactive_taxpayer"))

    scenario_a = _scenario_a(turnover, estimated_value_ron or 0.0, required_turnover_ron, is_inactive)
    scenario_b = _scenario_b(turnover, estimated_value_ron or 0.0, scenario_a["status"])

    if is_inactive:
        recommendation = (
            "Blocant: societatea este inactivă fiscal. Reactivarea la ANAF este pasul obligatoriu "
            "înainte de orice participare, în orice calitate."
        )
    elif scenario_a["status"] in ("eligible", "likely_eligible"):
        recommendation = (
            "Puteți oferta individual. Confirmați cerința exactă de cifră de afaceri din fișa de "
            "date și pregătiți documentele de excludere neverificabile automat."
        )
    elif scenario_a["status"] == "unknown":
        recommendation = (
            "Datele financiare sau valoarea estimată lipsesc — completați-le pentru o evaluare "
            "concludentă. Traseele de asociere rămân oricum disponibile."
        )
    else:
        recommendation = (
            "Capacitatea economică proprie nu susține rolul de lider pentru această valoare. "
            "Asocierea (art. 185) cumulează resursele, iar ca subcontractant nu vi se poate impune "
            "un prag de cifră de afaceri (art. 172 alin. (4))."
        )

    return {
        "company": {
            "cui": company.get("cui"),
            "name": company.get("company_name"),
            "county": company.get("county"),
            "caen_code": company.get("caen_code"),
            "turnover_ron": turnover,
            "employee_count": employees,
            "fiscal_year": financials.get("fiscal_year"),
            "is_inactive_taxpayer": is_inactive,
            "vat_registered": company.get("vat_registered"),
            "cash_vat_scheme": company.get("cash_vat_scheme"),
        },
        "contract": {
            "estimated_value_ron": estimated_value_ron or None,
            "max_lawful_turnover_requirement_ron": max_lawful_turnover_requirement(estimated_value_ron or 0.0),
            "ceiling_basis": (_articles([TURNOVER_CEILING_ARTICLE], 700) or [{}])[0].get("citation"),
        },
        "scenario_a_leader": scenario_a,
        "scenario_b_partnership": scenario_b,
        "exclusion_review": _exclusion_review(is_inactive, company),
        "recommendation": recommendation,
        "data_sources": (verification or {}).get("sources", []),
        "method_note": (
            "Datele companiei provin din registrele publice ANAF, nu din declarațiile "
            "utilizatorului. Pragurile citate sunt preluate din textele consolidate publicate pe "
            "legislatie.just.ro. Cerința reală de cifră de afaceri se află în fișa de date a "
            "procedurii și trebuie confirmată acolo."
        ),
    }
