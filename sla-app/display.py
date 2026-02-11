"""
Terminal display using Rich library
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from sla_calculator import SLASummary, SLAResult


console = Console()


def display_sla_dashboard(summary: SLASummary):
    """Display the SLA dashboard in the terminal."""

    # Header panel
    header = Panel(
        Text(summary.sla_name, justify="center", style="bold white"),
        subtitle=f"Target: {summary.target_days} Business Days",
        box=box.DOUBLE,
        style="blue",
    )
    console.print(header)
    console.print()

    # Summary metrics
    metrics_table = Table(show_header=False, box=None, padding=(0, 4))
    metrics_table.add_column("label", style="dim")
    metrics_table.add_column("value", justify="right")

    met_style = "green bold"
    breached_style = "red bold"
    progress_style = "yellow bold"

    metrics_table.add_row("✓ Met", f"[{met_style}]{summary.met_count}[/]")
    metrics_table.add_row("✗ Breached", f"[{breached_style}]{summary.breached_count}[/]")
    metrics_table.add_row("◷ In Progress", f"[{progress_style}]{summary.in_progress_count}[/]")
    metrics_table.add_row("", "")
    metrics_table.add_row("Total", f"[bold]{summary.total_count}[/]")

    resolved_count = summary.met_count + summary.breached_count
    if resolved_count > 0:
        compliance_style = "green" if summary.compliance_rate >= 90 else "yellow" if summary.compliance_rate >= 75 else "red"
        metrics_table.add_row("Compliance Rate", f"[{compliance_style}]{summary.compliance_rate:.1f}%[/]")

    console.print(Panel(metrics_table, title="Summary", box=box.ROUNDED))
    console.print()

    # Detailed ticket table
    ticket_table = Table(
        title="Ticket Details",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold cyan",
    )

    ticket_table.add_column("Source (ACS)", style="white")
    ticket_table.add_column("ACS Created", style="dim")
    ticket_table.add_column("Source of ID", style="white")
    ticket_table.add_column("Target (LPM)", style="white")
    ticket_table.add_column("LPM Created", style="dim")
    ticket_table.add_column("Days", justify="right")
    ticket_table.add_column("Status", justify="center")

    # Sort results: newest to oldest by ACS created date
    sorted_results = sorted(
        summary.results,
        key=lambda r: r.created_date,
        reverse=True  # Newest first
    )

    for result in sorted_results:
        # Format status
        if result.is_met:
            status = "[green]✓ Met[/]"
        elif result.is_breached:
            status = "[red]✗ Breached[/]"
        else:
            status = "[yellow]◷ In Progress[/]"

        # Format days with color
        if result.days_elapsed > result.target_days:
            days_str = f"[red]{result.days_elapsed}[/]"
        elif result.days_elapsed > result.target_days * 0.8:
            days_str = f"[yellow]{result.days_elapsed}[/]"
        else:
            days_str = f"[green]{result.days_elapsed}[/]"

        target = result.target_ticket or "[dim]--[/]"

        # Format dates
        acs_created = result.created_date.strftime("%Y-%m-%d") if result.created_date else "--"
        lpm_created = result.resolved_date.strftime("%Y-%m-%d") if result.resolved_date else "--"

        ticket_table.add_row(
            result.source_ticket,
            acs_created,
            result.source_of_identification or "[dim]--[/]",
            target,
            lpm_created,
            days_str,
            status,
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
