import sys
import asyncio
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from rich.console import Console
from rich.table import Table

from src.database.models import init_db, get_db_connection
from src.scrapers.sources.seap_consultations import SeapMarketConsultationAdapter
from src.scrapers.sources.seap_direct_awards import SeapDirectAwardsAdapter
from src.scrapers.sources.cluj_urbanism import ClujUrbanismAdapter
from src.scrapers.sources.bucuresti_urbanism import BucurestiUrbanismAdapter
from src.scrapers.sources.apm_environment import ApmEnvironmentalAdapter
from src.scrapers.sources.adr_national import NationalAdrHubAdapter
from src.scrapers.sources.mipe_oportunitati import MipeOportunitatiAdapter
from src.scrapers.sources.datagov_ro import DataGovRoAdapter
from src.ai.processor import RomanianIntelAIProcessor
from src.matching.engine import MultiTenantMatchmaker

console = Console()

async def main():
    init_db()
    console.print("[bold green]======================================================[/bold green]")
    console.print("[bold green] ROMANIA B2B INTEL: 8-SOURCE LIVE INGESTION & AI RUN  [/bold green]")
    console.print("[bold green]======================================================[/bold green]\n")

    adapters = [
        SeapMarketConsultationAdapter(min_value_ron=50000.0, page_size=25),
        SeapDirectAwardsAdapter(min_value_ron=20000.0),
        ClujUrbanismAdapter(),
        BucurestiUrbanismAdapter(),
        ApmEnvironmentalAdapter(),
        NationalAdrHubAdapter(),
        MipeOportunitatiAdapter(),
        DataGovRoAdapter()
    ]

    console.print("[bold cyan][1/3] Polling 8 Data Sources Across Romania...[/bold cyan]")
    total_ingested = 0
    for adapter in adapters:
        records = await adapter.execute_safe()
        total_ingested += len(records)
        console.print(f"  • {adapter.name}: [green]{len(records)} records[/green]")

    console.print(f"\n[bold cyan][2/3] Processing AI Structuring, Tags & Opportunity Scoring...[/bold cyan]")
    ai = RomanianIntelAIProcessor()
    scored_count = ai.process_pending_records(limit=400)
    console.print(f"  • [green]Refined {scored_count} Commercial Lead Dossiers[/green]")

    console.print(f"\n[bold cyan][3/3] Executing Multi-Tenant Matchmaking Engine...[/bold cyan]")
    matchmaker = MultiTenantMatchmaker()
    matches = matchmaker.run_matchmaking()
    for tenant_id, leads in matches.items():
        console.print(f"  • Tenant [{tenant_id[:8]}...] -> [green]{len(leads)} matched leads[/green]")

    # Telemetry View
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, opportunity_score, county, entity_name, project_title, financial_value_ron, trade_tags 
        FROM structured_intel 
        WHERE opportunity_score >= 7
        ORDER BY financial_value_ron DESC, opportunity_score DESC
        LIMIT 8
    """)
    top_records = cursor.fetchall()
    conn.close()

    if top_records:
        table = Table(title="\nTop High-Yield Verified Leads (Score >= 7)")
        table.add_column("Score", style="bold yellow", justify="center")
        table.add_column("Category", style="cyan")
        table.add_column("County", style="magenta")
        table.add_column("Entity / Developer", style="green")
        table.add_column("Project Scope", style="white")
        table.add_column("Est. Value", style="bold cyan", justify="right")

        for row in top_records:
            cat, score, county, entity, title, val_ron, tags = row
            val_display = f"{val_ron:,.0f} RON" if val_ron else "Aviz / AC Emisă"
            table.add_row(
                f"⭐ {score}/10",
                cat,
                county,
                entity[:22],
                title[:35] + "...",
                val_display
            )
        console.print(table)

if __name__ == "__main__":
    asyncio.run(main())
