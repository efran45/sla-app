"""
SLA Checker - Main logic for evaluating SLAs
"""
from datetime import datetime
from typing import Optional

from rich.console import Console

from jira_client import JiraClient
from sla_calculator import (
    SLAResult,
    SLASummary,
    get_business_days,
    get_business_days_elapsed,
    parse_jira_date,
    extract_field_value,
)
from config import SLA_DEFINITIONS, JIRA_FIELDS, SOURCE_OF_ID_FIELD_ID, CATEGORY_FIELD_ID

console = Console()


class SLAChecker:
    """Checks SLA compliance by querying Jira."""

    def __init__(self, jira_client: JiraClient, verbose: bool = False):
        self.jira = jira_client
        self.field_ids = JIRA_FIELDS.copy()
        self.verbose = verbose

    def _log(self, message: str, style: str = "dim"):
        """Print verbose log message."""
        if self.verbose:
            console.print(f"[{style}]{message}[/]")

    def set_field_id(self, field_name: str, field_id: str):
        """Set a custom field ID."""
        self.field_ids[field_name] = field_id

    def check_identification_resolution_config(self) -> SLASummary:
        """
        Check the "Identification of Resolution for Configuration Issues" SLA.

        SLA: Time from ACS ticket creation (for BCBSLA health plan) to
             linked LPM ticket with category "break fix" must be <= 30 business days.
        """
        sla_config = SLA_DEFINITIONS["identification_resolution_config"]
        summary = SLASummary(
            sla_name=sla_config["name"],
            target_days=sla_config["target_days"],
        )

        # Build JQL to find ACS tickets for BCBSLA
        health_plan_field = self.field_ids.get("health_plan", "")

        self._log(f"Health plan field ID: {health_plan_field}", "cyan")
        self._log(f"Category field ID: {self.field_ids.get('category', '')}", "cyan")

        jql = (
            f'project = {sla_config["source_project"]} '
            f'AND "{sla_config["health_plan_field"]}" = "{sla_config["health_plan_value"]}"'
        )

        self._log(f"JQL Query: {jql}", "yellow")

        source_of_id_field = self.field_ids.get("source_of_identification", "")

        # Fetch source tickets
        category_field = self.field_ids.get("category", "")
        fields = ["key", "created", "summary", "status", "issuelinks", health_plan_field, source_of_id_field, category_field]
        self._log(f"Requesting fields: {fields}", "dim")

        source_tickets = self.jira.search_issues(jql, fields=fields)

        self._log(f"Tickets returned from Jira: {len(source_tickets)}", "green")

        if self.verbose and source_tickets:
            console.print("\n[bold]Sample ticket data (first ticket):[/]")
            sample = source_tickets[0]
            console.print(f"  Key: {sample.get('key')}")
            console.print(f"  Fields: {list(sample.get('fields', {}).keys())}")
            sample_fields = sample.get('fields', {})
            console.print(f"  Issue links count: {len(sample_fields.get('issuelinks', []))}")
            if health_plan_field in sample_fields:
                console.print(f"  Health plan value: {sample_fields.get(health_plan_field)}")
            console.print()

        excluded_statuses = {"closed", "resolved", "canceled"}

        for ticket in source_tickets:
            result = self._evaluate_ticket(ticket, sla_config)

            # Exclude tickets with no LPM link if the ACS ticket is closed/resolved/canceled
            if not result.target_ticket:
                ticket_status = (ticket.get("fields", {}).get("status", {}).get("name", "") or "").lower()
                if ticket_status in excluded_statuses:
                    self._log(f"  Excluding {result.source_ticket}: no LPM ticket and status is '{ticket_status}'", "dim")
                    continue
                self._log(f"  {result.source_ticket}: no matching LPM ticket with 'break fix' category (tracking as in progress)", "dim")

            summary.add_result(result)

        return summary

    def check_resolution_config(self) -> SLASummary:
        """
        Check the "Resolution of Configuration Issues" SLA.

        SLA: Time from ACS ticket creation (for BCBSLA health plan) to
             linked LPM ticket reaching status "ready to build" must be <= 60 business days.
        """
        sla_config = SLA_DEFINITIONS["resolution_config"]
        summary = SLASummary(
            sla_name=sla_config["name"],
            target_days=sla_config["target_days"],
        )

        health_plan_field = self.field_ids.get("health_plan", "")
        source_of_id_field = self.field_ids.get("source_of_identification", "")
        category_field = self.field_ids.get("category", "")

        jql = (
            f'project = {sla_config["source_project"]} '
            f'AND "{sla_config["health_plan_field"]}" = "{sla_config["health_plan_value"]}"'
        )

        self._log(f"[Resolution SLA] JQL Query: {jql}", "yellow")

        fields = ["key", "created", "summary", "status", "issuelinks", health_plan_field, source_of_id_field, category_field]
        source_tickets = self.jira.search_issues(jql, fields=fields)

        self._log(f"[Resolution SLA] Tickets returned from Jira: {len(source_tickets)}", "green")

        excluded_statuses = {"closed", "resolved", "canceled"}

        for ticket in source_tickets:
            result = self._evaluate_ticket_resolution(ticket, sla_config)

            if not result.target_ticket:
                ticket_status = (ticket.get("fields", {}).get("status", {}).get("name", "") or "").lower()
                if ticket_status in excluded_statuses:
                    self._log(f"  Excluding {result.source_ticket}: no LPM ticket and status is '{ticket_status}'", "dim")
                    continue
                self._log(f"  {result.source_ticket}: no LPM ticket at 'ready to build' yet (tracking as in progress)", "dim")

            summary.add_result(result)

        return summary

    def _evaluate_ticket_resolution(self, ticket: dict, sla_config: dict) -> SLAResult:
        """Evaluate a single ticket against the Resolution SLA (LPM status = 'ready to build')."""
        ticket_key = ticket.get("key")
        fields = ticket.get("fields", {})

        self._log(f"\n--- [Resolution] Evaluating {ticket_key} ---", "bold cyan")

        created_str = fields.get("created")
        created_date = parse_jira_date(created_str)
        if not created_date:
            created_date = datetime.now()

        issue_links = fields.get("issuelinks", [])
        target_ticket = None
        resolved_date = None

        for link in issue_links:
            linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
            if not linked_issue:
                continue

            linked_key = linked_issue.get("key", "")
            if not linked_key.startswith(sla_config["target_project"]):
                continue

            self._log(f"    Checking LPM ticket {linked_key} for 'ready to build' status...", "dim")

            try:
                # Check current status of the LPM ticket
                linked_ticket_data = self.jira.get_issue(linked_key, fields=["key", "status"])
                current_status = (linked_ticket_data.get("fields", {}).get("status", {}).get("name", "") or "").lower()

                self._log(f"      Current status: '{current_status}'", "dim")

                # Look for when it transitioned to "ready to build" via changelog
                transition_date_str = self.jira.get_status_transition_date(linked_key, sla_config["target_status"])

                if transition_date_str:
                    target_ticket = linked_key
                    resolved_date = parse_jira_date(transition_date_str)
                    self._log(f"      MATCH! Reached 'ready to build' on {resolved_date}", "green")
                    break
                else:
                    self._log(f"      No 'ready to build' transition found in changelog", "dim")

            except Exception as e:
                self._log(f"      Error fetching linked ticket: {e}", "red")
                continue

        # Extract source of identification and category(migrated)
        source_of_id = extract_field_value(fields.get(SOURCE_OF_ID_FIELD_ID), default="")
        category_migrated = extract_field_value(fields.get(CATEGORY_FIELD_ID), default="")

        # Calculate days elapsed
        if resolved_date:
            days_elapsed = get_business_days(created_date, resolved_date)
        else:
            days_elapsed = get_business_days_elapsed(created_date)

        # Determine status
        target_days = sla_config["target_days"]

        if target_ticket and resolved_date:
            status = "met" if days_elapsed <= target_days else "breached"
        else:
            status = "breached" if days_elapsed > target_days else "in_progress"

        self._log(f"  Result: {status} ({days_elapsed} days)", "bold")

        return SLAResult(
            source_ticket=ticket_key,
            target_ticket=target_ticket,
            created_date=created_date,
            resolved_date=resolved_date,
            days_elapsed=days_elapsed,
            target_days=target_days,
            status=status,
            source_of_identification=source_of_id,
            category_migrated=category_migrated,
        )

    def _evaluate_ticket(self, ticket: dict, sla_config: dict) -> SLAResult:
        """Evaluate a single ticket against the SLA."""
        ticket_key = ticket.get("key")
        fields = ticket.get("fields", {})

        self._log(f"\n--- Evaluating {ticket_key} ---", "bold cyan")

        # Parse created date
        created_str = fields.get("created")
        created_date = parse_jira_date(created_str)

        if not created_date:
            created_date = datetime.now()  # Fallback

        self._log(f"  Created: {created_date}", "dim")

        # Get issue links
        issue_links = fields.get("issuelinks", [])
        self._log(f"  Issue links found: {len(issue_links)}", "dim")

        # Look for linked LPM ticket with category "break fix"
        target_ticket = None
        resolved_date = None

        for link in issue_links:
            linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
            if not linked_issue:
                self._log(f"    Link has no outward/inward issue: {link.get('type', {}).get('name', 'unknown')}", "dim")
                continue

            linked_key = linked_issue.get("key", "")
            self._log(f"    Found link: {linked_key}", "dim")

            # Check if it's an LPM ticket
            if not linked_key.startswith(sla_config["target_project"]):
                self._log(f"      Skipped: not an {sla_config['target_project']} ticket", "dim")
                continue

            self._log(f"      Is {sla_config['target_project']} ticket, checking category...", "dim")

            # Fetch the linked ticket to check category
            try:
                category_field = self.field_ids.get("category", "")
                linked_fields = ["key", "created", category_field] if category_field else ["key", "created"]
                linked_ticket_data = self.jira.get_issue(linked_key, fields=linked_fields)

                linked_ticket_fields = linked_ticket_data.get("fields", {})

                self._log(f"      LPM ticket fields: {list(linked_ticket_fields.keys())}", "dim")

                # Check category
                category_value = ""
                if category_field and category_field in linked_ticket_fields:
                    category_value = extract_field_value(linked_ticket_fields.get(category_field))
                    self._log(f"      Category field ({category_field}): {category_value}", "dim")

                # Also check for category in any field that might contain it
                for field_key, field_val in linked_ticket_fields.items():
                    if "category" in field_key.lower():
                        found_value = extract_field_value(field_val)
                        self._log(f"      Found category-like field ({field_key}): {found_value}", "dim")
                        if not category_value:
                            category_value = found_value

                self._log(f"      Final category value: '{category_value}'", "yellow")
                self._log(f"      Looking for: '{sla_config['target_category']}'", "yellow")

                if category_value.lower() == sla_config["target_category"].lower():
                    target_ticket = linked_key
                    resolved_date = parse_jira_date(linked_ticket_fields.get("created"))
                    self._log(f"      MATCH! Target ticket: {target_ticket}", "green")
                    break
                else:
                    self._log(f"      No match", "red")

            except Exception as e:
                self._log(f"      Error fetching linked ticket: {e}", "red")
                continue

        # Extract source of identification and category(migrated)
        source_of_id = extract_field_value(fields.get(SOURCE_OF_ID_FIELD_ID), default="")
        category_migrated = extract_field_value(fields.get(CATEGORY_FIELD_ID), default="")

        # Calculate days elapsed
        if resolved_date:
            days_elapsed = get_business_days(created_date, resolved_date)
        else:
            days_elapsed = get_business_days_elapsed(created_date)

        # Determine status
        target_days = sla_config["target_days"]

        if target_ticket and resolved_date:
            # SLA is resolved
            if days_elapsed <= target_days:
                status = "met"
            else:
                status = "breached"
        else:
            # SLA is still in progress
            if days_elapsed > target_days:
                status = "breached"
            else:
                status = "in_progress"

        self._log(f"  Result: {status} ({days_elapsed} days)", "bold")

        return SLAResult(
            source_ticket=ticket_key,
            target_ticket=target_ticket,
            created_date=created_date,
            resolved_date=resolved_date,
            days_elapsed=days_elapsed,
            target_days=target_days,
            status=status,
            source_of_identification=source_of_id,
            category_migrated=category_migrated,
        )
