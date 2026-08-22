import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import List, Dict, Any, Optional
import httpx
from src.config import settings
from src.notifications.dossier import ClientDossierFormatter
from src.notifications.exporter import LeadExporter

class NotificationService:
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: str = "alerts@romania-intel.ro"
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_email = from_email

    async def send_webhook_alert(self, webhook_url: str, payload: Dict[str, Any]) -> bool:
        """Sends lead payload to tenant CRM / Zapier / Make / Slack webhook."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(webhook_url, json=payload)
                return res.status_code in [200, 201, 204]
        except Exception:
            return False

    def send_email_digest(
        self,
        to_email: str,
        company_name: str,
        matched_leads: List[Dict[str, Any]],
        attach_csv: bool = True
    ) -> bool:
        """Sends formatted intelligence briefing + optional CSV spreadsheet attachment."""
        if not self.smtp_host or not self.smtp_user:
            # Running in dry-run mode
            print(f"[DRY-RUN EMAIL] Digest generated for {company_name} ({len(matched_leads)} leads) -> {to_email}")
            return True

        try:
            subject = f"🎯 [{len(matched_leads)} Oportunități Noi] Raport Inteligență Comercială - {company_name}"
            body_text = ClientDossierFormatter.format_email_digest(company_name, matched_leads)

            msg = MIMEMultipart()
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg.attach(MIMEText(body_text, "plain", "utf-8"))

            if attach_csv and matched_leads:
                csv_data = LeadExporter.export_to_csv_string(matched_leads)
                part = MIMEApplication(csv_data.encode("utf-8-sig"), Name=f"Oportunitati_{company_name}.csv")
                part["Content-Disposition"] = f'attachment; filename="Oportunitati_{company_name}.csv"'
                msg.attach(part)

            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, to_email, msg.as_string())
            return True
        except Exception as e:
            print(f"[!] Email delivery failed for {to_email}: {e}")
            return False