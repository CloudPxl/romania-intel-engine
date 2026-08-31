import asyncio
from rich.console import Console
from rich.table import Table

from src.database.models import init_db, get_db_connection
from src.scrapers.registry import registry
from src.scrapers.sources.seap_consultations import SeapMarketConsultationAdapter
from src.scrapers.sources.anpm_environment import AnpmEnvironmentAdapter
from src.scrapers.sources.adr_national import NationalAdrHubAdapter

console = Console()

async def run_pipeline():
    console.print("[bold green]================================================[/bold green]")
    console.print("[bold green] ROMANIA B2B INTELLIGENCE ENGINE: MULTI-SOURCE  [/bold green]")
    console.print("[bold green]================================================[/bold green]")

    init_db()

    registry.register(SeapMarketConsultationAdapter())
    registry.register(AnpmEnvironmentAdapter(county="Iasi", domain_code="apm-is"))
    registry.register(NationalAdrHubAdapter())

    adapters = registry.get_all()
    console.print(f"[cyan][*] Running {len(adapters)} active multi-source adapters...[/cyan]\n")

    total_new_records = 0
    for adapter in adapters:
        records = await adapter.execute_safe()
        total_new_records += len(records)

    console.print(f"\n[bold yellow]Pipeline Run Completed! New Records Ingested: {total_new_records}[/bold yellow]\n")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, county, institution, document_title, publication_date
        FROM raw_intel
        ORDER BY scraped_at DESC
        LIMIT 10
    """)
    recent_rows = cursor.fetchall()
    conn.close()

    if recent_rows:
        table = Table(title="Live Romanian Intelligence Database (All Channels)")
        table.add_column("Category", style="cyan", no_wrap=True)
        table.add_column("County / Region", style="magenta")
        table.add_column("Institution", style="green")
        table.add_column("Document Title", style="white")
        table.add_column("Date", style="dim")

        for row in recent_rows:
            table.add_row(row[0], row[1], row[2][:25], row[3][:45] + "...", str(row[4]))

        console.print(table)

if __name__ == "__main__":
    asyncio.run(run_pipeline())
