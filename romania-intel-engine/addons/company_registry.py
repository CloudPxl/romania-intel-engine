"""Live company verification against Romania's own state registries.

`business_eligibility.py` used to take every fact about the company from
whoever filled in the form — CAEN code, county, turnover, headcount — and
then compute an eligibility verdict from it. That verdict was only ever as
true as the self-declaration behind it, and the two facts that most often
decide it (IMM size class and the CAEN code a programme targets) are
exactly the two a hopeful applicant is most likely to get wrong.

Everything here reads the authoritative source instead:

* **ANAF's public VAT-payer API** (`webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva`)
  — the tax authority's own record: legal name, trade-registry number,
  main CAEN code, registered office (county), legal form, registration
  date, VAT status, and the *inactive taxpayer* flag. No key, no auth, no
  quota published; verified live against real CUIs before this shipped.
* **ANAF's public balance-sheet API** (`webservicesp.anaf.ro/bilant`) —
  the financial statements the company actually filed: net turnover and
  average headcount, which are precisely the two figures Legea 346/2004
  keys the IMM classification on.

Both are the state's own data about the company, which is what makes a
verified answer possible at all — no commercial aggregator is being
scraped, no terms of service are being worked around, and nothing here
guesses. A CUI that ANAF does not know comes back `found: False`; an
unreachable ANAF comes back with `error` set. Neither is ever papered over
with a plausible-looking company, for the same reason the scrapers report
an honest zero rather than inventing a tender: a fabricated verification
is worse than no verification for someone deciding whether to bid.
"""
import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from text_utils import fold

logger = logging.getLogger("CompanyRegistry")

ANAF_TVA_URL = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
ANAF_BILANT_URL = "https://webservicesp.anaf.ro/bilant"

# ANAF rejects an oversized batch outright rather than truncating it.
ANAF_MAX_BATCH = 100
ANAF_TIMEOUT_SECONDS = 20.0

# The balance sheet for year N is filed during N+1, so the most recent
# year is routinely not there yet — and a company can legitimately skip a
# year. Walk back rather than reporting "no financials" off one miss.
BILANT_YEARS_BACK = 4

# Legea 346/2004 keys the IMM class on net turnover and average headcount,
# which are these two rows of the filed balance sheet. Matched on the
# label rather than the indicator code: the code differs between the
# reporting forms ANAF uses for different entity types, the label does not.
TURNOVER_LABELS = ("cifra de afaceri neta", "cifra de afaceri")
HEADCOUNT_LABELS = ("numar mediu de salariati",)


def normalize_cui(raw: Any) -> Optional[int]:
    """`RO 1590082`, `ro-1590082`, `1590082 ` and `1590082` are all the
    same fiscal code. Returns None for anything that cannot be one."""
    if raw is None:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        return None
    try:
        cui = int(digits)
    except ValueError:
        return None
    # 1..10 digits is the full historical range of Romanian fiscal codes.
    if cui <= 0 or len(digits.lstrip("0")) > 10:
        return None
    return cui


def cui_checksum_valid(cui: int) -> bool:
    """The Romanian fiscal code carries a control digit (key 753217532).

    Checked before spending a network round trip: a mistyped CUI is by far
    the most common bad input here, and catching it locally means the user
    is told "this is not a valid CUI" instead of the far more alarming and
    much less accurate "this company does not exist".
    """
    if cui <= 0:
        return False
    digits = str(cui)
    if len(digits) < 2 or len(digits) > 10:
        return False
    key = "753217532"
    body, control = digits[:-1], int(digits[-1])
    # Right-align the body against the key, as the algorithm specifies.
    padded = body.rjust(len(key), "0")[-len(key):]
    total = sum(int(d) * int(k) for d, k in zip(padded, key))
    computed = (total * 10) % 11
    if computed == 10:
        computed = 0
    return computed == control


def _company_name_matches(declared: str, official: str) -> Dict[str, Any]:
    """How well a user-typed company name lines up with the registry's.

    Deliberately not a pass/fail gate. "SC DEDEMAN SRL", "Dedeman S.R.L."
    and "DEDEMAN" are the same company to a human and differ as strings,
    so a strict comparison would reject correct input; but a name that
    shares nothing with the registry's is worth surfacing, because it
    usually means the CUI belongs to somebody else entirely.
    """
    if not declared or not official:
        return {"compared": False, "matches": None, "confidence": None}

    # Legal-form suffixes carry no identifying information and are written
    # a dozen different ways, so they are stripped from both sides first.
    noise = {"sc", "s", "c", "srl", "sa", "pfa", "ii", "if", "d", "societatea", "societate", "comerciala"}

    def tokens(name: str) -> set:
        # Split on anything that is not a letter or digit rather than a
        # hand-listed set of separators. The registry writes trade names in
        # quotes — SOCIETATEA NATIONALA DE GAZE NATURALE "ROMGAZ" SA — and
        # a quote left attached to the token means the one distinctive word
        # in that name ("romgaz") never matches what the user typed, so a
        # correct entry gets reported as the wrong company.
        cleaned = "".join(ch if ch.isalnum() else " " for ch in fold(name))
        return {t for t in cleaned.split() if t and t not in noise}

    a, b = tokens(declared), tokens(official)
    if not a or not b:
        return {"compared": False, "matches": None, "confidence": None}
    overlap = len(a & b) / len(a | b)
    return {
        "compared": True,
        # Any shared distinctive token is treated as a match: the registry
        # name is frequently longer than what people type ("DEDEMAN" vs
        # "DEDEMAN SRL COMERT SI PRODUCTIE").
        "matches": bool(a & b),
        "confidence": round(overlap, 2),
        "official_name": official,
        "declared_name": declared,
    }


def _parse_anaf_company(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Flattens one ANAF `found` entry into the fields this product uses.

    ANAF nests the same company across five sibling objects; everything
    downstream wants one flat record, and mapping it here (rather than in
    the eligibility engine) keeps ANAF's response shape out of the rest of
    the codebase.
    """
    general = entry.get("date_generale") or {}
    vat = entry.get("inregistrare_scop_Tva") or {}
    inactive = entry.get("stare_inactiv") or {}
    address = entry.get("adresa_sediu_social") or {}

    caen_raw = general.get("cod_CAEN")
    # ANAF returns CAEN as an int, dropping any leading zero (610, not
    # 0610). CAEN codes are 4 digits; restoring the padding is what makes
    # them comparable against the programme tables in
    # business_eligibility.py, which list them as strings.
    caen = str(caen_raw).zfill(4) if caen_raw not in (None, "", 0) else None

    return {
        "cui": general.get("cui"),
        "company_name": (general.get("denumire") or "").strip() or None,
        "trade_registry_number": (general.get("nrRegCom") or "").strip() or None,
        "caen_code": caen,
        "legal_form": (general.get("forma_juridica") or "").strip() or None,
        "ownership_form": (general.get("forma_de_proprietate") or "").strip() or None,
        "registration_date": (general.get("data_inregistrare") or "").strip() or None,
        "registration_status": (general.get("stare_inregistrare") or "").strip() or None,
        "address": (general.get("adresa") or "").strip() or None,
        "county": (address.get("sdenumire_Judet") or "").strip() or None,
        "locality": (address.get("sdenumire_Localitate") or "").strip() or None,
        "postal_code": (general.get("codPostal") or "").strip() or None,
        "tax_authority": (general.get("organFiscalCompetent") or "").strip() or None,
        "vat_registered": bool(vat.get("scpTVA")),
        # The one field here that is itself a procurement exclusion ground:
        # a taxpayer ANAF has declared inactive cannot credibly certify the
        # tax-obligation requirement of Art. 165 Legea 98/2016.
        "is_inactive_taxpayer": bool(inactive.get("statusInactivi")),
        "inactivation_date": (inactive.get("dataInactivare") or "").strip() or None,
        "deregistration_date": (inactive.get("dataRadiere") or "").strip() or None,
        "einvoice_registered": bool(general.get("statusRO_e_Factura")),
    }


async def lookup_companies(cuis: List[Any], as_of: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """Batch identity lookup. Returns {cui: record} for those ANAF knows.

    ANAF accepts up to 100 per request, which is why this is the batch
    primitive and `lookup_company` is the single-CUI convenience wrapper —
    verifying a list of subcontractors should cost one request, not N.
    """
    normalized = [c for c in (normalize_cui(c) for c in cuis) if c is not None]
    if not normalized:
        return {}

    day = as_of or date.today().isoformat()
    results: Dict[int, Dict[str, Any]] = {}

    async with httpx.AsyncClient(timeout=ANAF_TIMEOUT_SECONDS) as client:
        for start in range(0, len(normalized), ANAF_MAX_BATCH):
            batch = normalized[start : start + ANAF_MAX_BATCH]
            payload = [{"cui": c, "data": day} for c in batch]
            try:
                resp = await client.post(
                    ANAF_TVA_URL,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                # ANAF answers 404 for a code it simply does not have on
                # file, which is an ordinary outcome (a typo, a company
                # never registered) and not a fault. Logging it at warning
                # level made every mistyped CUI look like an ANAF outage in
                # the logs, so it is separated from the real failures —
                # timeouts, 5xx, malformed JSON — below.
                if resp.status_code == 404:
                    logger.debug(f"[CompanyRegistry] ANAF has no record for batch starting {batch[0]}")
                    continue
                resp.raise_for_status()
                body = resp.json()
            except Exception as e:
                # Partial results are kept: a second batch failing must not
                # discard the companies the first one already verified.
                logger.warning(f"[CompanyRegistry] ANAF lookup failed for batch starting {batch[0]}: {e}")
                continue

            for entry in body.get("found") or []:
                record = _parse_anaf_company(entry)
                if record.get("cui") is not None:
                    results[int(record["cui"])] = record

    return results


def _extract_bilant_indicator(indicators: List[Dict[str, Any]], labels: tuple) -> Optional[float]:
    for row in indicators:
        label = fold(str(row.get("val_den_indicator") or "")).strip()
        for wanted in labels:
            if label.startswith(fold(wanted)):
                value = row.get("val_indicator")
                if value is None:
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
    return None


async def fetch_financials(cui: Any, years_back: int = BILANT_YEARS_BACK) -> Dict[str, Any]:
    """Net turnover and average headcount from the filed balance sheet.

    Walks backwards from last year: the statement for year N is filed
    during N+1, so the current year is never available and the most recent
    one often is not either. Returns the first year that carries real
    figures, and says which year it came from — an IMM classification
    computed off a three-year-old filing is still defensible, but only if
    the caller can see that is what happened.
    """
    normalized = normalize_cui(cui)
    if normalized is None:
        return {"found": False, "error": "CUI invalid."}

    current_year = date.today().year
    async with httpx.AsyncClient(timeout=ANAF_TIMEOUT_SECONDS) as client:
        for year in range(current_year - 1, current_year - 1 - years_back, -1):
            try:
                resp = await client.get(ANAF_BILANT_URL, params={"an": year, "cui": normalized})
                resp.raise_for_status()
                body = resp.json()
            except Exception as e:
                logger.warning(f"[CompanyRegistry] ANAF bilant failed for {normalized}/{year}: {e}")
                continue

            indicators = body.get("i") or []
            if not indicators:
                continue

            turnover = _extract_bilant_indicator(indicators, TURNOVER_LABELS)
            headcount = _extract_bilant_indicator(indicators, HEADCOUNT_LABELS)
            if turnover is None and headcount is None:
                continue

            return {
                "found": True,
                "fiscal_year": year,
                "turnover_ron": turnover,
                "employee_count": int(headcount) if headcount is not None else None,
                "caen_code": str(body.get("caen")).zfill(4) if body.get("caen") else None,
                "caen_description": (body.get("den_caen") or "").strip() or None,
                "company_name": (body.get("deni") or "").strip() or None,
                "source": "ANAF bilanț (situații financiare depuse)",
            }

    return {
        "found": False,
        "error": (
            f"ANAF nu are situații financiare publicate pentru acest CUI în ultimii "
            f"{years_back} ani (firmă nou-înființată, nedepunere, sau formă juridică fără obligație de depunere)."
        ),
    }


async def verify_company(
    cui: Any,
    declared_name: Optional[str] = None,
    include_financials: bool = True,
) -> Dict[str, Any]:
    """The full verified profile behind "Verificarea profilului companiei".

    Identity comes from ANAF's taxpayer register and the figures from the
    company's own filed balance sheet, so the eligibility verdict computed
    downstream rests on the state's record rather than on what somebody
    typed into a form. `verified` is the single flag callers should branch
    on; everything else explains it.
    """
    normalized = normalize_cui(cui)
    if normalized is None:
        return {
            "verified": False,
            "found": False,
            "cui_input": str(cui) if cui is not None else None,
            "error": "CUI invalid — introduceți codul fiscal numeric (ex: RO1590082 sau 1590082).",
        }

    checksum_ok = cui_checksum_valid(normalized)

    identity_task = lookup_companies([normalized])
    financial_task = fetch_financials(normalized) if include_financials else None
    if financial_task is not None:
        identities, financials = await asyncio.gather(identity_task, financial_task)
    else:
        identities, financials = await identity_task, None

    record = identities.get(normalized)
    if record is None:
        return {
            "verified": False,
            "found": False,
            "cui": normalized,
            "cui_checksum_valid": checksum_ok,
            "error": (
                "CUI-ul nu trece verificarea cifrei de control — este aproape sigur o eroare de tastare."
                if not checksum_ok
                else "ANAF nu returnează nicio firmă pentru acest CUI (radiată, inexistentă, sau serviciul ANAF este indisponibil)."
            ),
            "source": "ANAF — Registrul persoanelor impozabile",
        }

    name_match = _company_name_matches(declared_name or "", record.get("company_name") or "")

    # Facts that bar a company from a public procedure regardless of how
    # well it scores financially. Surfaced here, from the register, rather
    # than left to the self-declaration checkboxes on the form.
    registry_warnings: List[str] = []
    if record.get("is_inactive_taxpayer"):
        registry_warnings.append(
            "ANAF a declarat firma INACTIVĂ fiscal — motiv de excludere din procedurile de achiziție publică "
            "(Art. 165 Legea 98/2016) până la reactivare."
        )
    if record.get("deregistration_date"):
        registry_warnings.append(f"Firmă radiată la data {record['deregistration_date']}.")
    if name_match.get("compared") and name_match.get("matches") is False:
        registry_warnings.append(
            f"Denumirea introdusă (\"{declared_name}\") nu corespunde cu cea din registrul ANAF "
            f"(\"{record.get('company_name')}\") — verificați dacă CUI-ul aparține firmei dvs."
        )

    return {
        "verified": True,
        "found": True,
        "cui": normalized,
        "cui_checksum_valid": checksum_ok,
        "company": record,
        "financials": financials if financials is not None else {"found": False, "error": "Neinterogat."},
        "name_match": name_match,
        "registry_warnings": registry_warnings,
        "sources": [
            "ANAF — Registrul persoanelor impozabile (webservicesp.anaf.ro)",
            "ANAF — Situații financiare depuse (bilanț)",
        ],
        "checked_at": date.today().isoformat(),
    }
