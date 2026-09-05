"""The market profile must actually be *of* the county it was asked about.

Two defects, both of which made a real, correctly-computed analysis look
like fabricated data at the point of use:

1. **The county was counted and then discarded.** `in_requested_county`
   was reported, but the value distribution and the authority list were
   both computed over the nationwide comparable set. Asking about Iași
   returned a median drawn from 54 national procedures and named Compania
   de Apă Oradea and Primăria Municipiului București as the contracting
   authorities observed. Correct numbers answering a question nobody
   asked are indistinguishable, to the reader, from invented ones.

2. **County comparison used `.lower()`.** `"Iași".lower()` is `"iași"`,
   which never equals the `"iasi"` a user types — so the filter matched
   only those sources that happen to publish without diacritics. The rest
   of the codebase normalises counties precisely because of this (see
   db._county_key and the Caraș-Severin note in CLAUDE.md); this module
   was not doing it.

Also pins the award-intelligence summariser, which is the first thing in
this product allowed to state a winning discount — because it is the first
that has real outcomes behind it.
"""
import json

import pytest

import procurement_notices as pn
from addons.competitor_tracker import MIN_COUNTY_SAMPLE, CompetitorTrackerEngine as Engine


def _opp(title, entity, county, value, category="infrastructura", source_id=None):
    return {
        "source_id": source_id or title,
        "project_title": title,
        "entity_name": entity,
        "county": county,
        "financial_value_ron": value,
        "category": category,
    }


NATIONAL = [_opp(f"National {i}", "CNI", "Bihor", 5_000_000 + i) for i in range(50)]
IASI = [_opp(f"Iasi {i}", "Primăria Iași", "Iași", 1_000_000 + i * 1000) for i in range(4)]


# ------------------------------------------------------------ county scoping

def test_diacritics_do_not_break_the_county_filter():
    """Typing "iasi" must find rows stored as "Iași"."""
    result = Engine.analyze_landscape("infrastructura", "iasi", 1_000_000, NATIONAL + IASI)
    assert result["observed_market"]["in_requested_county"] == len(IASI)


def test_figures_are_computed_over_the_county_not_the_country():
    result = Engine.analyze_landscape("infrastructura", "iasi", 1_000_000, NATIONAL + IASI)
    market = result["observed_market"]
    assert market["scope"] == "county"
    assert market["analysed_procedures"] == len(IASI)
    # The bug in one assertion: the national authority must not appear in
    # an analysis scoped to Iași.
    assert market["contracting_authorities_observed"] == ["Primăria Iași"]
    assert "CNI" not in market["contracting_authorities_observed"]
    # A median drawn from Iași values, not from the 5M national ones.
    assert market["value_distribution_ron"]["median"] < 2_000_000


def test_thin_county_data_falls_back_nationally_and_says_so():
    thin = NATIONAL + IASI[:1]  # below MIN_COUNTY_SAMPLE
    market = Engine.analyze_landscape("infrastructura", "iasi", 1_000_000, thin)["observed_market"]
    assert market["scope"] == "national"
    # The national set is every comparable procedure, the lone Iași one
    # included — it is a national figure, not "everything except here".
    assert market["analysed_procedures"] == len(thin)
    assert market["in_requested_county"] == 1
    # The fallback has to be visible in the payload, not just implied.
    assert "întreaga țară" in market["scope_note"]


def test_county_is_echoed_as_the_sources_spell_it():
    result = Engine.analyze_landscape("infrastructura", "iasi", 1_000_000, NATIONAL + IASI)
    assert result["county"] == "Iași"


def test_procedures_carry_source_ids_for_deep_linking():
    market = Engine.analyze_landscape("infrastructura", "iasi", 1_000_000, NATIONAL + IASI)["observed_market"]
    assert market["procedures"]
    assert all(p["source_id"] for p in market["procedures"])


def test_no_pool_still_returns_a_complete_shape():
    result = Engine.analyze_landscape("infrastructura", "Cluj", 0, [])
    assert result["observed_market"]["value_distribution_ron"] is None
    assert result["pricing"]["reference_points_ron"] is None
    assert result["award_intelligence"]["available"] is False


# ------------------------------------------------------- pricing correctness

def test_pricing_guidance_states_no_percentage_threshold():
    """The 80% rule is from the repealed OUG 34/2006 — it is in neither
    art. 210 of Legea 98/2016 nor art. 136 of the HG 395/2016 norms,
    verified against both consolidated texts."""
    guidance = Engine.analyze_landscape("infrastructura", "Cluj", 100.0, [])["pricing"]["guidance"]
    assert "80%" not in guidance
    assert "nu prevede un prag procentual" in guidance
    # It should still name the two provisions that do apply.
    assert "210" in guidance and "136" in guidance


# ---------------------------------------------------------- award summariser

def _can_row(nid, authority, county, estimated, awarded, winner, offers=2, cpv="45000000"):
    """Shaped exactly as procurement_notices rows come back from Postgres —
    JSONB columns arrive as strings through asyncpg's default codec."""
    return {
        "notice_id": nid,
        "cpv_code": cpv,
        "contracting_authority": json.dumps({"name": authority, "county": county}),
        "financial": json.dumps({"estimated_value_ron": estimated}),
        "award_details": json.dumps({
            "winning_bidder_name": winner,
            "awarded_value_ron": awarded,
            "number_of_offers_received": offers,
        }),
        "timeline": json.dumps({}),
    }


def test_award_summary_refuses_to_report_below_the_minimum_sample():
    below = pn.MIN_AWARD_SAMPLE - 1
    rows = [_can_row(f"N{i}", "Primaria X", "Iasi", 100_000, 95_000, "ACME") for i in range(below)]
    out = pn.summarize_awards(rows)
    assert out["available"] is False
    assert out["sample_size"] == below
    assert out["min_sample_required"] == pn.MIN_AWARD_SAMPLE


def test_award_summary_ignores_notices_with_no_awarded_value():
    """A CAN can be published with the winner named and the price absent.
    Those must not be coerced to zero, which would report a 100% discount."""
    rows = [_can_row(f"N{i}", "P", "Iasi", 100_000, 90_000, "ACME") for i in range(5)]
    rows.append(_can_row("NX", "P", "Iasi", 100_000, None, "ACME"))
    out = pn.summarize_awards(rows)
    assert out["awards_seen"] == 6
    assert out["sample_size"] == 5
    assert out["winning_discount_pct"]["median"] == 10.0


def test_award_summary_computes_real_discounts():
    rows = [_can_row(f"N{i}", "P", "Iasi", 100_000, 80_000, "ACME") for i in range(6)]
    out = pn.summarize_awards(rows)
    assert out["available"] is True
    assert out["winning_discount_pct"]["median"] == 20.0


def test_pressure_classification_monopolized():
    rows = [_can_row(f"N{i}", "P", "Iasi", 100_000, 98_000, "ACME") for i in range(8)]
    out = pn.summarize_awards(rows)
    assert out["competitive_pressure"]["code"] == "monopolized"
    assert out["competitive_pressure"]["evidence"]["top_winner_share_pct"] == 100.0


def test_pressure_classification_cutthroat():
    rows = [
        _can_row(f"N{i}", "P", "Iasi", 100_000, 70_000, f"Firma {i}", offers=8)
        for i in range(8)
    ]
    out = pn.summarize_awards(rows)
    assert out["competitive_pressure"]["code"] == "cutthroat"


def test_authority_profile_reports_winner_concentration():
    rows = [_can_row(f"A{i}", "Primaria Alfa", "Iasi", 100_000, 95_000, "ACME") for i in range(4)]
    rows += [_can_row(f"B{i}", "Primaria Alfa", "Iasi", 100_000, 95_000, "Beta") for i in range(1)]
    out = pn.summarize_awards(rows)
    profile = out["authority_profiles"][0]
    assert profile["authority"] == "Primaria Alfa"
    assert profile["awards_observed"] == 5
    assert profile["top_winner"] == "ACME"
    assert profile["top_winner_share_pct"] == 80.0


def test_award_intelligence_reaches_the_market_profile():
    rows = [_can_row(f"N{i}", "P", "Iasi", 100_000, 85_000, "ACME") for i in range(6)]
    awards = pn.summarize_awards(rows)
    result = Engine.analyze_landscape(
        "infrastructura", "iasi", 1_000_000, NATIONAL + IASI, award_stats=awards
    )
    assert result["award_intelligence"]["available"] is True
    # With real awards, the pricing block gains an observed winning price
    # alongside — not instead of — the arithmetic ladder.
    assert result["pricing"]["observed_winning_price_ron"]["median_discount_pct"] == 15.0
    assert result["pricing"]["reference_points_ron"] is not None
    # And the limitations text must stop claiming we collect no award data.
    assert "nu colectează rezultate de atribuire" not in result["data_limitations"]
