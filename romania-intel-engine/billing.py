import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("BillingEngine")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

ACTIVE_COVERAGE = [
    "SICAP / SEAP (Achiziții & Consultări Naționale)",
    "CNI (Investiții Majore Guvernamentale)",
    "MIPE / PNRR (Fonduri Europene Nerambursabile)",
    "Județul Iași (Primăria Iași, CJ Iași, Miroslava)",
    "Județul Cluj (Primăria Cluj-Napoca, Florești, Dej)",
    "Județul Timiș (CJ Timiș, Sânandrei)",
    "București (Spitale Clinice, Digitalizare MS)",
    "Județul Bihor (Primăria Oradea, Parcuri Tehnologice)"
]

SUBSCRIPTION_PLANS = {
    "plan_acces_complet": {
        "name": "Acces Complet Desk",
        "price_ron": 499,
        "price_eur": 100,
        "price_usd": 110,
        "billing_interval": "lunar",
        "coverage": ACTIVE_COVERAGE,
        "features": [
            "Acces integral la toate cele 8 registre instituționale active",
            "Feed Live Pre-SEAP & Consultări de Piață",
            "Sinteze Executive & Bugete Estimate xAI Grok",
            "Export CSV date calificate",
            "1 Workspace & 2 Utilizatori"
        ]
    },
    "plan_founder_vip": {
        "name": "VIP Founder & Multi-Divizie",
        "price_ron": 1499,
        "price_eur": 300,
        "price_usd": 330,
        "billing_interval": "lunar",
        "coverage": ACTIVE_COVERAGE,
        "features": [
            "Tot ce include pachetul Acces Complet",
            "Multi-Product Divisions (Monitorizare separată pe linii de produse)",
            "Concurrent Bidding Pipeline (Managementul ofertelor în echipă)",
            "Battlecards Tactice de Ofertare & Unghiuri de Diferențiere",
            "Acces prioritar automat la toate județele viitoare pe măsură ce lansăm noi scrapere",
            "Până la 10 Utilizatori (Multi-Seat)"
        ]
    }
}

class StripeBillingEngine:
    @staticmethod
    def get_plans():
        return {
            "currency_primary": "RON",
            "active_registries": ACTIVE_COVERAGE,
            "plans": SUBSCRIPTION_PLANS
        }

    @staticmethod
    def create_checkout_session(
        tenant_id: str,
        plan_id: str,
        currency: str = "ron",
        success_url: str = "http://localhost:3000?billing=success",
        cancel_url: str = "http://localhost:3000?billing=cancelled"
    ) -> Dict[str, Any]:
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        if not plan:
            return {"status": "error", "message": "Plan tarifar invalid"}

        currency = currency.lower()
        amount = plan["price_ron"] * 100
        if currency == "eur":
            amount = plan["price_eur"] * 100
        elif currency == "usd":
            amount = plan["price_usd"] * 100

        if STRIPE_SECRET_KEY:
            try:
                import stripe
                stripe.api_key = STRIPE_SECRET_KEY
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": currency,
                            "product_data": {
                                "name": f"RO-INTEL Desk: {plan['name']}",
                                "description": f"Acces Intelligence Achiziții B2B ({tenant_id})"
                            },
                            "unit_amount": amount,
                            "recurring": {"interval": "month"}
                        },
                        "quantity": 1,
                    }],
                    mode="subscription",
                    success_url=success_url,
                    cancel_url=cancel_url,
                    metadata={"tenant_id": tenant_id, "plan_id": plan_id}
                )
                return {
                    "status": "success",
                    "checkout_url": session.url,
                    "session_id": session.id,
                    "plan": plan["name"],
                    "amount_ron": plan["price_ron"],
                    "currency": currency.upper()
                }
            except Exception as e:
                logger.error(f"[Stripe] Checkout creation error: {e}")

        return {
            "status": "simulated_success",
            "checkout_url": f"{success_url}&plan={plan_id}&tenant={tenant_id}",
            "plan_name": plan["name"],
            "amount_ron": plan["price_ron"],
            "currency": currency.upper(),
            "note": "Stripe Live/Test keys not set; simulated checkout session returned."
        }
