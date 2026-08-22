import json
from rich.console import Console
from rich.table import Table

from src.database.models import init_db, get_db_connection
from src.ai.processor import RomanianIntelAIProcessor

console = Console()

def run_ai_analysis():
    console.print("[bold green]======================================================[/bold green]")
    console.print("[bold green] ROMANIA B2B INTEL: AI REFINEMENT & QUALITY SCORING   [/bold green]")
    console.print("[bold green]======================================================[/bold green]")

    init_db()

    processor = RomanianIntelAIProcessor()
    processed_count = processor.process_pending_records(limit=250)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, opportunity_score, county, entity_name, project_title, financial_value_ron, trade_tags, sales_pitch_angle 
        FROM structured_intel 
        WHERE opportunity_score >= 7
        ORDER BY financial_value_ron DESC 
        LIMIT 10
    """)
    top_leads = cursor.fetchall()
    conn.close()

    if top_leads:
        table = Table(title=f"\nActionable Commercial Dossiers Generated (Total: {processed_count})")
        table.add_column("Score", style="bold yellow", justify="center")
        table.add_column("County", style="magenta")
        table.add_column("Entity / Developer", style="green")
        table.add_column("Project Title", style="white")
        table.add_column("Value / Status", style="bold cyan", justify="right")
        table.add_column("Trade Sectors", style="blue")
        table.add_column("Tactical Action Plan", style="dim")

        for row in top_leads:
            cat, score, county, entity, title, val_ron, raw_tags, action = row
            score_str = f"⭐ {score}/10"
            
            if val_ron:
                val_str = f"{val_ron:,.0f} RON"
            elif cat == "urbanism":
                val_str = "Autorizație AC"
            elif cat == "grants":
                val_str = "Ghid Finanțare UE"
            else:
                val_str = "Achiziție Publică"

            tags_list = json.loads(raw_tags)
            tags_display = ", ".join(tags_list[:2])
            
            table.add_row(
                score_str,
                county,
                entity[:25],
                title[:35] + "...",
                val_str,
                tags_display,
                action[:55] + "..."
            )

        console.print(table)

if __name__ == "__main__":
    run_ai_analysis()