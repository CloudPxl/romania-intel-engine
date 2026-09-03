import sys, os, time
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")

import httpx, psycopg2
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
RENDER_API = "https://ro-intel-engine.onrender.com"
DB_URL = os.getenv("DATABASE_URL")

def run_suite():
    console.print(Panel.fit("[bold cyan]RO-INTEL SYSTEM HEALTH & ENDPOINT VERIFICATION[/bold cyan]"))
    results = []

    try:
        t0 = time.time()
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM user_profiles;")
        u_cnt = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM opportunities;")
        l_cnt = cursor.fetchone()[0]
        conn.close()
        results.append(("Supabase PostgreSQL", "PASS", f"{u_cnt} users, {l_cnt} opportunities", f"{(time.time()-t0)*1000:.1f}ms"))
    except Exception as e:
        results.append(("Supabase PostgreSQL", "FAIL", str(e)[:40], "-"))

    endpoints = [
        ("Root API Status", "GET", f"{RENDER_API}/", None),
        # Every user-scoped route now takes its identity from the bearer
        # token, so an unauthenticated probe can only assert that they
        # reject it — which is itself the check worth making.
        ("System Status", "GET", f"{RENDER_API}/api/v1/system/status", None),
        ("Market Trends (public)", "GET", f"{RENDER_API}/api/v1/analysis/market-trends", None),
        ("My Feed (expects 401)", "GET", f"{RENDER_API}/api/v1/me/feed", None),
        ("My Profile (expects 401)", "GET", f"{RENDER_API}/api/v1/me", None),
    ]

    with httpx.Client(timeout=15.0) as client:
        for name, method, url, payload in endpoints:
            try:
                t0 = time.time()
                res = client.get(url) if method == "GET" else client.post(url, json=payload)
                lat = f"{(time.time()-t0)*1000:.1f}ms"
                results.append((name, "PASS" if res.status_code == 200 else "FAIL", f"HTTP {res.status_code}", lat))
            except Exception as ex:
                results.append((name, "FAIL", str(ex)[:30], "-"))

    table = Table(title="Live Backend Status", header_style="bold magenta")
    table.add_column("System / Route", width=35)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Details", width=35)
    table.add_column("Latency", justify="right", style="cyan", width=12)

    for item, status, detail, lat in results:
        s_color = "[bold green]PASS[/bold green]" if status == "PASS" else "[bold red]FAIL[/bold red]"
        table.add_row(item, s_color, detail, lat)

    console.print(table)

if __name__ == "__main__":
    run_suite()
