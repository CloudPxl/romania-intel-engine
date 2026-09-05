"""Live accuracy check for "Verificarea profilului companiei".

Runs the real lookup against the real ANAF registers — no mocks, no
fixtures — over a ground-truth set of nine actual Romanian companies
chosen to span the shapes that break naive implementations: an SA and an
SRL, a cooperative, a 3-digit CUI and a 8-digit one, CAEN codes with and
without a leading zero, and registered offices in three different
counties.

The bar, set by the product owner: 100% on every assertion, five
consecutive runs. Anything less exits non-zero.

    python scripts/verify_company_lookup.py

Repeat runs matter more than the number of cases: ANAF is a live
government service, and a client that is correct once but flaky under
repeated calls is not one you can put behind a customer-facing button.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from addons.company_registry import (  # noqa: E402
    cui_checksum_valid,
    normalize_cui,
    verify_company,
)
from text_utils import fold  # noqa: E402

REQUIRED_CLEAN_RUNS = 5

# Ground truth. Each entry was read off ANAF's own register before being
# written down here, so a failure means our client changed behaviour or
# broke — not that the expectation was a guess.
COMPANIES = [
    {"cui": 1590082, "name_contains": "omv petrom", "caen": "0610", "county_contains": "bucuresti"},
    {"cui": 14399840, "name_contains": "dante international", "caen": "4754", "county_contains": "bucuresti"},
    {"cui": 14056826, "name_contains": "romgaz", "caen": "0620", "county_contains": "sibiu"},
    {"cui": 13267221, "name_contains": "electrica", "caen": "7020", "county_contains": "bucuresti"},
    {"cui": 5888716, "name_contains": "digi romania", "caen": "6110", "county_contains": "bucuresti"},
    {"cui": 199001, "name_contains": "armatura", "caen": "2814", "county_contains": "cluj"},
    {"cui": 14837428, "name_contains": "borg design", "caen": "6210", "county_contains": "bucuresti"},
    {"cui": 13548146, "name_contains": "cubus arts", "caen": "6210", "county_contains": "sibiu"},
    {"cui": 361, "name_contains": "cooperativa", "caen": "2369", "county_contains": "bucuresti"},
]


class Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list = []

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
        else:
            self.failed.append(f"{label}{(' — ' + detail) if detail else ''}")


async def run_once(run_index: int) -> Checker:
    c = Checker()

    for expected in COMPANIES:
        cui = expected["cui"]
        result = await verify_company(cui, declared_name=None)
        prefix = f"CUI {cui}"

        if not result.get("verified"):
            c.check(f"{prefix} verified", False, result.get("error") or "not verified")
            continue
        c.check(f"{prefix} verified", True)

        company = result.get("company") or {}
        name = fold(company.get("company_name") or "")
        c.check(
            f"{prefix} name",
            expected["name_contains"] in name,
            f"expected ~'{expected['name_contains']}', got '{company.get('company_name')}'",
        )
        c.check(
            f"{prefix} CAEN",
            company.get("caen_code") == expected["caen"],
            f"expected {expected['caen']}, got {company.get('caen_code')}",
        )
        c.check(
            f"{prefix} county",
            expected["county_contains"] in fold(company.get("county") or ""),
            f"expected ~'{expected['county_contains']}', got '{company.get('county')}'",
        )
        c.check(
            f"{prefix} trade registry number present",
            bool(company.get("trade_registry_number")),
        )
        c.check(f"{prefix} echoes back its own CUI", company.get("cui") == cui)

    # Normalisation: the three ways a person actually types a fiscal code
    # must all resolve to the same company.
    for variant in ("RO1590082", "ro 1590082", " 1590082 "):
        result = await verify_company(variant)
        c.check(
            f"normalises '{variant}'",
            result.get("verified") and (result.get("company") or {}).get("cui") == 1590082,
            str(result.get("error")),
        )

    # A name that belongs to a different company must be reported, not
    # quietly accepted — this is the check that catches a copy-pasted CUI.
    mismatch = await verify_company(1590082, declared_name="Firma Inexistenta Test SRL")
    c.check(
        "name mismatch is flagged",
        any("nu corespunde" in w for w in mismatch.get("registry_warnings", [])),
        str(mismatch.get("registry_warnings")),
    )
    match = await verify_company(1590082, declared_name="OMV PETROM SA")
    c.check(
        "correct name raises no warning",
        not any("nu corespunde" in w for w in match.get("registry_warnings", [])),
        str(match.get("registry_warnings")),
    )

    # Honest failure: never invent a company for input that has none.
    bad_checksum = await verify_company(1590083)
    c.check(
        "invalid checksum rejected without inventing a company",
        not bad_checksum.get("verified") and bad_checksum.get("cui_checksum_valid") is False,
        str(bad_checksum),
    )
    garbage = await verify_company("nu-este-un-cui")
    c.check("non-numeric input rejected", not garbage.get("verified"), str(garbage))

    # Financials must be real filed figures, not defaults.
    fin = await verify_company(1590082)
    financials = fin.get("financials") or {}
    c.check("financials found", bool(financials.get("found")), str(financials.get("error")))
    c.check(
        "turnover is a real positive figure",
        isinstance(financials.get("turnover_ron"), float) and financials["turnover_ron"] > 0,
        str(financials.get("turnover_ron")),
    )
    c.check(
        "headcount is a real positive figure",
        isinstance(financials.get("employee_count"), int) and financials["employee_count"] > 0,
        str(financials.get("employee_count")),
    )

    # Pure-function guards, cheap and run every pass so a refactor that
    # breaks CUI validation cannot hide behind a healthy network.
    c.check("checksum accepts a valid CUI", cui_checksum_valid(1590082))
    c.check("checksum rejects an invalid one", not cui_checksum_valid(1590083))
    c.check("normalize strips the RO prefix", normalize_cui("RO1590082") == 1590082)
    c.check("normalize rejects letters-only input", normalize_cui("abc") is None)

    total = c.passed + len(c.failed)
    status = "100%" if not c.failed else f"{c.passed}/{total}"
    print(f"  run {run_index}: {status} ({c.passed} passed, {len(c.failed)} failed)")
    for failure in c.failed:
        print(f"      FAIL {failure}")
    return c


async def main() -> int:
    print(f"Live ANAF accuracy check — {len(COMPANIES)} real companies, {REQUIRED_CLEAN_RUNS} consecutive runs required\n")
    clean_streak = 0
    for i in range(1, REQUIRED_CLEAN_RUNS + 1):
        checker = await run_once(i)
        if checker.failed:
            print(f"\nFAILED on run {i} — streak broken at {clean_streak} clean run(s).")
            return 1
        clean_streak += 1

    print(f"\n{clean_streak}/{REQUIRED_CLEAN_RUNS} consecutive runs at 100% accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
