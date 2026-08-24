import os
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("NotificationDispatcher")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

class HighPriorityNotifier:
    @staticmethod
    async def dispatch_vip_alert(lead: Dict[str, Any], tenant_name: str):
        val_mil = lead.get("financial_value_ron", 0) / 1_000_000
        score = lead.get("opportunity_score", 0)
        
        # 1. Dispatch Telegram Alert
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            msg = (
                f"🚨 <b>NOU DOSAR PRE-SEAP VIP (Scor: {score}/10)</b>\n\n"
                f"🏢 <b>Beneficiar:</b> {lead.get('entity_name')} ({lead.get('county')})\n"
                f"💰 <b>Buget Estimat:</b> {val_mil:.2f} Mil. RON\n"
                f"📂 <b>Titlu:</b> {lead.get('project_title')}\n"
                f"🎯 <b>Workspace Alocat:</b> {tenant_name}\n"
                f"⏳ <b>Lansare Est.:</b> {lead.get('estimated_timeline', {}).get('estimated_tender_launch', 'T4 2026')}\n\n"
                f"💡 <b>Tactică Ofertare:</b>\n{lead.get('sales_pitch_angle')}\n\n"
                f"🔗 <a href='{lead.get('source_url')}'>Acces Sursă Oficială</a>"
            )
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(url, json=payload)
                    logger.info(f"📨 [Telegram] VIP Alert dispatched for {lead.get('source_id')}")
            except Exception as e:
                logger.error(f"[Telegram] Failed to dispatch alert: {e}")

        # 2. Dispatch Slack / Teams / Discord Webhook
        if SLACK_WEBHOOK_URL:
            webhook_payload = {
                "text": f"🚨 *NOU DOSAR VIP (Scor {score}/10)*: {lead.get('project_title')} - {val_mil:.1f} Mil. RON ({lead.get('entity_name')})"
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(SLACK_WEBHOOK_URL, json=webhook_payload)
                    logger.info(f"📨 [Webhook] Alert sent to corporate channel.")
            except Exception as e:
                logger.error(f"[Webhook] Failed to dispatch: {e}")
