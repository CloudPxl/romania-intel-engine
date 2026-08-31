import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("EligibilityScanner")

# Approximate BNR reference rate. EU grant ceilings are denominated in EUR
# while Romanian company filings are in RON, so a conversion is
# unavoidable; it is surfaced in the response (`fx_rate_used`) rather than
# hidden, because a borderline IMM classification can hinge on it and the
# caller may need to re-run against the official rate for the filing date.
RON_PER_EUR = 4.98

# IMM thresholds — Legea 346/2004, transposing EU Recommendation
# 2003/361/EC. A company must satisfy the headcount ceiling AND one of the
# financial ceilings. Size class drives both grant ceilings and required
# co-financing across PNRR/POR calls, so it is computed rather than assumed.
IMM_CLASSES = [
    ("microintreprindere", 10, 2_000_000),
    ("intreprindere_mica", 50, 10_000_000),
    ("intreprindere_mijlocie", 250, 50_000_000),
]

# Romania's 8 development regions. Regional programmes (POR, run by the
# ADRs) are awarded per region, so a company's county determines which
# regional call it can even apply to — the previous version accepted a
# county argument and never used it.
COUNTY_TO_REGION = {
    "nord-est": ["bacau", "botosani", "iasi", "neamt", "suceava", "vaslui"],
    "sud-est": ["braila", "buzau", "constanta", "galati", "tulcea", "vrancea"],
    "sud-muntenia": ["arges", "calarasi", "dambovita", "giurgiu", "ialomita", "prahova", "teleorman"],
    "sud-vest-oltenia": ["dolj", "gorj", "mehedinti", "olt", "valcea"],
    "vest": ["arad", "caras-severin", "caras severin", "hunedoara", "timis"],
    "nord-vest": ["bihor", "bistrita-nasaud", "bistrita nasaud", "cluj", "maramures", "satu mare", "salaj"],
    "centru": ["alba", "brasov", "covasna", "harghita", "mures", "sibiu"],
    "bucuresti-ilfov": ["bucuresti", "ilfov"],
}

ELIGIBLE_GRANT_PROGRAMS = [
    {
        "program_id": "PNRR-C6-ENERGIE",
        "name": "PNRR C6: Eficiență Energetică & Producție Energie Regenerabilă",
        "target_caen": ["3511", "3512", "2711", "2712", "4222", "4321", "7112"],
        "min_turnover_ron": 1_500_000,
        "max_grant_eur": 15_000_000,
        "co_financing_pct": 35,
        "eligible_sizes": ["intreprindere_mica", "intreprindere_mijlocie", "intreprindere_mare"],
        "eligible_regions": None,  # national
        "legal_basis": "Ghidul Solicitantului MIPE / PNRR Componenta 6 - Energie",
    },
    {
        "program_id": "PNRR-C7-DIGITALIZARE",
        "name": "PNRR C7: Digitalizarea Avansată a IMM-urilor & Sectorului Medical",
        "target_caen": ["6201", "6202", "6209", "6311", "3313", "8610"],
        "min_turnover_ron": 500_000,
        "max_grant_eur": 3_000_000,
        "co_financing_pct": 10,
        "eligible_sizes": ["microintreprindere", "intreprindere_mica", "intreprindere_mijlocie"],
        "eligible_regions": None,
        "legal_basis": "Ordinul MCID / MIPE nr. 2026/C7",
    },
    {
        "program_id": "POR-INFRA-2026",
        "name": "Programul Regional: Competitivitate & Infrastructură Tehnologică",
        "target_caen": ["4120", "4211", "4213", "4299", "7111", "7112"],
        "min_turnover_ron": 2_500_000,
        "max_grant_eur": 5_000_000,
        "co_financing_pct": 25,
        "eligible_sizes": ["intreprindere_mica", "intreprindere_mijlocie"],
        # POR is not available in Bucuresti-Ilfov on the same terms as the
        # less-developed regions (state-aid intensity differs).
        "eligible_regions": [
            "nord-est", "sud-est", "sud-muntenia", "sud-vest-oltenia",
            "vest", "nord-vest", "centru",
        ],
        "legal_basis": "Ghid Specific Agențiile pentru Dezvoltare Regională (ADR)",
    },
]

# Mandatory exclusion grounds for public procurement — Legea 98/2016
# Art. 164 (criminal convictions), Art. 165 (unpaid taxes/contributions),
# Art. 167 (professional misconduct, insolvency, conflict of interest).
# Any of these disqualifies a bidder regardless of financial standing, so
# they gate the result rather than merely reducing a score.
EXCLUSION_GROUNDS = {
    "has_criminal_conviction": "Art. 164 Legea 98/2016 — condamnare definitivă pentru infracțiuni economice",
    "has_unpaid_taxes": "Art. 165 Legea 98/2016 — obligații fiscale restante la bugetul de stat/local",
    "is_insolvent": "Art. 167 alin. (1) lit. b) Legea 98/2016 — procedură de insolvență/faliment",
    "has_professional_misconduct": "Art. 167 alin. (1) lit. c) Legea 98/2016 — abatere profesională gravă",
}


def classify_caen_match(company_caen: str, target_caen: List[str]) -> Optional[Dict[str, Any]]:
    """CAEN codes are hierarchical: 4 digits = class, first 3 = group,
    first 2 = division. Matching at different depths is not equally strong,
    so the depth is reported instead of collapsing everything into one
    boolean the way the previous version did (it treated a bare 2-digit
    division overlap as equivalent to an exact code match)."""
    code = (company_caen or "").strip()
    if not code:
        return None
    if code in target_caen:
        return {"depth": "exact", "confidence": 1.0, "matched": code,
                "note": f"Cod CAEN {code} este listat explicit în ghid."}
    group = next((t for t in target_caen if len(code) >= 3 and t.startswith(code[:3])), None)
    if group:
        return {"depth": "grupa", "confidence": 0.7, "matched": group,
                "note": f"Cod CAEN {code} se află în aceeași grupă ({code[:3]}) cu {group} — de confirmat cu AM."}
    division = next((t for t in target_caen if len(code) >= 2 and t.startswith(code[:2])), None)
    if division:
        return {"depth": "diviziune", "confidence": 0.4, "matched": division,
                "note": f"Cod CAEN {code} este doar în aceeași diviziune ({code[:2]}) cu {division} — eligibilitate incertă."}
    return None


def classify_company_size(turnover_ron: float, employee_count: int) -> Dict[str, Any]:
    turnover_eur = (turnover_ron or 0.0) / RON_PER_EUR
    for label, max_employees, max_turnover_eur in IMM_CLASSES:
        if employee_count < max_employees and turnover_eur <= max_turnover_eur:
            return {
                "size_class": label,
                "turnover_eur": round(turnover_eur, 2),
                "is_imm": True,
            }
    return {"size_class": "intreprindere_mare", "turnover_eur": round(turnover_eur, 2), "is_imm": False}


def resolve_region(county: str) -> Optional[str]:
    from text_utils import normalize_county

    target = normalize_county(county)
    if not target:
        return None
    for region, counties in COUNTY_TO_REGION.items():
        if any(normalize_county(c) == target for c in counties):
            return region
    return None


def _remediation_for(
    caen_match: Optional[Dict[str, Any]],
    turnover_ok: bool,
    size_ok: bool,
    region_ok: bool,
    county: str,
    region: Optional[str],
) -> str:
    """One actionable instruction for the single hardest blocker.

    Ordered the same way `blockers` is built, so the advice always names
    the most fundamental obstacle. The region arm sits last deliberately:
    it must not shadow a CAEN/turnover/size failure, but it must be
    reachable — before it existed a company blocked *only* by region fell
    through to the IMM-classification message, which had nothing to do
    with the actual reason it was rejected.
    """
    if not caen_match:
        return "Verificați posibilitatea autorizării unui cod CAEN secundar eligibil."
    if not turnover_ok:
        return "Reevaluați după depunerea bilanțului următor."
    if not size_ok:
        return "Consultați AM pentru încadrarea corectă a întreprinderii."
    if not region_ok:
        # A county we cannot map to a development region is a data problem
        # on the request, not a substantive ineligibility — say so rather
        # than advising a relocation the company may not need.
        if region is None:
            return (
                f"Județul '{county or 'nespecificat'}' nu a putut fi încadrat într-una dintre cele 8 regiuni "
                "de dezvoltare; corectați județul sediului social și reluați verificarea."
            )
        return (
            f"Apelul este alocat regional, iar eligibilitatea se stabilește după locul de implementare, nu după "
            f"obiectul de activitate. Regiunea '{region}' nu este acoperită: verificați apelul lansat de ADR "
            f"pentru '{region}' sau, dacă proiectul o permite, implementarea printr-un punct de lucru autorizat "
            "într-o regiune eligibilă."
        )
    # Unreachable while this chain covers every condition that can add a
    # blocker; kept so a future blocker still returns advice rather than None.
    return "Consultați AM pentru condițiile specifice ale apelului."


class BusinessEligibilityEngine:
    @staticmethod
    def evaluate_company(
        company_name: str,
        cui_fiscal: str,
        caen_code: str,
        turnover_ron: float,
        employee_count: int,
        county: str,
        exclusion_flags: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        exclusion_flags = exclusion_flags or {}
        size = classify_company_size(turnover_ron, employee_count)
        region = resolve_region(county)

        triggered_exclusions = [
            reason for flag, reason in EXCLUSION_GROUNDS.items() if exclusion_flags.get(flag)
        ]

        matched_grants: List[Dict[str, Any]] = []
        near_misses: List[Dict[str, Any]] = []

        for program in ELIGIBLE_GRANT_PROGRAMS:
            caen_match = classify_caen_match(caen_code, program["target_caen"])
            turnover_ok = (turnover_ron or 0.0) >= program["min_turnover_ron"]
            size_ok = size["size_class"] in program["eligible_sizes"]
            region_ok = program["eligible_regions"] is None or (region in (program["eligible_regions"] or []))

            blockers: List[str] = []
            if not caen_match:
                blockers.append(f"Cod CAEN {caen_code} nu figurează în lista programului.")
            if not turnover_ok:
                blockers.append(
                    f"Cifra de afaceri {turnover_ron:,.0f} RON sub pragul de {program['min_turnover_ron']:,.0f} RON."
                )
            if not size_ok:
                blockers.append(f"Categoria '{size['size_class']}' nu este eligibilă pentru acest program.")
            if not region_ok:
                blockers.append(
                    f"Regiunea '{region or 'nedeterminată'}' nu este acoperită de acest apel regional."
                )

            if blockers:
                near_misses.append({
                    "program_id": program["program_id"],
                    "program_name": program["name"],
                    "blocking_reasons": blockers,
                    # What the company would have to change — actionable
                    # advice was entirely absent before; a failing company
                    # simply got a 5.0 and no explanation.
                    "remediation": _remediation_for(
                        caen_match, turnover_ok, size_ok, region_ok, county, region
                    ),
                })
                continue

            # Confidence is driven by how precisely the CAEN code matched,
            # so a company sitting in the right division but the wrong class
            # is not reported with the same certainty as an exact hit.
            score = round(6.5 + 3.5 * caen_match["confidence"], 1)
            matched_grants.append({
                "program_id": program["program_id"],
                "program_name": program["name"],
                "eligible_grant_up_to": f"EUR {program['max_grant_eur']:,.0f}",
                "required_co_financing": f"{program['co_financing_pct']}%",
                "estimated_own_contribution_ron": round(
                    program["max_grant_eur"] * RON_PER_EUR * program["co_financing_pct"] / 100, 2
                ),
                "legal_basis": program["legal_basis"],
                "caen_match": caen_match,
                "eligibility_score": score,
                "action_required": "Constituiți dosarul de finanțare conform cerințelor din Ghid.",
            })

        matched_grants.sort(key=lambda g: g["eligibility_score"], reverse=True)

        if triggered_exclusions:
            status = "Neeligibil — motive de excludere Legea 98/2016"
            overall = 0.0
        elif matched_grants:
            status = "Eligibil pentru Fonduri Nerambursabile & Licitații Strategice"
            overall = round(sum(g["eligibility_score"] for g in matched_grants) / len(matched_grants), 1)
        else:
            status = "Necesită Ajustare CAEN / Cifră de Afaceri"
            overall = 3.0

        return {
            "company_profile": {
                "name": company_name,
                "cui": cui_fiscal,
                "caen": caen_code,
                "turnover_ron": turnover_ron,
                "employee_count": employee_count,
                "county": county,
                "development_region": region,
                **size,
            },
            "fx_rate_used": RON_PER_EUR,
            "qualification_status": status,
            "overall_eligibility_score": overall,
            "exclusion_grounds": triggered_exclusions,
            "matched_programs_count": len(matched_grants),
            "matched_grants": matched_grants,
            "near_misses": near_misses,
            "advisory_summary": BusinessEligibilityEngine._summarize(
                company_name, cui_fiscal, size, region, matched_grants, triggered_exclusions
            ),
        }

    @staticmethod
    def _summarize(company_name, cui, size, region, matched, exclusions) -> str:
        if exclusions:
            return (
                f"{company_name} (CUI {cui}) nu poate participa la proceduri de achiziție publică "
                f"până la remedierea următoarelor motive de excludere: {'; '.join(exclusions)}."
            )
        if not matched:
            return (
                f"{company_name} (CUI {cui}), încadrată ca {size['size_class']} în regiunea "
                f"{region or 'nedeterminată'}, nu îndeplinește în prezent criteriile programelor analizate. "
                f"Consultați secțiunea 'near_misses' pentru condițiile care lipsesc."
            )
        return (
            f"{company_name} (CUI {cui}), încadrată ca {size['size_class']} "
            f"(cifră de afaceri ≈ EUR {size['turnover_eur']:,.0f}) în regiunea {region or 'nedeterminată'}, "
            f"întrunește criteriile pentru {len(matched)} linii de finanțare nerambursabilă."
        )
