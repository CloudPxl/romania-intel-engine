import asyncio
import signal
import time
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.database.models import init_db, get_db_connection
from src.scrapers.registry import registry
from src.scrapers.sources.seap_consultations import SeapMarketConsultationAdapter
from src.scrapers.sources.cluj_urbanism import ClujUrbanismAdapter
from src.scrapers.sources.adr_national import NationalAdrHubAdapter
from src.scrapers.sources.mipe_oportunitati import MipeOportunitatiAdapter
from src.scrapers.sources.datagov_ro import DataGovRoAdapter
from src.ai.processor import RomanianIntelAIProcessor
from src.matching.engine import MultiTenantMatchmaker

console = Console()
RUNNING = True

def handle_shutdown(signum, frame):
    global RUNNING
    console.print("\n[bold red][!] Shutdown signal received. Gracefully stopping workers...[/bold red]")
    RUNNING = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

async def run_adapter_worker(adapter, semaphore: asyncio.Semaphore):
    async with semaphore:
        return await adapter.execute_safe()

async def autonomous_247_engine():
    console.print(Panel.fit(
        "[bold green]ROMANIA B2B INTEL ENGINE: 24/7 AUTONOMOUS PRODUCTION DAEMON[/bold green]\n"
        "[dim]Ingestion • AI Entity Resolution • Multi-Tenant Matchmaking[/dim]",
        border_style="green"
    ))

    # 1. Initialize DB with WAL mode & Foreign Keys
    init_db()

    # 2. Register Active High-Yield Scrapers
    # Register Complete Ingestion Suite
    registry.register(SeapMarketConsultationAdapter(min_value_ron=50000.0, page_size=50))
    registry.register(SeapDirectAwardsAdapter(min_value_ron=25000.0))
    registry.register(ClujUrbanismAdapter())
    registry.register(BucurestiUrbanismAdapter())
    registry.register(ApmEnvironmentalAdapter())
    registry.register(NationalAdrHubAdapter())
    registry.register(MipeOportunitatiAdapter())
    registry.register(DataGovRoAdapter())

    adapters = registry.get_all()
    ai_engine = RomanianIntelAIProcessor()
    matchmaker = MultiTenantMatchmaker()

    console.print(f"[cyan][✓] Registered {len(adapters)} data sources, AI processor, and matchmaking engine.[/cyan]\n")

    semaphore = asyncio.Semaphore(3)
    cycle_count = 0

    while RUNNING:
        cycle_count += 1
        now = time.time()
        console.print(f"[bold yellow]════════════════════════════════════════════════════════════════════════[/bold yellow]")
        console.print(f"[bold yellow]>>> CYCLE #{cycle_count} | {time.strftime('%Y-%m-%d %H:%M:%S')} <<<[/bold yellow]")

        # --- STAGE 1: INGESTION ---
        tasks = []
        for adapter in adapters:
            time_since_last_run = (now - adapter.last_run_timestamp) / 60.0
            if adapter.last_run_timestamp == 0 or time_since_last_run >= adapter.poll_interval_minutes:
                tasks.append(run_adapter_worker(adapter, semaphore))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_ingested = sum(len(r) for r in results if isinstance(r, list))
            console.print(f"[green][✓ Stage 1: Ingestion] Scraped {total_ingested} new raw records.[/green]")
        else:
            console.print("[dim][Stage 1: Ingestion] Adapters on cooldown.[/dim]")

        # --- STAGE 2: AI REFINEMENT & STRUCTURING ---
        structured_count = ai_engine.process_pending_records(limit=150)
        console.print(f"[green][✓ Stage 2: AI Engine] Formatted & scored {structured_count} commercial dossiers.[/green]")

        # --- STAGE 3: MULTI-TENANT MATCHMAKING ---
        matches = matchmaker.run_matchmaking()
        total_dispatched = sum(len(leads) for leads in matches.values())
        console.print(f"[green][✓ Stage 3: Matchmaking] Routed {total_dispatched} high-value leads to client queues.[/green]")

        # --- STAGE 4: TELEMETRY & LIVE DATABASE SNAPSHOT ---
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Summary counts
        cursor.execute("SELECT category, COUNT(*) FROM structured_intel GROUP BY category")
        summary = cursor.fetchall()
        
        # Top 5 highest opportunity leads
        cursor.execute("""
            SELECT category, opportunity_score, county, entity_name, project_title, financial_value_ron, trade_tags
            FROM structured_intel 
            WHERE opportunity_score >= 7
            ORDER BY financial_value_ron DESC, opportunity_score DESC 
            LIMIT 5
        """)
        top_leads = cursor.fetchall()
        conn.close()

        if summary:
            summary_table = Table(title=f"Database Ledger State (Cycle #{cycle_count})", show_header=True)
            summary_table.add_column("Category", style="cyan")
            summary_table.add_column("Verified Commercial Leads", style="bold green", justify="right")
            for cat, count in summary:
                summary_table.add_row(cat, str(count))
            console.print(summary_table)

        if top_leads:
            leads_table = Table(title="Top High-Score Commercial Leads", show_header=True)
            leads_table.add_column("Score", style="bold yellow", justify="center")
            leads_table.add_column("County", style="magenta")
            leads_table.add_column("Entity / Developer", style="green")
            leads_table.add_column("Project Scope", style="white")
            leads_table.add_column("Value / Status", style="bold cyan", justify="right")
            leads_table.add_column("Trade Tag", style="blue")

            for row in top_leads:
                cat, score, county, entity, title, val_ron, raw_tags = row
                val_str = f"{val_ron:,.0f} RON" if val_ron else ("Autorizație AC" if cat == "urbanism" else "Ghid Finanțare UE")
                tags_list = json.loads(raw_tags)
                tag_display = tags_list[0].replace("_", " ") if tags_list else "general"

                leads_table.add_row(
                    f"⭐ {score}/10",
                    county,
                    entity[:22],
                    title[:32] + "...",
                    val_str,
                    tag_display
                )
            console.print(leads_table)

        console.print("[dim]Cycle finished. Sleeping for 60s... (Press Ctrl+C to stop)[/dim]\n")
        
        # Responsive sleep loop
        for _ in range(12):
            if not RUNNING:
                break
            await asyncio.sleep(5)

    console.print("[bold green][✓] Engine shut down cleanly with 0 database locks.[/bold green]")

if __name__ == "__main__":
    asyncio.run(autonomous_247_engine())