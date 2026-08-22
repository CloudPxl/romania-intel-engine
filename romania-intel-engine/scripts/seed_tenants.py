import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")

import psycopg2
from rich.console import Console

console = Console()

def seed():
    pg_url = os.getenv("DATABASE_URL")
    if not pg_url:
        console.print("[bold red]DATABASE_URL not found in .env[/bold red]")
        return

    console.print(f"[cyan]Connecting to Supabase PostgreSQL at [bold]{pg_url.split('@')[-1]}[/bold]...[/cyan]")
    conn = psycopg2.connect(pg_url, connect_timeout=10)
    cursor = conn.cursor()

    sample_tenants = [
        {
            "id": "t1_infra_transilvania",
            "company_name": "SC Infra Construct Transilvania SRL",
            "fiscal_code_cui": "RO38491023",
            "email": "licitatii@infraconstruct.ro",
            "phone": "+40740112233",
            "tier": "enterprise",
            "counties": ["Cluj", "Bihor", "Salaj", "Maramures", "National"],
            "tags": ["infrastructura_drumuri_asfalt", "constructii_civile_industriale", "demolari_si_dezafectari"],
            "min_val": 100000.0,
            "min_score": 7
        },
        {
            "id": "t2_medtech_bucuresti",
            "company_name": "SC MedTech Pharma Distribution SRL",
            "fiscal_code_cui": "RO29481944",
            "email": "sales@medtechdist.ro",
            "phone": "+40722334455",
            "tier": "enterprise",
            "counties": ["Bucuresti", "Ilfov", "Prahova", "Brasov", "National"],
            "tags": ["echipamente_medicale_pharma"],
            "min_val": 25000.0,
            "min_score": 6
        },
        {
            "id": "t3_vest_consulting_grants",
            "company_name": "SC Vest Project Consulting SRL",
            "fiscal_code_cui": "RO41928374",
            "email": "contact@vestconsulting.ro",
            "phone": "+40755998877",
            "tier": "standard",
            "counties": ["Timis", "Arad", "Caras-Severin", "Vest", "National"],
            "tags": ["fonduri_ue_granturi_imm", "energie_regenerabila_fotovoltaic"],
            "min_val": 0.0,
            "min_score": 7
        }
    ]

    for t in sample_tenants:
        cursor.execute("""
            INSERT INTO tenants (id, company_name, fiscal_code_cui, contact_email, contact_phone, tier, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (id) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                contact_email = EXCLUDED.contact_email
        """, (t["id"], t["company_name"], t["fiscal_code_cui"], t["email"], t["phone"], t["tier"]))

        cursor.execute("""
            INSERT INTO tenant_filters (tenant_id, allowed_counties, subscribed_trade_tags, min_financial_value_ron, min_opportunity_score)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                allowed_counties = EXCLUDED.allowed_counties,
                subscribed_trade_tags = EXCLUDED.subscribed_trade_tags,
                min_financial_value_ron = EXCLUDED.min_financial_value_ron,
                min_opportunity_score = EXCLUDED.min_opportunity_score
        """, (t["id"], json.dumps(t["counties"]), json.dumps(t["tags"]), t["min_val"], t["min_score"]))

    conn.commit()
    conn.close()
    console.print("[bold green][✓] 3 Client Tenants successfully configured in Supabase PostgreSQL.[/bold green]")

if __name__ == "__main__":
    seed()
