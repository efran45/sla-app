#!/usr/bin/env python3
"""
Healthcare SLA CLI - Main entry point

Just run: python main.py
For debug output: python main.py --verbose
"""
import argparse
import json
import sys
from pathlib import Path

from datetime import datetime
from rich.prompt import Prompt, Confirm
from rich.console import Console

from config import JIRA_FIELDS
from jira_client import JiraClient
from sla_checker import SLAChecker
from display import (
    console,
    display_sla_dashboard,
    display_error,
    display_info,
    display_success,
)

# Config file location (same directory as script)
CONFIG_FILE = Path(__file__).parent / ".config.json"


def load_config() -> dict:
    """Load saved configuration."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(config: dict):
    """Save configuration to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def prompt_for_credentials(config: dict) -> dict:
    """Prompt user for Jira credentials."""
    saved_url = config.get("jira_base_url", "")
    saved_email = config.get("jira_email", "")

    if saved_url and saved_email:
        # Saved credentials found — confirm or re-enter
        console.print("\n[bold]Saved Credentials[/]\n")
        console.print(f"  Jira URL: [cyan]{saved_url}[/]")
        console.print(f"  Email:    [cyan]{saved_email}[/]")
        console.print()

        if Confirm.ask("Use these credentials?", default=True):
            base_url = saved_url
            email = saved_email
        else:
            console.print()
            base_url = Prompt.ask("Jira URL", default=saved_url)
            email = Prompt.ask("Email", default=saved_email)
            config["jira_base_url"] = base_url
            config["jira_email"] = email
    else:
        # No saved credentials — prompt for everything
        console.print("\n[bold]Jira Credentials[/]\n")
        base_url = Prompt.ask(
            "Jira URL",
            default="https://yourcompany.atlassian.net"
        )
        email = Prompt.ask("Email")
        config["jira_base_url"] = base_url
        config["jira_email"] = email

    # Always prompt for token (don't save it for security)
    console.print()
    console.print("[dim]Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens[/]")
    token = Prompt.ask("API Token", password=True)

    return {
        "base_url": base_url,
        "email": email,
        "token": token,
    }


def prompt_for_date_range() -> tuple:
    """Prompt user for an optional date range to filter ACS tickets."""
    console.print("\n[bold]Date Range Filter[/]")
    console.print("[dim]Filter ACS tickets by creation date. Leave blank to include all tickets.[/]\n")

    date_from = Prompt.ask("Start date (YYYY-MM-DD)", default="").strip()
    date_to = Prompt.ask("End date   (YYYY-MM-DD)", default="").strip()

    # Validate dates
    for label, val in [("Start date", date_from), ("End date", date_to)]:
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                display_error(f"{label} '{val}' is not valid. Expected YYYY-MM-DD. Ignoring filter.")
                return None, None

    return (date_from or None), (date_to or None)


def run_sla_checks(client: JiraClient, verbose: bool = False, date_from: str = None, date_to: str = None):
    """Run all SLA checks and display results."""
    checker = SLAChecker(client, verbose=verbose, date_from=date_from, date_to=date_to)

    # Field IDs are loaded from config.py
    checker.set_field_id("health_plan", JIRA_FIELDS["health_plan"])
    checker.set_field_id("category", JIRA_FIELDS["category"])

    display_info("Fetching tickets from Jira...")
    console.print()

    # SLA 1: Identification of Resolution for Configuration Issues (30 days)
    summary1 = checker.check_identification_resolution_config()

    if summary1.total_count == 0:
        display_info("No tickets found matching the Identification SLA criteria.")
    else:
        display_sla_dashboard(summary1)

    console.rule("[dim]")
    console.print()

    # SLA 2: Resolution of Configuration Issues (60 days)
    summary2 = checker.check_resolution_config()

    if summary2.total_count == 0:
        display_info("No tickets found matching the Resolution SLA criteria.")
    else:
        display_sla_dashboard(summary2)


def main():
    parser = argparse.ArgumentParser(description="Healthcare SLA CLI")
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging to see JQL queries and field values"
    )
    args = parser.parse_args()

    console.print()
    console.rule("[bold blue]Healthcare SLA CLI[/]")
    console.print()
    console.print("[dim]1. Identification of Resolution for Configuration Issues | 30 Business Days[/]")
    console.print("[dim]2. Resolution of Configuration Issues | 60 Business Days[/]")
    console.print("[dim]ACS → LPM Handoff | BCBSLA[/]")
    console.print()

    if args.verbose:
        console.print("[yellow]Verbose mode enabled[/]\n")

    # Load saved config
    config = load_config()

    # Get credentials
    creds = prompt_for_credentials(config)

    # Test connection
    console.print()
    display_info("Connecting to Jira...")

    try:
        client = JiraClient(
            base_url=creds["base_url"],
            email=creds["email"],
            token=creds["token"],
        )
        user_info = client.test_connection()
        display_success(f"Connected as: {user_info.get('displayName', 'Unknown')}")
    except Exception as e:
        display_error(f"Connection failed: {e}")
        sys.exit(1)

    # Save config (without token)
    save_config(config)

    # Get optional date range
    date_from, date_to = prompt_for_date_range()

    # Run the SLA checks
    console.print()
    console.rule("[bold]SLA Results[/]")
    if date_from or date_to:
        range_str = f"{date_from or 'beginning'} to {date_to or 'now'}"
        console.print(f"\n[dim]Filtered to ACS tickets created: {range_str}[/]")
    console.print()

    try:
        run_sla_checks(client, verbose=args.verbose, date_from=date_from, date_to=date_to)
    except Exception as e:
        display_error(f"SLA check failed: {e}")
        sys.exit(1)

    console.print()


if __name__ == "__main__":
    main()
