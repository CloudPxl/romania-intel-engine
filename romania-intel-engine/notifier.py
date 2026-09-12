import os
import html as html_module
import logging
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
from urllib.parse import quote
import httpx

from matching_engine import ALERT_THRESHOLD

logger = logging.getLogger("AlertDispatcher")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@ro-intel.xyz")
NOTIFICATION_EMAIL_TO = os.getenv("NOTIFICATION_EMAIL_TO", "director@infraconstruct.ro,office@ro-intel.xyz")

# Resend (https://resend.com) is the primary transport, SMTP the fallback.
#
# Called over its REST API with the httpx client this module already
# imports, rather than the `resend` SDK: the SDK is a thin synchronous
# wrapper over exactly this one POST, and adding it would mean either a
# blocking call inside the event loop or another asyncio.to_thread hop, for
# no behaviour this file does not already have.
#
# Why a provider API at all when SMTP exists here: SMTP from Render's free
# tier is unreliable in the specific way that hurts most — outbound :587 is
# frequently blocked or heavily throttled by hosts, and the failure is a
# timeout rather than a rejection, so it looks like a hang, not a
# misconfiguration. An HTTPS POST is not subject to that.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "RO-INTEL <alerts@ro-intel.xyz>")
RESEND_API_URL = "https://api.resend.com/emails"

# Where an alert's call-to-action points. The source URL still appears in
# the body, but the button goes into the app: the dossier there carries the
# score, the match reasons and the pipeline action, none of which exist on
# the authority's own page.
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://ro-intel.xyz")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")


def _format_ron(value: Optional[float]) -> str:
    """Romanian money formatting, and the zero-fabrication rule applied to
    it: an unpublished estimate is not '0,0 Mil. RON'.

    The previous template rendered a missing budget as "0.0 Mil. RON",
    which states as fact that the contract is worth nothing — a materially
    different claim from "the authority did not publish a figure", and the
    opposite of what the product tells users everywhere else.
    """
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        return "Nepublicată"

    def _ro(number: str) -> str:
        """en-US '1,234.56' -> ro-RO '1.234,56'. Applied to the NUMBER only,
        never to the whole string: doing it after the unit is appended also
        rewrites the full stop in 'Mil.' and yields '24,50 Mil, RON'."""
        return number.replace(",", "\x00").replace(".", ",").replace("\x00", ".")

    if amount >= 1_000_000:
        return f"{_ro(f'{amount / 1_000_000:,.2f}')} Mil. RON"
    return f"{_ro(f'{amount:,.0f}')} RON"

def build_lead_alert_email(
    lead: Dict[str, Any], match_info: Optional[Dict[str, Any]] = None
) -> tuple:
    """(subject, html, text) for one lead alert.

    A module-level function rather than a method so the template can be
    asserted against directly in tests without a transport.

    Every interpolated value is escaped. This is not theoretical: the whole
    body is scraped from third-party government portals, and a title
    containing `&`, `<` or a stray tag (Romanian institutional CMSs emit
    both) previously went into the HTML raw — at best breaking the layout of
    the message, at worst injecting markup into the recipient's mail client.

    Layout is table-based with inline styles, which is not a stylistic
    choice: Gmail strips <style> blocks in several contexts and Outlook's
    Word renderer ignores most float/flex CSS, so a <div>-and-classes
    template renders as an unstyled column in exactly the clients business
    users read mail in. The one <style> block carries only the mobile media
    query, which is additive — the message is already single-column and
    readable at 320px if it is dropped.
    """
    esc = html_module.escape

    title = (lead.get("project_title") or "Oportunitate nouă").strip()
    entity = (lead.get("entity_name") or "Autoritate contractantă").strip()
    county = (lead.get("county") or "România").strip()
    locality = (lead.get("locality") or "").strip()
    where = f"{locality}, {county}" if locality and locality != county else county
    sub_cat = (lead.get("sub_category") or lead.get("category") or "General").strip()
    deadline = (lead.get("action_deadline") or "").strip() or "Nepublicat"
    summary = (lead.get("executive_summary") or "").strip()
    source_id = (lead.get("source_id") or "").strip()
    source_url = (lead.get("source_url") or APP_BASE_URL).strip()
    budget = _format_ron(lead.get("financial_value_ron") or lead.get("estimated_value_ron"))
    score = match_info.get("score") if match_info else lead.get("opportunity_score")
    try:
        score_text = f"{float(score):.1f}/10"
    except (TypeError, ValueError):
        score_text = "—"
    reasons = [r for r in ((match_info or {}).get("reasons") or []) if r][:4]

    dossier_url = (
        f"{APP_BASE_URL}/cautare-avansata?openLead={quote(source_id, safe='')}"
        if source_id else APP_BASE_URL
    )

    budget_line = budget if budget != "Nepublicată" else "Nepublicată"
    subject = f"[RO-INTEL] {title[:70]} — {budget_line} ({county})"

    text_lines = [
        f"RO-INTEL — oportunitate nouă (scor {score_text})",
        "",
        f"Obiect: {title}",
        f"Autoritate: {entity}",
        f"Locație: {where}",
        f"Valoare estimată: {budget}",
        f"Termen limită: {deadline}",
    ]
    if reasons:
        text_lines += ["", "De ce v-a fost trimisă:"] + [f"  - {r}" for r in reasons]
    if summary:
        text_lines += ["", "Sinteză:", summary]
    text_lines += ["", f"Dosar complet: {dossier_url}", f"Sursă oficială: {source_url}"]
    text_body = "\n".join(text_lines)

    reasons_html = ""
    if reasons:
        items = "".join(
            f'<tr><td style="padding:2px 0;font:400 13px/1.5 Arial,sans-serif;color:#3d4852;">'
            f'<span style="color:#6c63ff;">&#9679;</span>&nbsp;{esc(r)}</td></tr>'
            for r in reasons
        )
        reasons_html = f"""
              <tr><td style="padding:16px 0 0 0;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
                       style="background:#f1f3f8;border-left:3px solid #6c63ff;border-radius:6px;">
                  <tr><td style="padding:12px 14px;">
                    <div style="font:700 11px/1 Arial,sans-serif;color:#6b7280;letter-spacing:.08em;
                                text-transform:uppercase;padding-bottom:8px;">De ce v-a fost trimisă</div>
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0">{items}</table>
                  </td></tr>
                </table>
              </td></tr>"""

    summary_html = ""
    if summary:
        summary_html = (
            f'<tr><td style="padding:16px 0 0 0;font:400 14px/1.6 Arial,sans-serif;color:#55606b;">'
            f"{esc(summary[:600])}</td></tr>"
        )

    def _spec(label: str, value: str, strong: bool = False) -> str:
        weight = "700" if strong else "500"
        color = "#3d4852" if not strong else "#6c63ff"
        return f"""
                  <tr>
                    <td class="spec-l" style="padding:7px 0;font:700 11px/1.4 Arial,sans-serif;color:#6b7280;
                        letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;" width="42%">{label}</td>
                    <td class="spec-v" style="padding:7px 0;font:{weight} 14px/1.4 Arial,sans-serif;
                        color:{color};" align="right">{value}</td>
                  </tr>"""

    html_body = f"""<!DOCTYPE html>
<html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title[:120])}</title>
<style>
  @media only screen and (max-width:480px) {{
    .wrap {{ padding:12px !important; }}
    .card {{ padding:20px 16px !important; }}
    .title {{ font-size:19px !important; }}
    .spec-l, .spec-v {{ display:block !important; width:100% !important; text-align:left !important; padding:2px 0 !important; }}
    .spec-v {{ padding-bottom:10px !important; }}
    .btn a {{ display:block !important; }}
  }}
</style></head>
<body style="margin:0;padding:0;background:#e0e5ec;-webkit-text-size-adjust:100%;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#e0e5ec;">
  <tr><td class="wrap" align="center" style="padding:24px 12px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600"
           style="width:100%;max-width:600px;">
      <tr><td style="padding:0 0 12px 4px;font:800 14px/1 Arial,sans-serif;color:#3d4852;letter-spacing:-.01em;">
        RO&#8209;INTEL
        <span style="font-weight:400;color:#6b7280;">&nbsp;Registrul Oportunităților Publice</span>
      </td></tr>
      <tr><td class="card" style="background:#f5f7fa;border-radius:16px;padding:26px 24px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr><td>
            <span style="display:inline-block;background:#eceafe;color:#6c63ff;border-radius:20px;
                         padding:5px 12px;font:700 11px/1 Arial,sans-serif;letter-spacing:.06em;
                         text-transform:uppercase;">{esc(sub_cat[:44])}</span>
          </td></tr>
          <tr><td class="title" style="padding:14px 0 0 0;font:700 21px/1.35 Arial,sans-serif;color:#3d4852;">
            {esc(title[:200])}
          </td></tr>
          <tr><td style="padding:6px 0 0 0;font:400 13px/1.5 Arial,sans-serif;color:#6b7280;">
            {esc(entity[:120])} &bull; {esc(where[:60])}
          </td></tr>
          <tr><td style="padding:18px 0 0 0;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
                   style="border-top:1px solid #dfe3ea;border-bottom:1px solid #dfe3ea;">
              {_spec("Valoare estimată", esc(budget), strong=True)}
              {_spec("Termen limită", esc(deadline))}
              {_spec("Scor oportunitate", esc(score_text))}
            </table>
          </td></tr>{reasons_html}{summary_html}
          <tr><td class="btn" style="padding:22px 0 0 0;">
            <a href="{esc(dossier_url)}"
               style="display:inline-block;background:#6c63ff;color:#ffffff;text-decoration:none;
                      font:700 14px/1 Arial,sans-serif;padding:14px 26px;border-radius:12px;">
              Deschide dosarul complet
            </a>
          </td></tr>
          <tr><td style="padding:14px 0 0 0;font:400 12px/1.5 Arial,sans-serif;">
            <a href="{esc(source_url)}" style="color:#6b7280;">Document oficial la sursă &#8599;</a>
          </td></tr>
        </table>
      </td></tr>
      <tr><td style="padding:14px 4px 0 4px;font:400 11px/1.6 Arial,sans-serif;color:#6b7280;">
        Ați primit acest mesaj pentru că această oportunitate corespunde criteriilor din profilul dvs.
        RO&#8209;INTEL. Pragul de alertă și adresa de notificare se modifică în
        <a href="{esc(APP_BASE_URL)}" style="color:#6c63ff;">Setări cont</a>.
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

    return subject, html_body, text_body


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
        if recipients:
            # Through send_email, so operator alerts get the Resend transport
            # too rather than being the one path still pinned to SMTP.
            sent = await cls.send_email(
                recipients,
                "[RO-INTEL] Alertă Sistem",
                f"<pre style=\"font:400 13px/1.6 monospace;color:#3d4852;white-space:pre-wrap;\">"
                f"{html_module.escape(text)}</pre>",
                text,
            )
            if sent:
                return True
        # Every live channel is unconfigured or failed. Every caller of this
        # method only wraps it in try/except and never inspects the boolean
        # return, so without this the alert would vanish with nothing to
        # show for it anywhere — persist it so GET /api/v1/system/sources
        # still surfaces it to whoever checks later.
        logger.error(f"[AlertDispatcher] All admin-alert channels failed/unconfigured: {text[:200]}")
        import db
        try:
            await db.record_system_alert(text)
        except Exception as e:
            logger.error(f"[AlertDispatcher] Failed to persist undelivered admin alert: {e}")
        return False

    @staticmethod
    async def _send_via_resend(to_emails: List[str], subject: str, html_body: str, text_body: str) -> bool:
        """Primary email transport. Returns False (never raises) when
        unconfigured or rejected, so the caller falls through to SMTP."""
        if not RESEND_API_KEY:
            return False
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": RESEND_FROM_EMAIL,
                        "to": to_emails,
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                )
            if resp.status_code in (200, 201):
                logger.info(f"✅ Resend accepted email to {to_emails}")
                return True
            # 403 here is almost always the one setup mistake worth naming:
            # Resend only allows arbitrary recipients once a sending domain
            # is verified, and until then silently restricts you to your own
            # address. That reads as "email is broken" without this line.
            logger.error(
                f"❌ Resend rejected email to {to_emails}: {resp.status_code} {resp.text[:200]}"
                + (" — is RESEND_FROM_EMAIL's domain verified?" if resp.status_code == 403 else "")
            )
            return False
        except Exception as e:
            logger.error(f"❌ Resend request failed: {e}")
            return False

    @classmethod
    async def send_email(cls, to_emails: List[str], subject: str, html_body: str, text_body: str) -> bool:
        """The single email entry point: Resend first, SMTP second.

        Every caller in this module goes through here rather than reaching
        for a transport directly, so adding, reordering or removing one is a
        change in this method alone. Returns True only if a transport
        actually accepted the message — the honest-failure contract
        _send_email_sync established, extended across both.
        """
        if not to_emails:
            return False
        if await cls._send_via_resend(to_emails, subject, html_body, text_body):
            return True
        return await asyncio.to_thread(cls._send_email_sync, to_emails, subject, html_body, text_body)

    @staticmethod
    def _send_email_sync(to_emails: List[str], subject: str, html_body: str, text_body: str) -> bool:
        if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
            logger.warning(f"[Email] SMTP_HOST/SMTP_USER/SMTP_PASSWORD not set — email alert not sent. To: {to_emails} | Subject: {subject}")
            return False
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
    async def dispatch_email_alert(
        cls,
        lead: Dict[str, Any],
        recipient_emails: Optional[List[str]] = None,
        match_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        recipients = recipient_emails or [e.strip() for e in NOTIFICATION_EMAIL_TO.split(",") if e.strip()]
        if not recipients:
            return False

        subject, html_body, text_body = build_lead_alert_email(lead, match_info)
        return await cls.send_email(recipients, subject, html_body, text_body)

    @classmethod
    async def dispatch_high_priority_alert(cls, lead: Dict[str, Any], recipient_emails: Optional[List[str]] = None):
        """Legacy, non-personalised path — kept for the old batch job in
        daemon.py while it still exists. New code should use
        dispatch_lead_alert_to_user instead."""
        from ai_refinery import HIGH_PRIORITY_SCORE

        if lead.get("opportunity_score", 0) >= HIGH_PRIORITY_SCORE:
            await cls.dispatch_email_alert(lead, recipient_emails)

    @classmethod
    async def dispatch_lead_alert_to_user(
        cls, lead: Dict[str, Any], profile: Dict[str, Any], match_info: Dict[str, Any]
    ) -> Dict[str, bool]:
        """Per-user, per-channel-idempotent alert dispatch for the streaming
        pipeline (orchestrator.run_tick).

        Takes the profile itself rather than looking it up: the tick loads
        every profile once per run and passes them down, so there is no
        per-signal query here and — more importantly — no module-level
        config cache to go stale.

        Telegram and email fire independently, so one failing doesn't block
        the other, and a channel is only recorded as dispatched once it
        actually succeeded.
        """
        import db

        user_id = profile.get("id")
        if not user_id:
            return {"telegram": False, "email": False}

        # `.get(..., default)` would only fall back when the key is absent,
        # but min_alert_score is present-and-None for a profile whose column
        # is NULL. That previously compared a float against None and raised
        # TypeError on every match — caught by the tick's per-alert
        # try/except, so it silently dropped that user's alerts entirely
        # rather than failing loudly.
        min_score = profile.get("min_alert_score")
        if min_score is None:
            min_score = ALERT_THRESHOLD
        if match_info.get("score", 0) < min_score:
            return {"telegram": False, "email": False}

        source_id = lead.get("source_id", "")
        results = {"telegram": False, "email": False}

        chat_id = profile.get("telegram_chat_id")
        if chat_id and not await db.has_alert_been_dispatched(user_id, source_id, "telegram"):
            text = (
                f"🚨 <b>{lead.get('project_title', '')}</b>\n"
                f"{lead.get('entity_name', '')} ({lead.get('county', '')})\n"
                f"Scor: {match_info.get('score')}/10\n{lead.get('source_url', '')}"
            )
            if await cls.dispatch_telegram_message(chat_id, text):
                await db.record_alert_dispatch(user_id, source_id, "telegram")
                results["telegram"] = True

        alert_email = profile.get("alert_email")
        if alert_email and not await db.has_alert_been_dispatched(user_id, source_id, "email"):
            if await cls.dispatch_email_alert(lead, [alert_email], match_info=match_info):
                await db.record_alert_dispatch(user_id, source_id, "email")
                results["email"] = True

        return results
