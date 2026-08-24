import os
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("BillingEngine")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Official RO-INTEL B2B Bank Details for Ordin de Plata (OP)
B2B_BANK_DETAILS = {
    "beneficiary": "RO-INTEL PROCUREMENT INTELLIGENCE",
    "bank_name": "Banca Transilvania / Revolut Business",
    "iban_ron": "RO98BTRL00000000000000XX",
    "swift_bic": "BTRLRO22",
    "payment_details_prefix": "Abonament RO-INTEL Desk ref: "
}

SUBSCRIPTION_PLANS = {
    "plan_acces_complet": {
        "name": "Acces Complet Desk",
        "price_ron": 499,
        "price_eur": 100,
        "billing_interval": "lunar",
        "features": [
            "Acces complet la toate cele 8 registre active (SICAP, CNI, MIPE, Județe)",
            "Feed Live Pre-SEAP & Consultări de Piață",
            "Sinteze Executive & Bugete Estimate xAI Grok",
            "Export CSV date calificate",
            "1 Workspace & 2 Locuri utilizatori"
        ]
    },
    "plan_founder_vip": {
        "name": "VIP Founder & Multi-Divizie",
        "price_ron": 1499,
        "price_eur": 300,
        "billing_interval": "lunar",
        "features": [
            "Tot ce include pachetul Acces Complet",
            "Camere VIP Specializate (Apărare & Securitate, M&A GovCon)",
            "Multi-Product Divisions (Monitorizare separată pe linii de produse)",
            "Scanner Clauze Restrictive & Caiete de Sarcini (PDF/DOCX)",
            "Simulator Șanse de Câștig & Marjă Optimă",
            "Generator Adrese Oficiale Legea 544 & Legea 98",
            "Copilot AI Interactiv Nelimitat",
            "Până la 10 Locuri utilizatori"
        ]
    }
}

class StripeBillingEngine:
    @staticmethod
    def get_plans():
        return {
            "currency_primary": "RON",
            "bank_transfer_available": True,
            "bank_details": B2B_BANK_DETAILS,
            "plans": SUBSCRIPTION_PLANS
        }

    @staticmethod
    def generate_proforma_invoice(
        tenant_id: str,
        plan_id: str,
        company_name: str,
        cui_fiscal: str,
        billing_email: str,
        billing_address: Optional[str] = "România"
    ) -> Dict[str, Any]:
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            return {"status": "error", "message": "Plan tarifar inexistent"}

        invoice_number = f"RO-INTEL-2026-{int(time.time()) % 100000:05d}"
        issue_date = datetime.now().strftime("%d.%m.%Y")
        due_date = datetime.now().strftime("%d.%m.%Y")
        total_amount = plan["price_ron"]

        proforma_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Factura Proforma {invoice_number}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; padding: 40px; }}
                .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #0284c7; padding-bottom: 20px; }}
                .title {{ font-size: 24px; font-weight: bold; color: #0369a1; }}
                .grid {{ display: flex; justify-content: space-between; margin-top: 30px; }}
                .box {{ width: 45%; font-size: 13px; line-height: 1.6; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 40px; font-size: 13px; }}
                th {{ background: #f1f5f9; padding: 12px; text-align: left; border-bottom: 2px solid #cbd5e1; }}
                td {{ padding: 12px; border-bottom: 1px solid #e2e8f0; }}
                .total {{ text-align: right; margin-top: 20px; font-size: 18px; font-weight: bold; color: #0f172a; }}
                .bank-box {{ background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 20px; margin-top: 30px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div>
                    <div class="title">FACTURĂ PROFORMĂ</div>
                    <div>Seria / Număr: <b>{invoice_number}</b></div>
                    <div>Data emiterii: <b>{issue_date}</b></div>
                </div>
                <div style="text-align: right;">
                    <div style="font-weight: bold; font-size: 18px; color: #0284c7;">RO-INTEL DESK</div>
                    <div>Inteligență B2B Achiziții Publice</div>
                    <div>https://ro-intel.xyz</div>
                </div>
            </div>

            <div class="grid">
                <div class="box">
                    <b style="color: #64748b;">FURNIZOR:</b><br>
                    <b>RO-INTEL INTELLIGENCE</b><br>
                    Email: billing@ro-intel.xyz<br>
                    Web: https://ro-intel.xyz
                </div>
                <div class="box">
                    <b style="color: #64748b;">CLIENT / BENEFICIAR:</b><br>
                    <b>{company_name}</b><br>
                    CUI / CIF: {cui_fiscal}<br>
                    Email Facturare: {billing_email}<br>
                    Sediu: {billing_address}
                </div>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Nr.</th>
                        <th>Descriere Serviciu</th>
                        <th>Perioadă</th>
                        <th style="text-align: right;">Total RON</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>1</td>
                        <td><b>Abonament Platformă: {plan['name']}</b><br><span style="color: #64748b; font-size: 11px;">Acces feed pre-SEAP, consultări de piață, radar AI Grok și instrumente de ofertare.</span></td>
                        <td>1 Lună</td>
                        <td style="text-align: right; font-weight: bold;">{total_amount:,.2f} RON</td>
                    </tr>
                </tbody>
            </table>

            <div class="total">Total de Plată: {total_amount:,.2f} RON</div>

            <div class="bank-box">
                <b style="color: #0369a1;">INSTRUCȚIUNI DE PLATĂ PRIN ORDIN DE PLATĂ (OP):</b><br>
                Banca: <b>{B2B_BANK_DETAILS['bank_name']}</b><br>
                IBAN RON: <b>{B2B_BANK_DETAILS['iban_ron']}</b><br>
                Beneficiar: <b>{B2B_BANK_DETAILS['beneficiary']}</b><br>
                Detalii Plată: <b>{B2B_BANK_DETAILS['payment_details_prefix']}{invoice_number} ({cui_fiscal})</b><br><br>
                <i>Contul dvs. se activează automat la confirmarea plății sau la transmiterea OP-ului către desk@ro-intel.xyz.</i>
            </div>
        </body>
        </html>
        """

        return {
            "status": "success",
            "invoice_number": invoice_number,
            "issue_date": issue_date,
            "total_ron": total_amount,
            "plan_name": plan["name"],
            "company_name": company_name,
            "cui_fiscal": cui_fiscal,
            "bank_details": B2B_BANK_DETAILS,
            "proforma_html": proforma_html
        }

    @staticmethod
    def create_checkout_session(tenant_id: str, plan_id: str, currency: str = "ron") -> Dict[str, Any]:
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            return {"status": "error", "message": "Plan tarifar invalid"}

        amount = plan["price_ron"] * 100

        if STRIPE_SECRET_KEY:
            try:
                import stripe
                stripe.api_key = STRIPE_SECRET_KEY
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": currency.lower(),
                            "product_data": {
                                "name": f"RO-INTEL Desk: {plan['name']}",
                                "description": f"Acces Enterprise B2B Procurement Intelligence ({tenant_id})"
                            },
                            "unit_amount": amount,
                            "recurring": {"interval": "month"}
                        },
                        "quantity": 1,
                    }],
                    mode="subscription",
                    success_url="https://ro-intel.xyz?billing=success",
                    cancel_url="https://ro-intel.xyz?billing=cancelled",
                    metadata={"tenant_id": tenant_id, "plan_id": plan_id}
                )
                return {
                    "status": "success",
                    "checkout_url": session.url,
                    "session_id": session.id,
                    "plan": plan["name"],
                    "amount_ron": plan["price_ron"]
                }
            except Exception as e:
                logger.error(f"[Stripe] Checkout creation error: {e}")

        # Fallback to direct proforma flow when Stripe live key is unconfigured
        return {
            "status": "proforma_required",
            "message": "Generați factura proformă pentru plată prin transfer bancar / Ordin de Plată (OP).",
            "plan_id": plan_id,
            "amount_ron": plan["price_ron"]
        }
