"""
Terminal display using Rich library
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.columns import Columns
from rich import box

from sla_calculator import SLASummary, SLAResult


console = Console()


def display_sla_dashboard(summary: SLASummary):
    """Display the SLA dashboard in the terminal."""
    term_width = console.size.width

    # Header panel
    header = Panel(
        Text(summary.sla_name, justify="center", style="bold white"),
        subtitle=f"Target: {summary.target_days} Business Days",
        box=box.HEAVY,
        style="blue",
        padding=(1, 2),
        expand=True,
    )
    console.print(header)
    console.print()

    # Summary metrics as side-by-side panels sized to terminal
    resolved_count = summary.met_count + summary.breached_count
    panel_width = max(12, (term_width - 10) // 4)

    met_panel = Panel(
        Text(str(summary.met_count), justify="center", style="green bold"),
        title="[green]Met[/]",
        box=box.ROUNDED,
        border_style="green",
        width=panel_width,
    )
    breached_panel = Panel(
        Text(str(summary.breached_count), justify="center", style="red bold"),
        title="[red]Breached[/]",
        box=box.ROUNDED,
        border_style="red",
        width=panel_width,
    )
    progress_panel = Panel(
        Text(str(summary.in_progress_count), justify="center", style="yellow bold"),
        title="[yellow]In Progress[/]",
        box=box.ROUNDED,
        border_style="yellow",
        width=panel_width,
    )
    total_panel = Panel(
        Text(str(summary.total_count), justify="center", style="bold"),
        title="Total",
        box=box.ROUNDED,
        width=panel_width,
    )

    console.print(Align.center(Columns([met_panel, breached_panel, progress_panel, total_panel], padding=(0, 1))))

    if resolved_count > 0:
        rate = summary.compliance_rate
        rate_style = "green" if rate >= 90 else "yellow" if rate >= 75 else "red"
        console.print(Align.center(
            Text.from_markup(f"Compliance Rate: [{rate_style} bold]{rate:.1f}%[/]  [dim]({summary.met_count} of {resolved_count} resolved tickets met SLA)[/]")
        ))

    console.print()

    # Description of what's shown (varies by SLA type)
    if "First Response" in summary.sla_name:
        desc_text = (
            "Showing all BCBSLA ACS tickets measuring time from creation to the first "
            "public comment by an internal (Atlassian) user. "
            "Elapsed = calendar days/hours/minutes from ACS creation to first response (or to now if no response yet)."
        )
    elif "Identification" in summary.sla_name:
        desc_text = (
            "Showing all BCBSLA ACS tickets that either have a linked LPM ticket "
            "with category \"break fix\", or are still open and awaiting an LPM link. "
            "Tickets without an LPM link that are closed, resolved, or canceled are excluded. "
            "Days = ACS creation to LPM creation (or to today if still awaiting a link)."
        )
    else:
        desc_text = (
            "Showing all BCBSLA ACS tickets that either have a linked LPM ticket "
            "that reached \"ready to build\" status, or are still open and awaiting resolution. "
            "Tickets without an LPM link that are closed, resolved, or canceled are excluded. "
            "Days = ACS creation to the date the LPM ticket entered \"ready to build\" (or to today if unresolved)."
        )

    console.print(Align.center(Text(desc_text, style="dim", justify="center"), width=min(term_width, 100)))
    console.print()

    # Detailed ticket table — use no_wrap and min_width to keep rows on one line
    ticket_table = Table(
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold cyan",
        row_styles=["", "dim"],
        padding=(0, 1),
        expand=True,
    )

    ticket_table.add_column("#", style="dim", justify="right", no_wrap=True, min_width=3)
    ticket_table.add_column("ACS Ticket", style="bold white", no_wrap=True, min_width=10)
    ticket_table.add_column("ACS Created", no_wrap=True, min_width=12)
    ticket_table.add_column("LPM Ticket", no_wrap=True, min_width=10)
    ticket_table.add_column("LPM Date", no_wrap=True, min_width=12)
    ticket_table.add_column("Days", justify="right", no_wrap=True, min_width=8)
    ticket_table.add_column("Status", justify="center", no_wrap=True, min_width=11)
    ticket_table.add_column("Category", style="dim", no_wrap=True)
    ticket_table.add_column("Source of ID", style="dim", no_wrap=True)

    # Sort results by ticket number (highest first)
    def ticket_sort_key(r):
        parts = r.source_ticket.rsplit("-", 1)
        return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0

    sorted_results = sorted(summary.results, key=ticket_sort_key, reverse=True)

    for i, result in enumerate(sorted_results, 1):
        if result.is_met:
            status = "[green]Met[/]"
        elif result.is_breached:
            status = "[red]Breached[/]"
        else:
            status = "[yellow]In Progress[/]"

        if result.elapsed_time_str:
            # Show d/h/m format for first response SLA
            if result.days_elapsed > result.target_days:
                days_str = f"[red bold]{result.elapsed_time_str}[/]"
            elif result.days_elapsed > result.target_days * 0.8:
                days_str = f"[yellow]{result.elapsed_time_str}[/]"
            else:
                days_str = f"[green]{result.elapsed_time_str}[/]"
        elif result.days_elapsed > result.target_days:
            days_str = f"[red bold]{result.days_elapsed}[/][dim]/{result.target_days}[/]"
        elif result.days_elapsed > result.target_days * 0.8:
            days_str = f"[yellow]{result.days_elapsed}[/][dim]/{result.target_days}[/]"
        else:
            days_str = f"[green]{result.days_elapsed}[/][dim]/{result.target_days}[/]"

        target = result.target_ticket or "[dim]--[/]"
        acs_created = result.created_date.strftime("%b %d, %Y") if result.created_date else "--"
        lpm_date = result.resolved_date.strftime("%b %d, %Y") if result.resolved_date else "[dim]--[/]"

        ticket_table.add_row(
            str(i),
            result.source_ticket,
            acs_created,
            target,
            lpm_date,
            days_str,
            status,
            result.category_migrated or "[dim]--[/]",
            result.source_of_identification or "[dim]--[/]",
        )

    console.print(ticket_table)
    console.print()


def display_error(message: str):
    """Display an error message."""
    console.print(Panel(
        Text(message, style="red"),
        title="Error",
        box=box.ROUNDED,
        border_style="red",
    ))


def display_info(message: str):
    """Display an info message."""
    console.print(f"[cyan]ℹ[/] {message}")


def display_success(message: str):
    """Display a success message."""
    console.print(f"[green]✓[/] {message}")
