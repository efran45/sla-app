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

from rich.prompt import Prompt
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
    console.print("\n[bold]Jira Credentials[/]\n")

    # Show saved values as defaults
    saved_url = config.get("jira_base_url", "")
    saved_email = config.get("jira_email", "")

    base_url = Prompt.ask(
        "Jira URL",
        default=saved_url if saved_url else "https://yourcompany.atlassian.net"
    )

    email = Prompt.ask(
        "Email",
        default=saved_email if saved_email else None
    )

    # Always prompt for token (don't save it for security)
    console.print("[dim]Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens[/]")
    token = Prompt.ask("API Token", password=True)

    config["jira_base_url"] = base_url
    config["jira_email"] = email

    return {
        "base_url": base_url,
        "email": email,
        "token": token,
    }


def run_sla_check(client: JiraClient, verbose: bool = False):
    """Run the SLA check and display results."""
    checker = SLAChecker(client, verbose=verbose)

    # Field IDs are loaded from config.py
    checker.set_field_id("health_plan", JIRA_FIELDS["health_plan"])
    checker.set_field_id("category", JIRA_FIELDS["category"])

    display_info("Fetching tickets from Jira...")
    console.print()

    summary = checker.check_identification_resolution_config()

    if summary.total_count == 0:
        display_info("No tickets found matching the SLA criteria.")
        display_info("Make sure the 'Health plan (migrated)' field contains 'BCBSLA' on ACS tickets.")
        return

    display_sla_dashboard(summary)


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
    console.print("[dim]Identification of Resolution for Configuration Issues[/]")
    console.print("[dim]ACS → LPM Handoff | BCBSLA | 30 Business Days[/]")
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

    # Run the SLA check
    console.print()
    console.rule("[bold]SLA Results[/]")
    console.print()

    try:
        run_sla_check(client, verbose=args.verbose)
    except Exception as e:
        display_error(f"SLA check failed: {e}")
        sys.exit(1)

    console.print()


if __name__ == "__main__":
    main()
