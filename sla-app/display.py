"""
Terminal display using Rich library
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich import box

from sla_calculator import SLASummary, SLAResult


console = Console()


def display_sla_dashboard(summary: SLASummary):
    """Display the SLA dashboard in the terminal."""

    # Header panel
    header = Panel(
        Text(summary.sla_name, justify="center", style="bold white"),
        subtitle=f"Target: {summary.target_days} Business Days",
        box=box.HEAVY,
        style="blue",
        padding=(1, 2),
    )
    console.print(header)
    console.print()

    # Summary metrics as side-by-side panels
    resolved_count = summary.met_count + summary.breached_count

    met_panel = Panel(
        Text(str(summary.met_count), justify="center", style="green bold"),
        title="[green]Met[/]",
        box=box.ROUNDED,
        border_style="green",
        width=16,
    )
    breached_panel = Panel(
        Text(str(summary.breached_count), justify="center", style="red bold"),
        title="[red]Breached[/]",
        box=box.ROUNDED,
        border_style="red",
        width=16,
    )
    progress_panel = Panel(
        Text(str(summary.in_progress_count), justify="center", style="yellow bold"),
        title="[yellow]In Progress[/]",
        box=box.ROUNDED,
        border_style="yellow",
        width=16,
    )
    total_panel = Panel(
        Text(str(summary.total_count), justify="center", style="bold"),
        title="Total",
        box=box.ROUNDED,
        width=16,
    )

    console.print(Columns([met_panel, breached_panel, progress_panel, total_panel], padding=(0, 1)))

    if resolved_count > 0:
        rate = summary.compliance_rate
        rate_style = "green" if rate >= 90 else "yellow" if rate >= 75 else "red"
        console.print(f"\n  Compliance Rate: [{rate_style} bold]{rate:.1f}%[/]  [dim]({summary.met_count} of {resolved_count} resolved tickets met SLA)[/]")

    console.print()

    # Description of what's shown (varies by SLA type)
    if "Identification" in summary.sla_name:
        console.print(Panel(
            "[dim]Showing all BCBSLA ACS tickets that either have a linked LPM ticket "
            "with category \"break fix\", or are still open and awaiting an LPM link.\n"
            "Tickets without an LPM link that are closed, resolved, or canceled are excluded.\n\n"
            "Days = ACS creation to LPM creation (or to today if still awaiting a link).[/]",
            title="[dim]What's below[/]",
            box=box.SIMPLE,
            padding=(0, 2),
        ))
    else:
        console.print(Panel(
            "[dim]Showing all BCBSLA ACS tickets that either have a linked LPM ticket "
            "that reached \"ready to build\" status, or are still open and awaiting resolution.\n"
            "Tickets without an LPM link that are closed, resolved, or canceled are excluded.\n\n"
            "Days = ACS creation to the date the LPM ticket entered \"ready to build\" (or to today if unresolved).[/]",
            title="[dim]What's below[/]",
            box=box.SIMPLE,
            padding=(0, 2),
        ))

    # Detailed ticket table
    ticket_table = Table(
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold cyan",
        row_styles=["", "dim"],
        padding=(0, 1),
    )

    ticket_table.add_column("#", style="dim", justify="right")
    ticket_table.add_column("ACS Ticket", style="bold white")
    ticket_table.add_column("ACS Created")
    ticket_table.add_column("LPM Ticket")
    ticket_table.add_column("LPM Date")
    ticket_table.add_column("Days", justify="right")
    ticket_table.add_column("Status", justify="center")
    ticket_table.add_column("Category", style="dim")
    ticket_table.add_column("Source of ID", style="dim")

    # Sort results: breached first, then in progress, then met; within each group newest first
    status_order = {"breached": 0, "in_progress": 1, "met": 2}
    sorted_results = sorted(
        summary.results,
        key=lambda r: (status_order.get(r.status, 3), -r.created_date.timestamp()),
    )

    for i, result in enumerate(sorted_results, 1):
        # Format status
        if result.is_met:
            status = "[green]Met[/]"
        elif result.is_breached:
            status = "[red]Breached[/]"
        else:
            status = "[yellow]In Progress[/]"

        # Format days with color and target reference
        if result.days_elapsed > result.target_days:
            days_str = f"[red bold]{result.days_elapsed}[/] [dim]/ {result.target_days}[/]"
        elif result.days_elapsed > result.target_days * 0.8:
            days_str = f"[yellow]{result.days_elapsed}[/] [dim]/ {result.target_days}[/]"
        else:
            days_str = f"[green]{result.days_elapsed}[/] [dim]/ {result.target_days}[/]"

        target = result.target_ticket or "[dim]--[/]"

        # Format dates
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
