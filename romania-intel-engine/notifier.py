import os
import logging
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("AlertDispatcher")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@ro-intel.xyz")
NOTIFICATION_EMAIL_TO = os.getenv("NOTIFICATION_EMAIL_TO", "director@infraconstruct.ro,office@ro-intel.xyz")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

class LeadAlertDispatcher:
    @staticmethod
    async def dispatch_telegram_message(chat_id: str, text: str) -> bool:
        """Low-level Telegram send, used both for admin/system alerts (circuit
        breaker trips, staleness) and per-tenant lead alerts. Unlike the SMTP
        path below, an unconfigured bot token is reported as a real failure
        rather than a simulated success."""
        if not TELEGRAM_BOT_TOKEN or not chat_id:
            logger.warning("[Telegram] TELEGRAM_BOT_TOKEN or chat_id not set — alert not sent.")
            return False
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
                resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram alert: {e}")
            return False

    @classmethod
    async def dispatch_admin_alert(cls, text: str) -> bool:
        """System/operator-facing alerts (circuit breaker trips, staleness
        watchdog) — separate from tenant-facing lead alerts below."""
        if TELEGRAM_ADMIN_CHAT_ID:
            sent = await cls.dispatch_telegram_message(TELEGRAM_ADMIN_CHAT_ID, text)
            if sent:
                return True
        recipients = [e.strip() for e in NOTIFICATION_EMAIL_TO.split(",") if e.strip()]
        if not recipients:
            return False
        return await asyncio.to_thread(
            cls._send_email_sync, recipients, "[RO-INTEL] Alertă Sistem", f"<pre>{text}</pre>", text
        )

    @staticmethod
    def _send_email_sync(to_emails: List[str], subject: str, html_body: str, text_body: str) -> bool:
        if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
            logger.info(f"📧 [Email Alert Local Engine Simulated] To: {to_emails} | Subject: {subject}")
            return True
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = SMTP_FROM
            msg["To"] = ", ".join(to_emails)
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
            else:
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
                server.starttls()

            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_emails, msg.as_string())
            server.quit()
            logger.info(f"✅ Email alert sent to {to_emails}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send email alert: {e}")
            return False

    @classmethod
    async def dispatch_email_alert(cls, lead: Dict[str, Any], recipient_emails: Optional[List[str]] = None) -> bool:
        recipients = recipient_emails or [e.strip() for e in NOTIFICATION_EMAIL_TO.split(",") if e.strip()]
        if not recipients:
            return False

        score = lead.get("opportunity_score", 0)
        title = lead.get("project_title", "Proiect Pre-SEAP Nou")
        budget_mil = (lead.get("financial_value_ron", 0) / 1000000)
        county = lead.get("county", "România")
        locality = lead.get("locality", "")
        entity = lead.get("entity_name", "Autoritate Contractantă")
        source = lead.get("source_type", "Pre-SEAP")
        sub_cat = lead.get("sub_category", lead.get("category", "General"))
        deadline = lead.get("action_deadline", "Nespecificat")
        summary = lead.get("executive_summary", "")
        pitch = lead.get("sales_pitch_angle", "")
        source_url = lead.get("source_url", "https://ro-intel.xyz")

        subject = f"🚨 [RO-INTEL ALERTĂ] {budget_mil:.1f} Mil. RON - {title[:50]}... ({county})"
        text_body = f"RO-INTEL 2026 - ALERTĂ PRE-SEAP (Scor {score}/10)\n\nProiect: {title}\nBeneficiar: {entity} ({locality}, {county})\nBuget: {budget_mil:.1f} Mil. RON\nTermen: {deadline}\nSursă: {source}\n\nSinteză:\n{summary}\n\nTactică:\n{pitch}\n\nDosar Oficial: {source_url}\n"

        html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, sans-serif; background-color: #060b13; color: #f1f5f9; padding: 20px; }}
.card {{ max-width: 620px; margin: 0 auto; background-color: #0b111e; border: 1px solid #182335; border-radius: 14px; padding: 24px; }}
.badge {{ background-color: #083344; color: #22d3ee; font-size: 11px; font-weight: bold; padding: 4px 10px; border-radius: 6px; text-transform: uppercase; }}
.btn {{ display: block; text-align: center; background: #06b6d4; color: #000; font-weight: bold; font-size: 13px; text-decoration: none; padding: 12px; border-radius: 8px; margin-top: 20px; }}
</style></head>
<body><div class="card">
<span class="badge">{sub_cat}</span>
<h2 style="color: #fff; margin-top: 12px;">{title}</h2>
<p style="color: #94a3b8; font-size: 13px;">🏛 {entity} &bull; 📍 {locality}, {county}</p>
<p style="color: #38bdf8; font-size: 16px; font-weight: bold;">Buget: {budget_mil:.2f} Mil. RON | Termen: {deadline}</p>
<p style="color: #cbd5e1; font-size: 13px; line-height: 1.6;">{summary}</p>
<div style="background-color: #082f49; border: 1px solid #0284c7; border-radius: 8px; padding: 12px; font-size: 12px; color: #e0f2fe;">
<b>💡 Recomandare Tactică:</b><br>{pitch}
</div>
<a href="{source_url}" class="btn">Accesează Documentul Oficial Sursă ↗</a>
</div></body></html>"""

        return await asyncio.to_thread(cls._send_email_sync, recipients, subject, html_body, text_body)

    @classmethod
    async def dispatch_high_priority_alert(cls, lead: Dict[str, Any], recipient_emails: Optional[List[str]] = None):
        """Legacy, non-tenant-aware path — kept for the old 6h batch job
        (api.py:background_scraping_job / daemon.py) while it still runs
        alongside the new per-tenant streaming pipeline. New code should use
        dispatch_lead_alert_to_tenant instead."""
        from ai_refinery import HIGH_PRIORITY_SCORE

        if lead.get("opportunity_score", 0) >= HIGH_PRIORITY_SCORE:
            await cls.dispatch_email_alert(lead, recipient_emails)

    @classmethod
    async def dispatch_lead_alert_to_tenant(cls, lead: Dict[str, Any], tenant_id: str, match_info: Dict[str, Any]) -> Dict[str, bool]:
        """Tenant-aware, per-channel-idempotent alert dispatch for the
        streaming pipeline (orchestrator.run_tick). Fires Telegram (instant)
        and email (rich HTML dossier) independently — one failing doesn't
        block the other — and only records a channel as dispatched once it
        actually succeeds, gated by min_alert_score per tenant rather than
        the old global 9.0/9.2 hardcoded thresholds."""
        import db
        from matching_engine import TENANT_ORGANIZATIONS

        tenant = TENANT_ORGANIZATIONS.get(tenant_id, {})
        # `.get(..., 9.0)` only falls back when the key is absent — but
        # db.get_tenant_organizations() stores an explicit None for a
        # tenant whose min_alert_score column is NULL (nullable, no DB
        # default), so the key is always present. That made this compare a
        # float against None for any such tenant, raising TypeError on
        # every match (caught by orchestrator.py's per-alert try/except,
        # so it silently dropped every alert for that tenant instead of
        # crashing the tick).
        min_score = tenant.get("min_alert_score")
        if min_score is None:
            min_score = 9.0
        if match_info.get("tenant_opportunity_score", 0) < min_score:
            return {"telegram": False, "email": False}

        source_id = lead.get("source_id", "")
        results = {"telegram": False, "email": False}

        chat_id = tenant.get("telegram_chat_id")
        if chat_id and not await db.has_alert_been_dispatched(tenant_id, source_id, "telegram"):
            text = f"🚨 <b>{lead.get('project_title', '')}</b>\n{lead.get('entity_name', '')} ({lead.get('county', '')})\nScor: {match_info.get('tenant_opportunity_score')}/10\n{lead.get('source_url', '')}"
            if await cls.dispatch_telegram_message(chat_id, text):
                await db.record_alert_dispatch(tenant_id, source_id, "telegram")
                results["telegram"] = True

        emails = tenant.get("alert_emails") or []
        if emails and not await db.has_alert_been_dispatched(tenant_id, source_id, "email"):
            if await cls.dispatch_email_alert(lead, emails):
                await db.record_alert_dispatch(tenant_id, source_id, "email")
                results["email"] = True

        return results
