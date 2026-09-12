import os
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("BillingEngine")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://ro-intel.xyz")

# Annual price as a multiple of the monthly one. 10 = two months free,
# which is the usual SaaS shape; an explicit constant rather than a magic
# 0.833 discount buried in an f-string.
ANNUAL_MONTHS_CHARGED = int(os.getenv("ANNUAL_MONTHS_CHARGED", "10"))

# Optional. When a plan has a real Stripe Price id configured, checkout
# uses it; when it does not, checkout builds the price inline via
# price_data (see create_checkout_session).
#
# That fallback is the difference between "works as soon as a test API key
# exists" and "works once someone has also created four Price objects in
# the dashboard and copied their ids here". Inline price_data is fully
# supported for mode="subscription", so nothing is lost by starting there;
# real Price ids are still preferred once they exist, because coupons,
# Stripe-side reporting and price changes without a redeploy all key off
# them.
STRIPE_PRICE_IDS = {
    ("plan_acces_complet", "monthly"): os.getenv("STRIPE_PRICE_ACCES_LUNAR", ""),
    ("plan_acces_complet", "annual"): os.getenv("STRIPE_PRICE_ACCES_ANUAL", ""),
    ("plan_founder_vip", "monthly"): os.getenv("STRIPE_PRICE_VIP_LUNAR", ""),
    ("plan_founder_vip", "annual"): os.getenv("STRIPE_PRICE_VIP_ANUAL", ""),
}


def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)

B2B_BANK_DETAILS = {
    "beneficiary": "RO-INTEL PROCUREMENT INTELLIGENCE SRL",
    "bank_name": "Banca Transilvania",
    "iban_ron": "RO49BTRL00000000000000RO",
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
            "Acces complet la toate cele 8 registre active (SICAP, CNI, MIPE, Judete)",
            "Feed Live Pre-SEAP & Consultari de Piata",
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
            "Camere VIP Specializate (Aparare & Securitate, M&A GovCon)",
            "Multi-Product Divisions (Monitorizare separata pe linii de produse)",
            "Scanner Clauze Restrictive & Caiete de Sarcini (PDF/DOCX)",
            "Simulator Sanse de Castig & Marja Optima",
            "Generator Adrese Oficiale Legea 544 & Legea 98",
            "Copilot AI Interactiv Nelimitat",
            "Pana la 10 Locuri utilizatori"
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
        plan_id: str,
        company_name: str,
        cui_fiscal: str,
        billing_email: str,
        billing_address: Optional[str] = "Romania"
    ) -> Dict[str, Any]:
        plan = SUBSCRIPTION_PLANS.get(plan_id, SUBSCRIPTION_PLANS["plan_founder_vip"])
        invoice_number = f"RO-INTEL-2026-{int(time.time()) % 100000:05d}"
        issue_date = datetime.now().strftime("%d.%m.%Y")
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
                    <div class="title">FACTURA PROFORMA</div>
                    <div>Seria / Numar: <b>{invoice_number}</b></div>
                    <div>Data emiterii: <b>{issue_date}</b></div>
                </div>
                <div style="text-align: right;">
                    <div style="font-weight: bold; font-size: 18px; color: #0284c7;">RO-INTEL DESK</div>
                    <div>Inteligenta B2B Achizitii Publice</div>
                    <div>https://ro-intel.xyz</div>
                </div>
            </div>

            <div class="grid">
                <div class="box">
                    <b style="color: #64748b;">FURNIZOR:</b><br>
                    <b>RO-INTEL INTELLIGENCE SRL</b><br>
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
                        <th>Perioada</th>
                        <th style="text-align: right;">Total RON</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>1</td>
                        <td><b>Abonament Platforma: {plan['name']}</b><br><span style="color: #64748b; font-size: 11px;">Acces feed pre-SEAP, consultari de piata, radar AI Grok si instrumente de ofertare.</span></td>
                        <td>1 Luna</td>
                        <td style="text-align: right; font-weight: bold;">{total_amount:,.2f} RON</td>
                    </tr>
                </tbody>
            </table>

            <div class="total">Total de Plata: {total_amount:,.2f} RON</div>

            <div class="bank-box">
                <b style="color: #0369a1;">INSTRUCTIUNI DE PLATA PRIN ORDIN DE PLATA (OP):</b><br>
                Banca: <b>{B2B_BANK_DETAILS['bank_name']}</b><br>
                IBAN RON: <b>{B2B_BANK_DETAILS['iban_ron']}</b><br>
                Beneficiar: <b>{B2B_BANK_DETAILS['beneficiary']}</b><br>
                Detalii Plata: <b>{B2B_BANK_DETAILS['payment_details_prefix']}{invoice_number} ({cui_fiscal})</b><br><br>
                <i>Contul dvs. se activeaza automat la confirmarea platii sau la transmiterea OP-ului catre desk@ro-intel.xyz.</i>
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
    def price_for(plan_id: str, interval: str) -> int:
        """Amount in RON for one billing period."""
        plan = SUBSCRIPTION_PLANS.get(plan_id, SUBSCRIPTION_PLANS["plan_founder_vip"])
        monthly = int(plan["price_ron"])
        return monthly * ANNUAL_MONTHS_CHARGED if interval == "annual" else monthly

    @staticmethod
    def create_checkout_session(
        plan_id: str,
        interval: str = "monthly",
        user_id: Optional[str] = None,
        customer_email: Optional[str] = None,
        stripe_customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """A real Stripe Hosted Checkout session, or an honest refusal.

        Returns `status: "unavailable"` — never a fabricated URL — when no
        API key is configured, so the frontend can fall back to the proforma
        flow that has always worked instead of sending the user to a dead
        link. That is the same honest-degradation contract the rest of this
        codebase uses for an unconfigured dependency.
        """
        if plan_id not in SUBSCRIPTION_PLANS:
            return {"status": "error", "message": f"Plan necunoscut: {plan_id}"}
        if interval not in ("monthly", "annual"):
            return {"status": "error", "message": f"Interval necunoscut: {interval}"}

        plan = SUBSCRIPTION_PLANS[plan_id]
        amount_ron = StripeBillingEngine.price_for(plan_id, interval)

        if not stripe_configured():
            return {
                "status": "unavailable",
                "message": (
                    "Plata prin card în curs de activare — contactați suportul "
                    "pentru factură proformă."
                ),
                "plan_id": plan_id,
                "interval": interval,
                "amount_ron": amount_ron,
            }

        try:
            import stripe
        except ImportError:
            logger.error("[Billing] stripe SDK not installed.")
            return {"status": "unavailable", "message": "Modulul de plată nu este disponibil."}

        stripe.api_key = STRIPE_SECRET_KEY
        configured_price = STRIPE_PRICE_IDS.get((plan_id, interval)) or ""

        if configured_price:
            line_item: Dict[str, Any] = {"price": configured_price, "quantity": 1}
        else:
            line_item = {
                "quantity": 1,
                "price_data": {
                    "currency": "ron",
                    # Stripe amounts are in the currency's smallest unit —
                    # bani for RON. Sending 499 here would charge 4,99 RON.
                    "unit_amount": amount_ron * 100,
                    "recurring": {"interval": "year" if interval == "annual" else "month"},
                    "product_data": {
                        "name": f"RO-INTEL — {plan['name']}",
                        "description": "Acces la registrul de oportunități pre-SEAP și instrumentele de ofertare.",
                    },
                },
            }

        params: Dict[str, Any] = {
            "mode": "subscription",
            "line_items": [line_item],
            "success_url": f"{APP_BASE_URL}/abonament?status=succes&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{APP_BASE_URL}/abonament?status=anulat",
            "locale": "ro",
            "allow_promotion_codes": True,
            # Both, deliberately. client_reference_id survives onto the
            # session; metadata is copied onto the subscription as well, so
            # a later subscription.* event can still be traced back to a
            # user without a customer-id lookup.
            "client_reference_id": user_id or "",
            "metadata": {"user_id": user_id or "", "plan_id": plan_id, "interval": interval},
            "subscription_data": {
                "metadata": {"user_id": user_id or "", "plan_id": plan_id, "interval": interval}
            },
        }
        # Passing an existing customer keeps one person to one Stripe
        # customer across renewals; customer_email is only for a first
        # purchase (Stripe rejects both together).
        if stripe_customer_id:
            params["customer"] = stripe_customer_id
        elif customer_email:
            params["customer_email"] = customer_email

        try:
            session = stripe.checkout.Session.create(**params)
        except Exception as e:
            logger.error(f"[Billing] Stripe checkout session failed: {e}")
            return {
                "status": "error",
                "message": "Sesiunea de plată nu a putut fi creată. Reîncercați sau solicitați o proformă.",
            }

        return {
            "status": "success",
            "checkout_url": session.url,
            "session_id": session.id,
            "plan_id": plan_id,
            "interval": interval,
            "amount_ron": amount_ron,
        }
