import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from models.schemas import SessionStats, ProspectAnalysis

console = Console()

class TerminalDashboard:
    def __init__(self):
        self.console = console

    def display_banner(self):
        banner_text = Text()
        banner_text.append("════════════════════════════════════════════════════════════════════\n", style="bold cyan")
        banner_text.append("   INSTAGRAM REEL INDIVIDUAL PROFILE INVESTIGATION AGENT\n", style="bold white")
        banner_text.append("      (Autonomous Visual Computer-Use Profile Investigator)\n", style="italic cyan")
        banner_text.append("════════════════════════════════════════════════════════════════════", style="bold cyan")
        self.console.print(Panel(banner_text, border_style="cyan"))

    def display_session_stats(self, stats: SessionStats):
        table = Table(title="[bold green]📊 LIVE SESSION STATISTICS[/bold green]", border_style="green", expand=True)
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Count", style="bold yellow", justify="right")

        table.add_row("Reels Inspected", str(stats.reels_inspected))
        table.add_row("Comments Read", str(stats.comments_read))
        table.add_row("Individual Profiles Opened", str(stats.profiles_opened))
        table.add_row("Profiles with Message Buttons", str(stats.profiles_with_message_buttons))
        table.add_row("Explicit DM Invitations", str(stats.explicit_dm_invitations))
        table.add_row("Interested (No DM Permission)", str(stats.interested_without_dm_permission))
        table.add_row("Unavailable Profiles", str(stats.unavailable_profiles))
        table.add_row("Do-Not-Contact Profiles", str(stats.do_not_contact_profiles))
        table.add_row("[bold bright_green]Eligible Conversations[/bold bright_green]", f"[bold bright_green]{stats.eligible_conversations}[/bold bright_green]")
        table.add_row("Questions Prepared", str(stats.questions_prepared))
        table.add_row("Questions Sent", str(stats.questions_sent))

        self.console.print(table)

    def display_prospect_card(self, analysis: ProspectAnalysis):
        decision_styles = {
            "ELIGIBLE": "bold green",
            "INTERESTED_BUT_NO_PERMISSION": "yellow",
            "NOT_INTERESTED": "dim white",
            "UNAVAILABLE": "red",
            "DO_NOT_CONTACT": "bold red",
            "UNCERTAIN": "magenta"
        }
        dec_style = decision_styles.get(analysis.decision.value, "white")

        card = Table.grid(padding=1)
        card.add_column(style="bold cyan", width=18)
        card.add_column(style="white")

        card.add_row("Username:", f"@{analysis.username}")
        card.add_row("Reel ID:", analysis.reel_id)
        card.add_row("Comment:", f'"{analysis.comment_text}"')
        card.add_row("Intent:", analysis.comment_intent.value)
        card.add_row("Msg Available:", analysis.message_availability.value)
        card.add_row("DM Permission:", analysis.dm_permission.value)
        card.add_row("Decision:", Text(analysis.decision.value, style=dec_style))
        card.add_row("Reasoning:", analysis.reasoning)

        if analysis.suggested_question:
            card.add_row("[bold bright_green]Suggested Q:[/bold bright_green]", f"[italic bright_green]{analysis.suggested_question}[/italic bright_green]")

        self.console.print(Panel(card, title=f"Investigation Result: @{analysis.username}", border_style=dec_style))

dashboard = TerminalDashboard()
