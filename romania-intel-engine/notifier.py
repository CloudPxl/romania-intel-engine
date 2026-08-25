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
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

class LeadAlertDispatcher:
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
        pub_date = lead.get("published_date", "2026-08-25")
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
        if lead.get("opportunity_score", 0) >= 9.0:
            await cls.dispatch_email_alert(lead, recipient_emails)
