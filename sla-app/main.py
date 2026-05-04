#!/usr/bin/env python3
"""
Healthcare SLA CLI - Main entry point

Just run: python main.py
For debug output: python main.py --verbose
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

import requests
from datetime import datetime
from rich.prompt import Prompt, Confirm
from rich.console import Console

logging.basicConfig(level=logging.INFO, format="[SLA] %(levelname)s %(message)s")
_log = logging.getLogger(__name__)

_env_file = Path(__file__).parent / ".env"
_log.info("Looking for .env at: %s", _env_file)
_log.info(".env file found: %s", _env_file.exists())

try:
    from dotenv import load_dotenv
    loaded = load_dotenv(_env_file)
    _log.info("dotenv load_dotenv returned: %s", loaded)
except ImportError:
    _log.warning("python-dotenv is not installed — .env file will not be loaded")

from config import JIRA_FIELDS
from jira_client import JiraClient
from sla_checker import SLAChecker
from display import (
    console,
    display_sla_dashboard,
    display_fix_version_tickets,
    display_error,
    display_info,
    display_success,
)

CONFIG_FILE = Path(__file__).parent / ".config.json"


def get_env_credentials() -> dict | None:
    """Return credentials from environment variables, or None if not all three are set."""
    base_url = os.environ.get("JIRA_BASE_URL", "").strip()
    email    = os.environ.get("JIRA_EMAIL", "").strip()
    token    = os.environ.get("JIRA_API_TOKEN", "").strip()
    _log.info("JIRA_BASE_URL set: %s", bool(base_url))
    _log.info("JIRA_EMAIL set: %s", bool(email))
    _log.info("JIRA_API_TOKEN set: %s", bool(token))
    if base_url and email and token:
        _log.info("All env credentials found — skipping interactive prompt")
        return {"base_url": base_url, "email": email, "token": token}
    _log.info("Env credentials incomplete — falling back to interactive prompt")
    return None


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def prompt_for_credentials(config: dict) -> dict:
    saved_url = config.get("jira_base_url", "")
    saved_email = config.get("jira_email", "")

    if saved_url and saved_email:
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
        console.print("\n[bold]Jira Credentials[/]\n")
        base_url = Prompt.ask("Jira URL", default="https://yourcompany.atlassian.net")
        email = Prompt.ask("Email")
        config["jira_base_url"] = base_url
        config["jira_email"] = email

    console.print()
    console.print("[dim]Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens[/]")
    token = Prompt.ask("API Token", password=True)

    return {
        "base_url": base_url,
        "email": email,
        "token": token,
    }


def connect_to_jira(creds: dict):
    """Create a JiraClient, test the connection, and return (client, user_info). Exits on failure."""
    _log.info("Attempting connection to: %s", creds["base_url"])
    _log.info("Connecting as: %s", creds["email"])
    try:
        client = JiraClient(
            base_url=creds["base_url"],
            email=creds["email"],
            token=creds["token"],
        )
        user_info = client.test_connection()
        _log.info("Connection successful — logged in as: %s", user_info.get("displayName"))
        return client, user_info
    except requests.exceptions.ConnectionError:
        display_error(
            f"Cannot reach Jira at '{creds['base_url']}'. "
            "Check JIRA_BASE_URL and your network connection."
        )
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 401:
            display_error("Authentication failed (HTTP 401). Check your email address and API token.")
        elif status == 403:
            display_error("Access denied (HTTP 403). Your account may not have permission to access this Jira instance.")
        elif status == 404:
            display_error(f"Jira URL not found (HTTP 404). Verify that '{creds['base_url']}' is correct.")
        else:
            display_error(f"Jira returned HTTP {status}: {e}")
        sys.exit(1)
    except ValueError as e:
        display_error(str(e))
        sys.exit(1)
    except Exception as e:
        display_error(f"Connection failed: {e}")
        sys.exit(1)


def prompt_for_date_range() -> tuple:
    console.print("\n[bold]Date Range Filter[/]")
    console.print("[dim]Filter tickets by creation date. Leave blank to include all tickets.[/]\n")

    date_from = Prompt.ask("Start date (YYYY-MM-DD)", default="").strip()
    date_to = Prompt.ask("End date   (YYYY-MM-DD)", default="").strip()

    for label, val in [("Start date", date_from), ("End date", date_to)]:
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                display_error(f"{label} '{val}' is not valid. Expected YYYY-MM-DD. Ignoring filter.")
                return None, None

    return (date_from or None), (date_to or None)


def run_sla_checks(client: JiraClient, verbose: bool = False, date_from: str = None, date_to: str = None):
    checker = SLAChecker(client, verbose=verbose, date_from=date_from, date_to=date_to)

    checker.set_field_id("health_plan", JIRA_FIELDS["health_plan"])
    checker.set_field_id("category", JIRA_FIELDS["category"])

    display_info("Fetching tickets from Jira...")
    console.print()

    # SLA 1: Time to First Response (2 business days)
    summary1 = checker.check_first_response()
    if summary1.total_count == 0:
        display_info("No tickets found matching the First Response SLA criteria.")
    else:
        display_sla_dashboard(summary1)

    console.rule("[dim]")
    console.print()

    # SLA 2: Identification of Resolution for Configuration Issues (30 days)
    summary2 = checker.check_identification_resolution_config()
    if summary2.total_count == 0:
        display_info("No tickets found matching the Identification SLA criteria.")
    else:
        display_sla_dashboard(summary2)

    console.rule("[dim]")
    console.print()

    # SLA 3: Resolution of Configuration Issues (60 days)
    summary3 = checker.check_resolution_config()
    if summary3.total_count == 0:
        display_info("No tickets found matching the Resolution SLA criteria.")
    else:
        display_sla_dashboard(summary3)

    console.rule("[dim]")
    console.print()

    # SLA 4: Impact Report Delivery (30 business days)
    summary4 = checker.check_impact_report_delivery()
    if summary4.total_count == 0:
        display_info("No SR sub-tasks found via direct LPM links. Checking fix versions...")
        console.print()
        fix_version_data = checker.get_recent_fix_version_lpm_tickets()
        display_fix_version_tickets(fix_version_data)
    else:
        display_sla_dashboard(summary4)


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
    console.print("[dim]1. Time to First Response | 2 Business Days[/]")
    console.print("[dim]2. Identification of Resolution for Configuration Issues | 30 Business Days[/]")
    console.print("[dim]3. Resolution of Configuration Issues | 60 Business Days[/]")
    console.print("[dim]4. Impact Report Delivery | 30 Business Days[/]")
    console.print("[dim]ACS -> LPM -> SR | LA Blue[/]")
    console.print()

    if args.verbose:
        console.print("[yellow]Verbose mode enabled[/]\n")

    env_creds = get_env_credentials()
    if env_creds:
        console.print("[green]Using Jira credentials from environment variables.[/]\n")
        creds = env_creds
    else:
        config = load_config()
        creds = prompt_for_credentials(config)
        save_config(config)

    console.print()
    display_info("Connecting to Jira...")

    client, user_info = connect_to_jira(creds)
    display_success(f"Connected as: {user_info.get('displayName', 'Unknown')}")

    date_from, date_to = prompt_for_date_range()

    console.print()
    console.rule("[bold]SLA Results[/]")
    if date_from or date_to:
        range_str = f"{date_from or 'beginning'} to {date_to or 'now'}"
        console.print(f"\n[dim]Filtered to tickets created: {range_str}[/]")
    console.print()

    try:
        run_sla_checks(client, verbose=args.verbose, date_from=date_from, date_to=date_to)
    except Exception as e:
        display_error(f"SLA check failed: {e}")
        sys.exit(1)

    console.print()


if __name__ == "__main__":
    main()
