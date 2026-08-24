import os, sys, json
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
    conn = psycopg2.connect(pg_url)
    cursor = conn.cursor()

    users = [
        ("usr_andrei_muresan", "andrei.muresan@infraconstruct.ro", "+40740112233", "Andrei Mureșan", "t1_infra_transilvania", "owner"),
        ("usr_elena_pop", "elena.pop@medtechdist.ro", "+40722334455", "Elena Pop", "t2_medtech_bucuresti", "bid_manager"),
        ("usr_radu_ionescu", "radu.ionescu@vestconsulting.ro", "+40755998877", "Radu Ionescu", "t3_vest_consulting_grants", "owner")
    ]

    for uid, email, phone, name, tenant_id, role in users:
        cursor.execute("""
            INSERT INTO user_profiles (id, email, phone, full_name, auth_provider, tenant_id, role)
            VALUES (%s, %s, %s, %s, 'email', %s, %s)
            ON CONFLICT (email) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                tenant_id = EXCLUDED.tenant_id,
                role = EXCLUDED.role
        """, (uid, email, phone, name, tenant_id, role))

    conn.commit()
    conn.close()
    console.print("[bold green][✓] User profiles seeded into Supabase successfully.[/bold green]")

if __name__ == "__main__":
    seed()
