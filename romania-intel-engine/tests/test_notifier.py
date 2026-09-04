"""notifier.py's admin-alert path used to lie: an unconfigured SMTP fallback
logged "sent" and returned True with nothing actually delivered, and no
caller inspected the return value anyway — so a fully-broken source could
open its circuit breaker and nobody would ever find out. These pin the fix:
an honest failure on every channel, and a durable record of it.
"""
import pytest

import notifier
from notifier import LeadAlertDispatcher


class _RecordingDb:
    def __init__(self):
        self.recorded = []

    async def record_system_alert(self, message):
        self.recorded.append(message)


class TestSendEmailSync:
    def test_unconfigured_smtp_returns_false(self, monkeypatch):
        monkeypatch.setattr(notifier, "SMTP_HOST", "")
        monkeypatch.setattr(notifier, "SMTP_USER", "")
        monkeypatch.setattr(notifier, "SMTP_PASSWORD", "")
        sent = LeadAlertDispatcher._send_email_sync(["a@b.ro"], "Subj", "<p>x</p>", "x")
        assert sent is False


class TestDispatchAdminAlert:
    @pytest.mark.asyncio
    async def test_all_channels_unconfigured_persists_and_returns_false(self, monkeypatch):
        monkeypatch.setattr(notifier, "TELEGRAM_ADMIN_CHAT_ID", "")
        monkeypatch.setattr(notifier, "SMTP_HOST", "")
        monkeypatch.setattr(notifier, "SMTP_USER", "")
        monkeypatch.setattr(notifier, "SMTP_PASSWORD", "")
        monkeypatch.setattr(notifier, "NOTIFICATION_EMAIL_TO", "ops@example.ro")

        import db
        fake_db = _RecordingDb()
        monkeypatch.setattr(db, "record_system_alert", fake_db.record_system_alert)

        result = await LeadAlertDispatcher.dispatch_admin_alert("sursa X a picat")
        assert result is False
        assert fake_db.recorded == ["sursa X a picat"]

    @pytest.mark.asyncio
    async def test_telegram_success_short_circuits_and_skips_persistence(self, monkeypatch):
        monkeypatch.setattr(notifier, "TELEGRAM_ADMIN_CHAT_ID", "12345")

        async def fake_telegram(chat_id, text):
            return True

        monkeypatch.setattr(LeadAlertDispatcher, "dispatch_telegram_message", staticmethod(fake_telegram))

        import db
        fake_db = _RecordingDb()
        monkeypatch.setattr(db, "record_system_alert", fake_db.record_system_alert)

        result = await LeadAlertDispatcher.dispatch_admin_alert("totul e bine")
        assert result is True
        assert fake_db.recorded == []
