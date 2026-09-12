"""Email transport (Resend -> SMTP) and the lead-alert template.

The transport order matters operationally: SMTP on :587 from a PaaS is
frequently blocked or throttled and fails as a *timeout*, which reads as a
hang rather than a misconfiguration. Resend goes over HTTPS and is tried
first; SMTP stays as the fallback so an existing configuration keeps
working.
"""
import pytest

import notifier
from notifier import LeadAlertDispatcher, build_lead_alert_email


class _FakeResponse:
    def __init__(self, status_code, text="{}"):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Records the outbound Resend call. Replaces httpx.AsyncClient so no
    network is touched."""

    def __init__(self, status_code=200, calls=None):
        self._status = status_code
        self.calls = calls if calls is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(self._status)


def _patch_resend(monkeypatch, status_code=200):
    calls = []
    monkeypatch.setattr(notifier, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(
        notifier.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(status_code=status_code, calls=calls),
    )
    return calls


class TestTransportOrder:
    @pytest.mark.asyncio
    async def test_resend_is_used_first_and_smtp_is_not_touched(self, monkeypatch):
        calls = _patch_resend(monkeypatch)
        smtp_called = []
        monkeypatch.setattr(
            LeadAlertDispatcher, "_send_email_sync",
            staticmethod(lambda *a, **k: smtp_called.append(a) or True),
        )
        ok = await LeadAlertDispatcher.send_email(["a@b.ro"], "S", "<p>h</p>", "t")
        assert ok is True
        assert len(calls) == 1
        assert calls[0]["url"] == notifier.RESEND_API_URL
        assert calls[0]["json"]["to"] == ["a@b.ro"]
        assert not smtp_called, "SMTP must not run once Resend accepted"

    @pytest.mark.asyncio
    async def test_falls_back_to_smtp_when_resend_rejects(self, monkeypatch):
        _patch_resend(monkeypatch, status_code=422)
        smtp_called = []
        monkeypatch.setattr(
            LeadAlertDispatcher, "_send_email_sync",
            staticmethod(lambda *a, **k: smtp_called.append(a) or True),
        )
        assert await LeadAlertDispatcher.send_email(["a@b.ro"], "S", "<p>h</p>", "t") is True
        assert len(smtp_called) == 1, "SMTP fallback did not run"

    @pytest.mark.asyncio
    async def test_unconfigured_resend_goes_straight_to_smtp(self, monkeypatch):
        monkeypatch.setattr(notifier, "RESEND_API_KEY", "")
        smtp_called = []
        monkeypatch.setattr(
            LeadAlertDispatcher, "_send_email_sync",
            staticmethod(lambda *a, **k: smtp_called.append(a) or False),
        )
        assert await LeadAlertDispatcher.send_email(["a@b.ro"], "S", "<p>h</p>", "t") is False
        assert len(smtp_called) == 1

    @pytest.mark.asyncio
    async def test_both_transports_failing_reports_failure(self, monkeypatch):
        """The honest-failure contract: no transport accepted it, so the
        caller must not be told it was sent."""
        _patch_resend(monkeypatch, status_code=500)
        monkeypatch.setattr(
            LeadAlertDispatcher, "_send_email_sync", staticmethod(lambda *a, **k: False)
        )
        assert await LeadAlertDispatcher.send_email(["a@b.ro"], "S", "<p>h</p>", "t") is False

    @pytest.mark.asyncio
    async def test_no_recipients_is_never_a_send(self, monkeypatch):
        calls = _patch_resend(monkeypatch)
        assert await LeadAlertDispatcher.send_email([], "S", "<p>h</p>", "t") is False
        assert not calls


class TestMoneyFormatting:
    @pytest.mark.parametrize("value,expected", [
        (24_500_000, "24,50 Mil. RON"),
        (1_234_567.89, "1,23 Mil. RON"),
        (150_000, "150.000 RON"),
        (0, "Nepublicată"),
        (None, "Nepublicată"),
        (-5, "Nepublicată"),
    ])
    def test_romanian_separators_and_unpublished(self, value, expected):
        assert notifier._format_ron(value) == expected

    def test_the_unit_suffix_is_not_mangled_by_the_separator_swap(self):
        """en-US -> ro-RO swaps '.' and ',', and applying that to the whole
        string after appending the unit also rewrites the full stop in
        'Mil.', yielding '24,50 Mil, RON'."""
        assert "Mil. RON" in notifier._format_ron(24_500_000)
        assert "Mil," not in notifier._format_ron(24_500_000)


class TestLeadTemplate:
    def _lead(self, **over):
        base = {
            "project_title": "Modernizare drum județean",
            "entity_name": "Consiliul Județean Cluj",
            "county": "Cluj", "locality": "Cluj-Napoca",
            "financial_value_ron": 24_500_000,
            "action_deadline": "2026-10-15",
            "executive_summary": "Indicatori tehnico-economici aprobați.",
            "source_id": "HCL-CJ-2026/188",
            "sub_category": "Hotărâre de consiliu",
            "source_url": "https://cjcluj.ro/hcl/188",
        }
        base.update(over)
        return base

    def test_scraped_text_is_escaped(self):
        """Every field is scraped from a third-party portal. Romanian
        institutional CMSs emit raw & and stray tags routinely."""
        _, html, _ = build_lead_alert_email(
            self._lead(project_title='Reabilitare <script>x</script> & extindere')
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html and "&amp;" in html

    def test_click_through_targets_the_in_app_dossier_with_an_encoded_id(self):
        """source_ids legitimately contain '/', which would otherwise split
        the query parameter and open the wrong (or no) dossier."""
        _, html, _ = build_lead_alert_email(self._lead())
        assert "openLead=HCL-CJ-2026%2F188" in html

    def test_key_specs_are_present(self):
        _, html, text = build_lead_alert_email(self._lead())
        for expected in ("Consiliul Județean Cluj", "24,50 Mil. RON", "2026-10-15"):
            assert expected in html, f"{expected} missing from the HTML"
            assert expected in text, f"{expected} missing from the plaintext part"

    def test_match_reasons_are_shown_when_supplied(self):
        _, html, text = build_lead_alert_email(
            self._lead(), {"score": 8.4, "reasons": ["Cuvânt cheie: drum", "Județ: Cluj"]}
        )
        assert "De ce v-a fost trimisă" in html
        assert "Cuvânt cheie: drum" in html and "Cuvânt cheie: drum" in text
        assert "8.4/10" in html

    def test_an_unpublished_budget_is_never_rendered_as_zero(self):
        """The product's zero-fabrication rule. '0.0 Mil. RON' asserts the
        contract is worth nothing, which is a different claim from 'the
        authority published no figure'."""
        subject, html, text = build_lead_alert_email(self._lead(financial_value_ron=0))
        assert "Nepublicată" in html and "Nepublicată" in text and "Nepublicată" in subject
        assert "0,00 Mil" not in html and "0.0 Mil" not in html

    def test_a_bare_lead_does_not_raise(self):
        """Ingestion hands this whatever the scraper produced; a sparse
        signal must still produce a sendable message."""
        subject, html, text = build_lead_alert_email({"source_id": "X-1"})
        assert subject and "<html" in html and text
