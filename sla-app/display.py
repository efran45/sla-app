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

    if "First Response" in summary.sla_name:
        desc_text = (
            "Showing all LA Blue ACS tickets measuring time from creation to the first "
            "public comment (any author, including automations). "
            "Elapsed = business days from ACS creation to first public comment (or to now if none yet)."
        )
    elif "Identification" in summary.sla_name:
        desc_text = (
            "Showing all LA Blue ACS tickets and their linked LPM tickets. "
            "Tickets without an LPM link that are closed, resolved, or canceled are excluded. "
            "Days = ACS creation → first time the linked LPM ticket reached 'Ready for Config' status "
            "(or to today if not yet reached)."
        )
    elif "Resolution" in summary.sla_name:
        desc_text = (
            "Showing all LA Blue ACS tickets and their linked LPM tickets. "
            "Tickets without an LPM link that are closed, resolved, or canceled are excluded. "
            "Days = ACS creation → first time the linked LPM ticket reached 'Deployed to UAT', "
            "'Waiting for UAT Signoff', or 'Done' status (or to today if not yet reached)."
        )
    else:
        desc_text = ""

    console.print(Align.center(Text(desc_text, style="dim", justify="center"), width=min(term_width, 100)))
    console.print()

    is_first_response = "First Response" in summary.sla_name
    is_resolution = "Resolution of" in summary.sla_name

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
    ticket_table.add_column("ACS Category", style="dim", no_wrap=True)
    ticket_table.add_column("ACS Created", no_wrap=True, min_width=18)
    if not is_first_response:
        ticket_table.add_column("LPM Ticket", no_wrap=True, min_width=10)
        ticket_table.add_column("LPM Category", style="dim", no_wrap=True)
    if is_first_response:
        date_col_name = "First Comment Date"
    elif is_resolution:
        date_col_name = "LPM Status Date"
    else:
        date_col_name = "LPM Status Date"
    ticket_table.add_column(date_col_name, no_wrap=True, min_width=18)
    ticket_table.add_column("Elapsed" if is_first_response else "Days", justify="right", no_wrap=True, min_width=8)
    ticket_table.add_column("Status", justify="center", no_wrap=True, min_width=11)
    ticket_table.add_column("Source of ID", style="dim", no_wrap=True)

    def ticket_sort_key(r):
        parts = r.source_ticket.rsplit("-", 1)
        return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0

    sorted_results = sorted(summary.results, key=ticket_sort_key, reverse=True)

    datetime_fmt = "%b %d, %Y %I:%M %p"
    date_fmt = "%b %d, %Y"

    for i, result in enumerate(sorted_results, 1):
        if result.is_met:
            status = "[green]Met[/]"
        elif result.is_breached:
            status = "[red]Breached[/]"
        else:
            status = "[yellow]In Progress[/]"

        if result.elapsed_time_str:
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

        if is_first_response:
            acs_created = result.created_date.strftime(datetime_fmt) if result.created_date else "--"
            comment_date = result.resolved_date.strftime(datetime_fmt) if result.resolved_date else "[dim]--[/]"
            ticket_table.add_row(
                str(i),
                result.source_ticket,
                result.category_migrated or "[dim]--[/]",
                acs_created,
                comment_date,
                days_str,
                status,
                result.source_of_identification or "[dim]--[/]",
            )
        else:
            target = result.target_ticket or "[dim]--[/]"
            acs_created = result.created_date.strftime(date_fmt) if result.created_date else "--"
            lpm_date = result.resolved_date.strftime(date_fmt) if result.resolved_date else "[dim]--[/]"
            ticket_table.add_row(
                str(i),
                result.source_ticket,
                result.category_migrated or "[dim]--[/]",
                acs_created,
                target,
                result.lpm_category or "[dim]--[/]",
                lpm_date,
                days_str,
                status,
                result.source_of_identification or "[dim]--[/]",
            )

    console.print(ticket_table)
    console.print()


def display_fix_version_tickets(version_data: list[dict]):
    """Display LPM fix version tickets with linked keys when no SR sub-tasks are found."""
    console.print(Panel(
        Text(
            "No SR sub-tasks found linked to any LPM tickets.\n"
            "Showing all LA Blue LPM tickets in recent fix versions with their linked ticket keys.",
            justify="center",
            style="yellow",
        ),
        title="[yellow]Impact Report Delivery — No SR Sub-tasks Found[/]",
        box=box.HEAVY,
        border_style="yellow",
        padding=(1, 2),
        expand=True,
    ))
    console.print()

    if not version_data:
        console.print("[dim]  No LPM tickets found in any fix version.[/]")
        console.print()
        return

    for entry in version_data:
        version = entry["version"]
        tickets = entry["tickets"]

        version_name = version.get("name", "Unknown")
        release_date = version.get("releaseDate", "No date set")
        released = version.get("released", False)
        status_label = "[green]Released[/]" if released else "[yellow]Unreleased[/]"

        console.print(
            f"[bold cyan]{version_name}[/]  {status_label}  "
            f"[dim]Release date: {release_date}[/]  [dim]({len(tickets)} ticket{'s' if len(tickets) != 1 else ''})[/]"
        )
        console.print()

        if not tickets:
            console.print("  [dim]No LA Blue tickets in this version.[/]")
            console.print()
            continue

        table = Table(
            box=box.SIMPLE_HEAVY,
            show_lines=False,
            header_style="bold cyan",
            padding=(0, 1),
            expand=True,
        )
        table.add_column("LPM Ticket", style="bold white", no_wrap=True, min_width=12)
        table.add_column("Status", no_wrap=True, min_width=14)
        table.add_column("Summary", min_width=30)
        table.add_column("Linked Tickets", min_width=20)

        for ticket in tickets:
            linked_str = "  ".join(ticket["linked_keys"]) if ticket["linked_keys"] else "[dim]none[/]"
            table.add_row(
                ticket["key"],
                ticket["status"],
                ticket["summary"] or "[dim]--[/]",
                linked_str,
            )

        console.print(table)
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
    console.print(f"[cyan]i[/] {message}")


def display_success(message: str):
    """Display a success message."""
    console.print(f"[green]v[/] {message}")
