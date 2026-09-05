"""Qualification scenarios, Art. 210 exposure, and the CNSC clause patterns.

These cover the parts of the brief where the specification itself named a
rule that turned out not to be in force. Each is asserted here against the
consolidated text ingested by scripts/build_legal_kb.py, so a future
rewrite cannot quietly reintroduce the version everyone repeats:

* **The 2x turnover ceiling is art. 175 alin. (2) lit. a), not art. 172.**
  Art. 172 lists the three permitted categories of capacity criteria; art.
  175 is the economic-and-financial one that carries the arithmetic.
* **There is no 80% abnormally-low-price threshold.** Not in art. 210 of
  Legea 98/2016, and not in art. 136 of the HG 395/2016 norms — the string
  "80" appears in the whole of those norms only as article numbers. It is
  a survival from the repealed OUG 34/2006. The product keeps 80% as an
  internal early-warning heuristic and must always label it as one.
* **The notificare prealabilă no longer exists.** Art. 6 and art. 7 of
  Legea 101/2016 were both repealed by OUG 45/2018, and the consolidated
  text contains no such instrument. Advising one burns contestation days.
"""
import pytest

import legal_kb
from addons import price_strategy, qualification_scenarios
from addons.caiet_analyzer import CaietDeSarciniAnalyzer, check_turnover_requirement


def _verification(turnover=None, inactive=False, found=True):
    return {
        "found": found,
        "company": {
            "cui": 199001,
            "company_name": "ACME CONSTRUCT SRL",
            "county": "BRAȘOV",
            "caen_code": "4211",
            "is_inactive_taxpayer": inactive,
            "vat_registered": True,
        },
        "financials": {"found": turnover is not None, "turnover_ron": turnover, "employee_count": 40,
                       "fiscal_year": 2025},
        "sources": ["ANAF"],
    }


# ------------------------------------------------------ the statutory anchors

def test_turnover_ceiling_article_is_175_not_172():
    """Pinned because the brief named art. 172 and the distinction is the
    difference between a citable finding and a wrong one."""
    art175 = legal_kb.get_article("L98/2016:175")["text"]
    assert "nu trebuie să depășească de două ori valoarea estimată" in art175
    art172 = legal_kb.get_article("L98/2016:172")["text"]
    assert "de două ori" not in art172
    assert qualification_scenarios.TURNOVER_CEILING_ARTICLE == "L98/2016:175"


def test_no_eighty_percent_threshold_exists_in_either_instrument():
    for key in ("L98/2016:210", "HG395/2016:136"):
        text = legal_kb.get_article(key)["text"]
        assert "80%" not in text
        assert "80 %" not in text


def test_notificare_prealabila_articles_are_repealed():
    assert legal_kb.is_repealed("L101/2016:6")
    assert legal_kb.is_repealed("L101/2016:7")
    # And the concept is absent from the law entirely.
    assert legal_kb.search("notificare prealabil", law_keys=["L101/2016"]) == []


# --------------------------------------------------------- scenario A: leader

def test_turnover_above_the_ceiling_clears_any_lawful_requirement():
    result = qualification_scenarios.evaluate_qualification(
        _verification(turnover=25_000_000), estimated_value_ron=10_000_000
    )
    a = result["scenario_a_leader"]
    assert a["status"] == "eligible"
    assert a["max_lawful_turnover_requirement_ron"] == 20_000_000


def test_turnover_between_estimate_and_ceiling_is_not_claimed_as_certain():
    result = qualification_scenarios.evaluate_qualification(
        _verification(turnover=12_000_000), estimated_value_ron=10_000_000
    )
    assert result["scenario_a_leader"]["status"] == "likely_eligible"


def test_a_requirement_above_the_ceiling_is_flagged_as_challengeable():
    result = qualification_scenarios.evaluate_qualification(
        _verification(turnover=30_000_000),
        estimated_value_ron=10_000_000,
        required_turnover_ron=25_000_000,
    )
    findings = " ".join(result["scenario_a_leader"]["findings"])
    assert "depășește plafonul" in findings
    assert "175" in findings
    # Challengeable, not automatically unlawful: art. 175 alin. (3) allows
    # exceeding it in duly justified cases.
    assert "art. 175 alin. (3)" in findings


def test_inactive_taxpayer_blocks_every_route():
    result = qualification_scenarios.evaluate_qualification(
        _verification(turnover=99_000_000, inactive=True), estimated_value_ron=1_000
    )
    assert result["scenario_a_leader"]["status"] == "blocked"
    assert "inactiv" in result["recommendation"].lower()


def test_missing_turnover_is_unknown_not_ineligible():
    """Absence of evidence is not evidence of ineligibility — a company too
    new to have filed a balance sheet has not failed anything."""
    result = qualification_scenarios.evaluate_qualification(
        _verification(turnover=None), estimated_value_ron=10_000_000
    )
    assert result["scenario_a_leader"]["status"] == "unknown"


def test_unpublished_estimate_yields_no_ceiling():
    assert qualification_scenarios.max_lawful_turnover_requirement(0) is None
    assert qualification_scenarios.max_lawful_turnover_requirement(None) is None


# ---------------------------------------------------- scenario B: partnership

def test_partnership_routes_are_always_offered_with_real_citations():
    result = qualification_scenarios.evaluate_qualification(
        _verification(turnover=1_000_000), estimated_value_ron=10_000_000
    )
    b = result["scenario_b_partnership"]
    routes = {r["route"] for r in b["routes"]}
    assert routes == {"subcontractor", "joint_venture", "third_party_support"}
    assert b["supportable_share_pct"] == 10.0
    # Every route quotes real text; a route with an empty legal basis would
    # be an assertion with nothing behind it.
    for route in b["routes"]:
        assert route["legal_basis"], f"{route['route']} has no quoted article"


def test_exclusion_review_separates_checked_from_unverifiable():
    review = qualification_scenarios.evaluate_qualification(
        _verification(turnover=5_000_000), estimated_value_ron=1_000_000
    )["exclusion_review"]
    statuses = {g["ground"]: g["status"] for g in review["grounds"]}
    # The one ANAF actually answers.
    assert statuses["Contribuabil declarat inactiv"] == "pass"
    # The ones it cannot. Reporting these as "pass" would be a fabricated
    # clearance on a legally consequential question.
    assert statuses["Insolvență, faliment sau lichidare"] == "unverified"
    assert statuses["Obligații fiscale restante"] == "unverified"
    assert review["unverified_count"] == 4


# ------------------------------------------------------------ price strategy

def test_lowest_price_offers_no_technical_compensation():
    r = price_strategy.analyze_pricing(10_000_000, 9_500_000, award_criterion="lowest_price")
    assert "scoring_model" in r
    assert "undercut_scenarios" not in r["scoring_model"]


def test_best_value_quantifies_the_technical_points_needed():
    r = price_strategy.analyze_pricing(
        10_000_000, 9_000_000, award_criterion="best_value", price_weight_pct=40
    )
    scenario = next(
        s for s in r["scoring_model"]["undercut_scenarios"] if s["competitor_undercuts_you_by_pct"] == 10
    )
    # Price points = (rival/yours) * 40 = 0.9 * 40 = 36, so 4 of 40 lost,
    # which is 4/60 = 6.7% of the technical weight.
    assert scenario["your_price_points"] == 36.0
    assert scenario["price_points_lost"] == 4.0
    assert scenario["technical_advantage_needed_pct_of_technical_weight"] == 6.7


def test_heuristic_trigger_is_labelled_as_ours_not_the_laws():
    r = price_strategy.analyze_pricing(10_000_000, 7_500_000)
    risk = r["abnormally_low_risk"]
    assert risk["requires_justification_dossier"] is True
    assert risk["trigger_used"] == "prag intern de avertizare"
    assert "nu prevăd un prag procentual" in risk["legal_position"]
    assert "OUG 34/2006" in risk["legal_position"]
    # And it must cite the two provisions that do apply.
    citations = " ".join(a["citation"] for a in risk["legal_basis"])
    assert "210" in citations and "136" in citations


def test_real_award_data_overrides_the_heuristic():
    """A measured distribution beats a rule of thumb, and the response has
    to say which one it used."""
    awards = {
        "available": True,
        "sample_size": 12,
        "winning_discount_pct": {"median": 5.0, "average": 5.0, "min": 4.0, "max": 6.0},
    }
    r = price_strategy.analyze_pricing(10_000_000, 8_400_000, award_stats=awards)
    risk = r["abnormally_low_risk"]
    assert risk["code"] == "below_observed_market"
    assert risk["trigger_used"] == "discountul median observat al câștigătorilor"
    assert risk["observed_median_discount_pct"] == 5.0


def test_over_budget_bid_is_flagged_separately():
    r = price_strategy.analyze_pricing(10_000_000, 11_000_000)
    assert r["abnormally_low_risk"]["code"] == "over_budget"


def test_unpublished_estimate_refuses_to_model():
    assert price_strategy.analyze_pricing(0, 5_000)["status"] == "error"


def test_justification_outline_follows_the_statutory_letters():
    outline = price_strategy.build_justification_outline("ACME", "DJ 103", 10_000_000, 7_500_000)
    assert [c["letter"] for c in outline["chapters"]] == ["a", "b", "c", "d", "e", "f"]
    # Chapters d) and e) must reference the two articles art. 210 alin. (2)
    # itself cross-references, or the dossier misses what the commission
    # is required to check.
    assert "51" in outline["chapters"][3]["title"]
    assert "218" in outline["chapters"][4]["title"]
    assert outline["legal_basis"]


# ------------------------------------------------------- CNSC clause patterns

def test_brand_mention_is_not_flagged_when_sau_echivalent_is_present():
    """Art. 156 alin. (3): naming a brand is lawful when accompanied by
    "sau echivalent". Flagging every "marcă" made this the noisiest rule
    in the scanner and fired hardest on correctly-drafted documents."""
    clean = "Se solicita pompe marca Grundfos sau echivalent."
    result = CaietDeSarciniAnalyzer.analyze_specification_text(clean, "Test")
    assert result["equivalence_clause_present"] is True
    patterns = {f["pattern"] for f in result["detected_red_flags"]}
    assert "marca sau producator indicat" not in patterns


def test_brand_lock_in_is_flagged_without_the_saving_phrase():
    result = CaietDeSarciniAnalyzer.analyze_specification_text(
        "Se solicita pompe marca Grundfos.", "Test"
    )
    assert result["equivalence_clause_present"] is False
    patterns = {f["pattern"] for f in result["detected_red_flags"]}
    assert "marca sau producator indicat" in patterns


def test_full_time_employment_requirement_is_flagged():
    result = CaietDeSarciniAnalyzer.analyze_specification_text(
        "Personalul cheie va fi angajat cu contract individual de munca la data depunerii ofertei.",
        "Test",
    )
    flag = next(f for f in result["detected_red_flags"] if "personal angajat" in f["pattern"])
    assert flag["severity"] == "Critic"
    # It must point at art. 182, which is what makes the requirement
    # challengeable rather than merely unfair.
    assert "182" in flag["tactical_advisory"]


def test_mandatory_site_visit_is_flagged():
    result = CaietDeSarciniAnalyzer.analyze_specification_text(
        "Vizitarea amplasamentului este obligatorie pentru toti ofertantii.", "Test"
    )
    patterns = {f["pattern"] for f in result["detected_red_flags"]}
    assert "vizita obligatorie pe amplasament" in patterns


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("25.000.000", 25_000_000.0),
        ("25.000.000,50", 25_000_000.50),
        ("1234567", 1_234_567.0),
    ],
)
def test_romanian_number_format_is_parsed_not_guessed(raw, expected):
    """'.' is the thousands separator in Romanian, the reverse of a Python
    literal — feeding these to float() directly would misparse silently."""
    from addons.caiet_analyzer import _parse_ron_amount

    assert _parse_ron_amount(raw) == expected


def test_turnover_over_ceiling_is_measured_and_cited():
    text = "Ofertantul va prezenta o cifra de afaceri anuala minima de 25.000.000 lei."
    check = check_turnover_requirement(text, estimated_value_ron=10_000_000)
    assert check["required_turnover_ron"] == 25_000_000
    assert check["legal_ceiling_ron"] == 20_000_000
    assert check["exceeds_legal_ceiling"] is True
    assert "175" in check["finding"]


def test_turnover_within_ceiling_is_reported_but_not_flagged():
    text = "Cifra de afaceri anuala minima de 8.000.000 lei."
    check = check_turnover_requirement(text, estimated_value_ron=10_000_000)
    assert check["exceeds_legal_ceiling"] is False
    result = CaietDeSarciniAnalyzer.analyze_specification_text(
        text, "Test", estimated_value_ron=10_000_000
    )
    patterns = {f["pattern"] for f in result["detected_red_flags"]}
    assert "cifra de afaceri peste plafonul legal" not in patterns


def test_turnover_check_needs_both_halves():
    """Half a comparison is not a partial answer — it is a wrong one."""
    assert check_turnover_requirement("cifra de afaceri de 25.000.000 lei", None) is None
    assert check_turnover_requirement("niciun prag mentionat", 10_000_000) is None
