#!/usr/bin/env python3
"""Onboards one real external client, by hand — the operational workflow
Part B of the tenant-isolation fix relies on instead of a self-serve
signup flow (deliberately not built: unnecessary for 10-20 hand-picked
companies, and out of scope for a $0-investment fix).

Unlike the since-deleted scripts/seed_tenants.py (confirmed dead, and
unsafe to run: it inserted synthetic user ids that aren't real Supabase
Auth UUIDs straight into `user_profiles`), this writes through db.py's
real asyncpg pool against the actual tenants/tenant_products/user_profiles
tables (tenants_schema.sql) — the same connection path the live API uses,
not a disconnected raw psycopg2 script.

Usage:
    python scripts/provision_tenant.py \\
        --tenant-id t4_acme_construct \\
        --company-name "SC Acme Construct SRL" \\
        --domain infrastructura \\
        --alert-email director@acme.ro \\
        --product-name "Divizia Infrastructura Rutiera" \\
        --target-counties Cluj,Timis \\
        --min-value-ron 3000000 \\
        --keywords drum,pod,asfalt,reabilitare \\
        --exclude-keywords curatenie,catering \\
        --user-id <the client's real Supabase Auth UUID> \\
        --user-email director@acme.ro

Find --user-id in the Supabase dashboard -> Authentication -> Users,
*after* the client has signed in at least once via Google/magic-link (the
row doesn't exist before their first real login). Re-running with the
same --tenant-id is safe (upserts); running again with a different
--product-name adds a second product line to an existing tenant rather
than replacing the first.

--user-id/--user-email are optional per-run — you can provision the
tenant/product config first and link a user to it later by re-running
with just --tenant-id, --user-id, and --user-email.
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import db  # noqa: E402


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _split_csv(value: Optional[str]) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


async def provision(args: argparse.Namespace) -> None:
    if not db.DATABASE_URL:
        print("DATABASE_URL is not set — nothing to write to. Aborting.", file=sys.stderr)
        sys.exit(1)

    async with db.with_connection() as conn:
        if conn is None:
            print("Could not obtain a database connection (see logs above). Aborting.", file=sys.stderr)
            sys.exit(1)

        async with conn.transaction():
            if args.company_name and args.domain:
                await conn.execute(
                    """
                    INSERT INTO tenants (id, company_name, primary_domain, alert_emails, telegram_chat_id, min_alert_score)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (id) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        primary_domain = EXCLUDED.primary_domain,
                        alert_emails = EXCLUDED.alert_emails,
                        telegram_chat_id = EXCLUDED.telegram_chat_id,
                        min_alert_score = EXCLUDED.min_alert_score
                    """,
                    args.tenant_id, args.company_name, args.domain,
                    _split_csv(args.alert_email), args.telegram_chat_id, args.min_alert_score,
                )
                print(f"  tenant '{args.tenant_id}' upserted.")

            if args.product_name:
                product_id = f"{args.tenant_id}_prod_{_slugify(args.product_name)}"
                await conn.execute(
                    """
                    INSERT INTO tenant_products (id, tenant_id, name, domain, target_counties, min_value_ron, keywords, exclude_keywords)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name, domain = EXCLUDED.domain,
                        target_counties = EXCLUDED.target_counties, min_value_ron = EXCLUDED.min_value_ron,
                        keywords = EXCLUDED.keywords, exclude_keywords = EXCLUDED.exclude_keywords
                    """,
                    product_id, args.tenant_id, args.product_name, args.domain or "infrastructura",
                    _split_csv(args.target_counties), args.min_value_ron,
                    _split_csv(args.keywords), _split_csv(args.exclude_keywords),
                )
                print(f"  product '{product_id}' upserted.")

            if args.user_id and args.user_email:
                await conn.execute(
                    """
                    INSERT INTO user_profiles (id, email, tenant_id, role)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (id) DO UPDATE SET
                        email = EXCLUDED.email, tenant_id = EXCLUDED.tenant_id, role = EXCLUDED.role,
                        updated_at = now()
                    """,
                    args.user_id, args.user_email, args.tenant_id, args.role,
                )
                print(f"  user '{args.user_email}' ({args.user_id}) linked to tenant '{args.tenant_id}'.")

    print("Done. Reload the live server's tenant cache with:")
    print('  curl -X POST "$RENDER_APP_URL/api/v1/admin/reload-tenants" -H "X-Admin-Secret: $TICK_SECRET"')
    print("(or restart the service — it reloads once at every startup regardless).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", required=True, help="e.g. t4_acme_construct")
    parser.add_argument("--company-name")
    parser.add_argument("--domain", help="infrastructura | sanatate | energie | aparare | digitalizare")
    parser.add_argument("--alert-email", help="comma-separated")
    parser.add_argument("--telegram-chat-id")
    parser.add_argument("--min-alert-score", type=float, default=7.5)
    parser.add_argument("--product-name")
    parser.add_argument("--target-counties", help="comma-separated Romanian county names")
    parser.add_argument("--min-value-ron", type=float, default=0.0)
    parser.add_argument("--keywords", help="comma-separated")
    parser.add_argument("--exclude-keywords", help="comma-separated")
    parser.add_argument("--user-id", help="the client's real Supabase Auth UUID (from the Supabase dashboard)")
    parser.add_argument("--user-email")
    parser.add_argument("--role", default="owner")
    args = parser.parse_args()

    if not any([args.company_name, args.product_name, (args.user_id and args.user_email)]):
        parser.error("Nothing to do — pass at least one of --company-name/--domain, --product-name, or --user-id+--user-email.")

    asyncio.run(provision(args))


if __name__ == "__main__":
    main()
