"""Who gets a Web Push notification, and why.

push_notifications.decide_push is the entire notification policy, kept as a
pure function so it can be pinned exhaustively here without a tick, a
database or a push service. Two rules:

  criteria — matched the user's own filters AND cleared their own
      min_alert_score.
  radar    — did NOT match their filters, but scored >= PUSH_RADAR_MIN_SCORE
      on its own merits.
"""
import pytest

import push_notifications
from push_notifications import build_payload, decide_push


def _profile(**over):
    base = {
        "id": "u-1",
        "min_alert_score": 7.5,
        "push_enabled": True,
        "push_radar_enabled": True,
        "exclude_keywords": [],
    }
    base.update(over)
    return base


class TestCriteriaRule:
    def test_match_at_or_above_the_users_threshold_pushes(self):
        assert decide_push({"opportunity_score": 5.0}, _profile(),
                           {"is_match": True, "score": 7.5}) == "criteria"

    def test_match_below_the_users_threshold_does_not_push(self):
        assert decide_push({"opportunity_score": 5.0}, _profile(),
                           {"is_match": True, "score": 7.4}) is None

    def test_a_low_scoring_match_does_not_fall_through_to_the_radar(self):
        """A match under the user's own threshold is their setting being
        respected — not an outlier the radar should rescue. Without this the
        radar would silently override every min_alert_score above 9."""
        assert decide_push({"opportunity_score": 9.9}, _profile(),
                           {"is_match": True, "score": 2.0}) is None

    def test_a_null_min_alert_score_falls_back_to_the_default(self):
        """The column is NULL on older profiles; comparing a float against
        None raises TypeError, which is how a whole user's alerts once
        vanished silently inside a caller's try/except."""
        assert decide_push({"opportunity_score": 5.0}, _profile(min_alert_score=None),
                           {"is_match": True, "score": 8.0}) == "criteria"


class TestRadarRule:
    def test_a_high_scoring_non_match_pushes_as_radar(self):
        assert decide_push({"opportunity_score": 9.0}, _profile(),
                           {"is_match": False, "score": 0.0}) == "radar"

    def test_just_below_the_radar_floor_does_not_push(self):
        assert decide_push({"opportunity_score": 8.99}, _profile(),
                           {"is_match": False, "score": 0.0}) is None

    def test_the_radar_can_be_declined_without_losing_your_own_alerts(self):
        """The radar is the one class of notification the user did not ask
        for, so it is separately switchable."""
        prof = _profile(push_radar_enabled=False)
        assert decide_push({"opportunity_score": 9.9}, prof, {"is_match": False, "score": 0}) is None
        assert decide_push({"opportunity_score": 1.0}, prof, {"is_match": True, "score": 8.0}) == "criteria"

    def test_the_floor_is_configurable(self):
        assert decide_push({"opportunity_score": 8.0}, _profile(),
                           {"is_match": False, "score": 0}, radar_min_score=8.0) == "radar"


class TestSuppression:
    def test_push_disabled_suppresses_both_rules(self):
        prof = _profile(push_enabled=False)
        assert decide_push({"opportunity_score": 9.9}, prof, {"is_match": True, "score": 10}) is None
        assert decide_push({"opportunity_score": 9.9}, prof, {"is_match": False, "score": 0}) is None

    def test_an_excluded_keyword_outranks_even_a_perfect_radar_score(self):
        """A hard exclusion is the user saying 'not this, at any score'.
        matching_engine returns is_match False for these, which at this
        layer is indistinguishable from an ordinary non-match — so without
        re-reading the exclusion list the radar would push exactly the
        thing the user banned."""
        lead = {"opportunity_score": 10.0, "project_title": "Servicii de paza si protectie"}
        assert decide_push(lead, _profile(exclude_keywords=["paza"]),
                           {"is_match": False, "score": 0}) is None

    def test_an_unrelated_exclusion_does_not_suppress(self):
        lead = {"opportunity_score": 9.5, "project_title": "Modernizare drum judetean"}
        assert decide_push(lead, _profile(exclude_keywords=["paza"]),
                           {"is_match": False, "score": 0}) == "radar"

    def test_a_non_numeric_score_is_declined_rather_than_raising(self):
        assert decide_push({"opportunity_score": "n/a"}, _profile(),
                           {"is_match": False, "score": 0}) is None


class TestPayload:
    def test_radar_sends_announce_themselves_in_the_title(self):
        """On a lock screen there is no room to explain why an unrequested
        notification arrived, so the title has to carry it."""
        radar = build_payload({"project_title": "X", "source_id": "S1"}, "radar")
        criteria = build_payload({"project_title": "X", "source_id": "S1"}, "criteria")
        assert "Radar" in radar["title"]
        assert "Radar" not in criteria["title"]

    def test_click_target_deep_links_to_the_dossier(self):
        p = build_payload({"project_title": "X", "source_id": "SEAP-123"}, "criteria")
        assert p["url"] == "/cautare-avansata?openLead=SEAP-123"

    def test_a_lead_without_a_source_id_still_routes_somewhere_valid(self):
        p = build_payload({"project_title": "X"}, "criteria")
        assert p["url"] == "/cautare-avansata"

    def test_unpublished_budget_is_not_shown_as_zero(self):
        p = build_payload({"project_title": "X", "financial_value_ron": 0}, "criteria")
        assert "Nepublicată" in p["body"]

    def test_the_tag_collapses_repeat_notifications_for_one_tender(self):
        p = build_payload({"project_title": "X", "source_id": "S1"}, "criteria")
        assert p["tag"] == "ro-intel-S1"


class TestConfiguration:
    def test_unconfigured_vapid_reports_not_configured(self, monkeypatch):
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", "")
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", "")
        assert push_notifications.is_configured() is False

    def test_both_keys_are_required(self, monkeypatch):
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", "pub")
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", "")
        assert push_notifications.is_configured() is False

    @pytest.mark.asyncio
    async def test_dispatch_is_a_no_op_when_unconfigured(self, monkeypatch):
        """A deployment with no VAPID keys must cost the ingestion tick
        nothing and must not raise into it."""
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", "")
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", "")
        sent = await push_notifications.dispatch_to_user(
            "u-1", [{"endpoint": "e", "p256dh": "k", "auth": "a"}], {"project_title": "X"}, "criteria"
        )
        assert sent == 0


class TestVapidKeyForms:
    """py_vapid accepts a *path* to a PEM or the raw scalar as base64url —
    never the contents of a PEM as a string, which is precisely what an
    operator pastes into a Render env var after running the documented
    openssl recipe.

    Getting this wrong fails only on a real send, with "Could not
    deserialize key data" raised far from the configuration that caused it,
    while every unit test still passes. Caught by an end-to-end send against
    a fabricated FCM endpoint; pinned here.
    """

    PEM = (
        "-----BEGIN EC PRIVATE KEY-----\n"
        "MHcCAQEEIAmJqXxrGhFtqHPtDWreiaHrI4WpO+xdZ3eiZpo9fCn4oAoGCCqGSM49\n"
        "AwEHoUQDQgAEiQbEffX/9h1Ncoq9lCNrEM9btXq07VXxdfjietmFRpWHQzXioZzr\n"
        "S8nYJuSKaXrcH3nb2X9zx+tioeBwGISOIQ==\n"
        "-----END EC PRIVATE KEY-----\n"
    )

    def test_a_pem_is_converted_to_the_raw_base64url_scalar(self, monkeypatch):
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", self.PEM)
        converted = push_notifications._vapid_private_key()
        assert "BEGIN" not in converted
        # A P-256 scalar is 32 bytes -> 43 base64url chars unpadded.
        assert len(converted) == 43
        assert "=" not in converted and "+" not in converted and "/" not in converted

    def test_an_already_raw_key_passes_through_untouched(self, monkeypatch):
        raw = "CYmpfGsaEW2oc-0Nat6JoesjhaU77F1nd6Jmmj18Kfg"
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", raw)
        assert push_notifications._vapid_private_key() == raw

    def test_surrounding_whitespace_does_not_break_detection(self, monkeypatch):
        """Env editors routinely add a trailing newline."""
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", "\n  " + self.PEM + "  \n")
        assert len(push_notifications._vapid_private_key()) == 43

    def test_garbage_degrades_to_empty_rather_than_raising(self, monkeypatch):
        """A malformed key must not raise up through the ingestion tick."""
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY",
                            "-----BEGIN EC PRIVATE KEY-----\nnot-a-key\n-----END EC PRIVATE KEY-----")
        assert push_notifications._vapid_private_key() == ""


class TestKeyPairConsistency:
    """A mismatched VAPID pair is the one misconfiguration that looks
    entirely healthy server-side: is_configured() is True, the browser
    subscribes, every send is attempted, and the push service rejects each
    with a bare 401/403 far from the paste that caused it.

    The pair below is real and was generated with the documented openssl
    recipe. WRONG_PRIVATE is what the previously-documented
    `... -outform DER | tail -c 32` produced from that same key — note it
    is a literal suffix of the public key, because a SEC1 ECPrivateKey DER
    ends with the public point, not the private scalar.
    """

    PUBLIC = ("BELyN8Or-yKPqVnLcv9T4zCoGhw-85mCVUcSsI4nlkLh35Xq42L3j0uB"
              "nas9UsLn5P_w76PVeziLfTrriM0K2UU")
    PRIVATE = "ZcDCq0V2AhLk1f4AUEHVSNkrFcOl8oNg4VCN19mTlFw"
    WRONG_PRIVATE = "35Xq42L3j0uBnas9UsLn5P_w76PVeziLfTrriM0K2UU"

    def test_a_real_pair_is_reported_consistent(self, monkeypatch):
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", self.PUBLIC)
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", self.PRIVATE)
        assert push_notifications.keys_are_consistent() is True

    def test_the_tail_minus_32_mistake_is_caught(self, monkeypatch):
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", self.PUBLIC)
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", self.WRONG_PRIVATE)
        assert push_notifications.keys_are_consistent() is False

    def test_the_wrong_key_really_is_a_suffix_of_the_public_key(self):
        """Pins why the old recipe was wrong, not just that it was."""
        assert self.PUBLIC.endswith(self.WRONG_PRIVATE)

    def test_unset_keys_report_unknown_rather_than_inconsistent(self, monkeypatch):
        """None must be distinguishable from False: callers gate on
        `is False` so an unconfigured deployment is not reported as
        misconfigured."""
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", "")
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", "")
        assert push_notifications.keys_are_consistent() is None

    def test_a_pem_private_key_is_compared_after_conversion(self, monkeypatch):
        """The operator may paste the PEM; consistency must still resolve."""
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY", TestVapidKeyForms.PEM)
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", self.PUBLIC)
        # Different key entirely -> False, not None (i.e. it was evaluated).
        assert push_notifications.keys_are_consistent() is False

    def test_garbage_private_key_reports_unknown_not_a_false_mismatch(self, monkeypatch):
        monkeypatch.setattr(push_notifications, "VAPID_PUBLIC_KEY", self.PUBLIC)
        monkeypatch.setattr(push_notifications, "VAPID_PRIVATE_KEY",
                            "-----BEGIN EC PRIVATE KEY-----\nnope\n-----END EC PRIVATE KEY-----")
        assert push_notifications.keys_are_consistent() is None
