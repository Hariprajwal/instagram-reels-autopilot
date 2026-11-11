import sys
import json
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from config.settings import SESSION_DATA_DIR

console = Console()
queue_file = SESSION_DATA_DIR / "queue.json"

def show_queue():
    console.print(Panel("[bold cyan]PROSPECT LEAD REVIEW QUEUE (ELIGIBLE PROSPECTS ONLY)[/bold cyan]", border_style="cyan"))

    if not queue_file.exists():
        console.print("[dim]No leads currently in queue.[/dim]")
        return

    try:
        with open(queue_file, "r", encoding="utf-8") as f:
            leads = json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading queue: {e}[/red]")
        return

    if not leads:
        console.print("[dim]Queue is currently empty.[/dim]")
        return

    table = Table(title="[bold green]Eligible Prospects Pending Operator Review[/bold green]", border_style="green", expand=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Username", style="bold cyan")
    table.add_column("Comment", style="white")
    table.add_column("Suggested Question (1-Question Rule)", style="italic green")
    table.add_column("Approved", style="bold yellow")

    for i, lead in enumerate(leads, 1):
        table.add_row(
            str(i),
            f"@{lead.get('username')}",
            f'"{lead.get("comment_text")}"',
            lead.get("suggested_question") or "N/A",
            "YES" if lead.get("approved_by_user") else "NO"
        )

    console.print(table)
    console.print("\n[yellow]Tip: All messages require your manual verification before dispatch.[/yellow]")

if __name__ == "__main__":
    show_queue()
