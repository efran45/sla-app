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
    format_elapsed_time,
)
from config import SLA_DEFINITIONS, JIRA_FIELDS, SOURCE_OF_ID_FIELD_ID, CATEGORY_FIELD_ID

console = Console()


class SLAChecker:
    """Checks SLA compliance by querying Jira."""

    def __init__(self, jira_client: JiraClient, verbose: bool = False, date_from: str = None, date_to: str = None):
        self.jira = jira_client
        self.field_ids = JIRA_FIELDS.copy()
        self.verbose = verbose
        self.date_from = date_from
        self.date_to = date_to

    def _log(self, message: str, style: str = "dim"):
        """Print verbose log message."""
        if self.verbose:
            console.print(f"[{style}]{message}[/]")

    def set_field_id(self, field_name: str, field_id: str):
        """Set a custom field ID."""
        self.field_ids[field_name] = field_id

    def _date_filter_jql(self) -> str:
        """Build JQL date filter clause from date range."""
        parts = []
        if self.date_from:
            parts.append(f'created >= "{self.date_from}"')
        if self.date_to:
            parts.append(f'created <= "{self.date_to}"')
        return (" AND " + " AND ".join(parts)) if parts else ""

    def _is_public_comment(self, comment: dict) -> bool:
        """Check if a comment is publicly visible (not an internal note)."""
        jsd_public = comment.get("jsdPublic")
        visibility = comment.get("visibility")
        if jsd_public is not None:
            return bool(jsd_public)
        return not bool(visibility)

    def _extract_adf_text(self, node) -> str:
        """Recursively extract plain text from an ADF (Atlassian Document Format) node."""
        if not isinstance(node, dict):
            return ""
        if node.get("type") == "text":
            return node.get("text", "")
        parts = []
        for child in node.get("content", []):
            parts.append(self._extract_adf_text(child))
        return " ".join(filter(None, parts))

    def _adf_has_media(self, node) -> bool:
        """Recursively check if an ADF node contains a media attachment."""
        if not isinstance(node, dict):
            return False
        if node.get("type") in ("media", "mediaGroup", "mediaSingle"):
            return True
        for child in node.get("content", []):
            if self._adf_has_media(child):
                return True
        return False

    def _comment_is_impact_report(self, comment: dict) -> bool:
        """
        Check if a comment looks like an impact report delivery.
        Matches public comments that have an attachment and mention
        "impact report" (case-insensitive) in the body text.
        """
        if not self._is_public_comment(comment):
            return False
        body = comment.get("body", {})
        if not body:
            return False
        text = self._extract_adf_text(body).lower()
        has_keywords = "impact report" in text
        has_attachment = self._adf_has_media(body)
        return has_keywords and has_attachment

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
            f'{self._date_filter_jql()}'
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
            console.print("
[bold]Sample ticket data (first ticket):[/]")
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
             the "config done date" on linked LPM ticket must be <= 60 business days.
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
            f'{self._date_filter_jql()}'
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
                self._log(f"  {result.source_ticket}: no LPM ticket with config done date yet (tracking as in progress)", "dim")

            summary.add_result(result)

        return summary

    def check_first_response(self) -> SLASummary:
        """
        Check the "Time to First Response" SLA.

        SLA: Time from ACS ticket creation (for BCBSLA health plan) to the first
             public comment by an internal (Atlassian account type) user must be <= 2 business days.
        """
        sla_config = SLA_DEFINITIONS["first_response"]
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
            f'{self._date_filter_jql()}'
        )

        self._log(f"[First Response SLA] JQL Query: {jql}", "yellow")

        fields = ["key", "created", "summary", "status", health_plan_field, source_of_id_field, category_field]
        source_tickets = self.jira.search_issues(jql, fields=fields)

        self._log(f"[First Response SLA] Tickets returned from Jira: {len(source_tickets)}", "green")

        for ticket in source_tickets:
            ticket_key = ticket.get("key")
            ticket_fields = ticket.get("fields", {})

            self._log(f"
--- [First Response] Evaluating {ticket_key} ---", "bold cyan")

            created_str = ticket_fields.get("created")
            created_date = parse_jira_date(created_str)
            if not created_date:
                created_date = datetime.now()

            # Fetch comments for this ticket
            try:
                comments = self.jira.get_issue_comments(ticket_key)
            except Exception as e:
                self._log(f"  Error fetching comments: {e}", "red")
                comments = []

            self._log(f"  Total comments: {len(comments)}", "dim")

            # Find the earliest public comment from an internal (atlassian) user
            first_response_date = None
            for comment in comments:
                author = comment.get("author", {})
                account_type = author.get("accountType", "")

                # Only consider internal licensed users
                if account_type != "atlassian":
                    continue

                # Check if the comment is public (visible to customers)
                # jsdPublic == True means it's a public comment in JSM
                # If jsdPublic is not present, check that visibility is absent (not internal-only)
                jsd_public = comment.get("jsdPublic")
                visibility = comment.get("visibility")

                if jsd_public is not None:
                    if not jsd_public:
                        continue
                elif visibility:
                    # Has a visibility restriction — it's an internal note
                    continue

                comment_date = parse_jira_date(comment.get("created"))
                if comment_date and (first_response_date is None or comment_date < first_response_date):
                    first_response_date = comment_date
                    self._log(f"  Public internal comment found: {author.get('displayName', 'Unknown')} on {comment_date}", "green")

            # Extract source of identification and category(migrated)
            source_of_id = extract_field_value(ticket_fields.get(SOURCE_OF_ID_FIELD_ID), default="")
            category_migrated = extract_field_value(ticket_fields.get(CATEGORY_FIELD_ID), default="")

            # Calculate business days elapsed
            if first_response_date:
                days_elapsed = get_business_days(created_date, first_response_date)
                elapsed_time_str = format_elapsed_time(created_date, first_response_date)
            else:
                days_elapsed = get_business_days_elapsed(created_date)
                elapsed_time_str = format_elapsed_time(created_date, datetime.now())

            # Determine status
            target_days = sla_config["target_days"]

            if first_response_date:
                status = "met" if days_elapsed <= target_days else "breached"
            else:
                status = "breached" if days_elapsed > target_days else "in_progress"

            self._log(f"  Result: {status} ({days_elapsed} biz days, {elapsed_time_str})", "bold")

            result = SLAResult(
                source_ticket=ticket_key,
                target_ticket=None,
                created_date=created_date,
                resolved_date=first_response_date,
                days_elapsed=days_elapsed,
                target_days=target_days,
                status=status,
                source_of_identification=source_of_id,
                category_migrated=category_migrated,
                elapsed_time_str=elapsed_time_str,
            )
            summary.add_result(result)

        return summary

    def check_impact_report_delivery(self) -> SLASummary:
        """
        Check the "Impact Report Delivery" SLA.

        Chain: LPM (BCBSLA) -> SR sub-task -> ACS ticket -> public comment with impact report attachment

        SLA: Time from SR sub-task creation to a public comment on the linked ACS ticket
             that contains an attachment and mentions "impact report" must be <= 30 business days.
        """
        sla_config = SLA_DEFINITIONS["impact_report_delivery"]
        summary = SLASummary(
            sla_name=sla_config["name"],
            target_days=sla_config["target_days"],
        )

        health_plan_field = self.field_ids.get("health_plan", "")

        # Query LPM tickets filtered by BCBSLA health plan
        jql = (
            f'project = {sla_config["lpm_project"]} '
            f'AND "{sla_config["health_plan_field"]}" = "{sla_config["health_plan_value"]}"'
            f'{self._date_filter_jql()}'
        )

        self._log(f"[Impact Report SLA] JQL Query: {jql}", "yellow")

        fields = ["key", "created", "summary", "status", "issuelinks", health_plan_field]
        lpm_tickets = self.jira.search_issues(jql, fields=fields)

        self._log(f"[Impact Report SLA] LPM tickets returned: {len(lpm_tickets)}", "green")

        sr_project = sla_config["sr_project"]
        acs_project = sla_config["acs_project"]
        target_days = sla_config["target_days"]

        for lpm_ticket in lpm_tickets:
            lpm_key = lpm_ticket.get("key")
            lpm_fields = lpm_ticket.get("fields", {})
            issue_links = lpm_fields.get("issuelinks", [])

            self._log(f"
--- [Impact Report] Processing LPM {lpm_key} ({len(issue_links)} links) ---", "bold cyan")

            for link in issue_links:
                linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
                if not linked_issue:
                    continue

                linked_key = linked_issue.get("key", "")
                if not linked_key.startswith(sr_project):
                    continue

                self._log(f"  Found SR ticket: {linked_key}", "dim")

                try:
                    sr_data = self.jira.get_issue(
                        linked_key,
                        fields=["key", "created", "summary", "status", "issuetype", "issuelinks"],
                    )
                    sr_fields = sr_data.get("fields", {})

                    # Must be a sub-task issue type
                    issue_type = sr_fields.get("issuetype", {})
                    is_subtask = issue_type.get("subtask", False) or issue_type.get("name", "").lower() == "sub-task"
                    if not is_subtask:
                        self._log(f"    Skipping {linked_key}: not a sub-task (type: {issue_type.get('name', 'unknown')})", "dim")
                        continue

                    # SLA clock starts at SR sub-task creation
                    sr_created_date = parse_jira_date(sr_fields.get("created")) or datetime.now()

                    # Check if SR ticket is in a done/closed status
                    sr_status = sr_fields.get("status", {})
                    sr_status_category = sr_status.get("statusCategory", {}).get("key", "").lower()
                    sr_status_name = (sr_status.get("name") or "").lower()
                    sr_is_done = sr_status_category == "done" or sr_status_name in {
                        "done", "closed", "resolved", "cancelled", "canceled", "complete", "completed"
                    }

                    self._log(f"    SR sub-task {linked_key} | created: {sr_created_date} | status: {sr_status.get('name')} (done: {sr_is_done})", "dim")

                    # Find ACS tickets linked to the SR ticket
                    sr_links = sr_fields.get("issuelinks", [])
                    report_comment_date = None
                    acs_ticket_key = None

                    for sr_link in sr_links:
                        acs_issue = sr_link.get("outwardIssue") or sr_link.get("inwardIssue")
                        if not acs_issue:
                            continue
                        acs_key = acs_issue.get("key", "")
                        if not acs_key.startswith(acs_project):
                            continue

                        self._log(f"    Found ACS ticket linked to SR: {acs_key}", "dim")

                        try:
                            comments = self.jira.get_issue_comments(acs_key)
                            self._log(f"      {len(comments)} comments on {acs_key}", "dim")

                            for comment in comments:
                                if self._comment_is_impact_report(comment):
                                    comment_date = parse_jira_date(comment.get("created"))
                                    if comment_date and (report_comment_date is None or comment_date < report_comment_date):
                                        report_comment_date = comment_date
                                        acs_ticket_key = acs_key
                                        self._log(f"      MATCH! Impact report comment on {acs_key} at {comment_date}", "green")

                        except Exception as e:
                            self._log(f"      Error fetching comments for {acs_key}: {e}", "red")
                            continue

                    # Calculate SLA
                    if report_comment_date:
                        days_elapsed = get_business_days(sr_created_date, report_comment_date)
                        elapsed_time_str = format_elapsed_time(sr_created_date, report_comment_date)
                    else:
                        days_elapsed = get_business_days_elapsed(sr_created_date)
                        elapsed_time_str = format_elapsed_time(sr_created_date, datetime.now())

                    if report_comment_date:
                        status = "met" if days_elapsed <= target_days else "breached"
                    else:
                        status = "breached" if days_elapsed > target_days else "in_progress"

                    self._log(f"  Result for {linked_key}: {status} ({days_elapsed} biz days)", "bold")

                    result = SLAResult(
                        source_ticket=linked_key,       # SR sub-task (SLA start)
                        target_ticket=acs_ticket_key,   # ACS ticket (SLA end)
                        created_date=sr_created_date,
                        resolved_date=report_comment_date,
                        days_elapsed=days_elapsed,
                        target_days=target_days,
                        status=status,
                        lpm_category=lpm_key,           # Store originating LPM ticket for reference
                        elapsed_time_str=elapsed_time_str,
                    )
                    summary.add_result(result)

                except Exception as e:
                    self._log(f"  Error processing SR ticket {linked_key}: {e}", "red")
                    continue

        return summary

    def _evaluate_ticket_resolution(self, ticket: dict, sla_config: dict) -> SLAResult:
        """Evaluate a single ticket against the Resolution SLA (config done date on LPM)."""
        ticket_key = ticket.get("key")
        fields = ticket.get("fields", {})

        self._log(f"
--- [Resolution] Evaluating {ticket_key} ---", "bold cyan")

        created_str = fields.get("created")
        created_date = parse_jira_date(created_str)
        if not created_date:
            created_date = datetime.now()

        issue_links = fields.get("issuelinks", [])
        target_ticket = None
        resolved_date = None
        candidates = []

        config_done_field = sla_config.get("config_done_date_field", "")

        for link in issue_links:
            linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
            if not linked_issue:
                continue

            linked_key = linked_issue.get("key", "")
            if not linked_key.startswith(sla_config["target_project"]):
                continue

            self._log(f"    Checking LPM ticket {linked_key} for config done date...", "dim")

            try:
                category_field = self.field_ids.get("category", "")
                linked_fields = ["key", "created"]
                if config_done_field:
                    linked_fields.append(config_done_field)
                if category_field:
                    linked_fields.append(category_field)
                linked_ticket_data = self.jira.get_issue(linked_key, fields=linked_fields)
                linked_ticket_fields = linked_ticket_data.get("fields", {})

                config_done_value = linked_ticket_fields.get(config_done_field)
                config_done_date = parse_jira_date(config_done_value)

                lpm_cat = ""
                if category_field and category_field in linked_ticket_fields:
                    lpm_cat = extract_field_value(linked_ticket_fields.get(category_field), default="")

                if config_done_date:
                    candidates.append((linked_key, config_done_date, lpm_cat))
                    self._log(f"      MATCH! Candidate: {linked_key} config done date: {config_done_date}", "green")
                else:
                    self._log(f"      No config done date set", "dim")

            except Exception as e:
                self._log(f"      Error fetching linked ticket: {e}", "red")
                continue

        # Pick the most recent LPM ticket with a config done date
        lpm_category = ""
        if candidates:
            candidates.sort(key=lambda c: c[1] or datetime.min, reverse=True)
            target_ticket, resolved_date, lpm_category = candidates[0]
            self._log(f"  Selected most recent LPM ticket: {target_ticket}", "green")

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
            lpm_category=lpm_category,
        )

    def _evaluate_ticket(self, ticket: dict, sla_config: dict) -> SLAResult:
        """Evaluate a single ticket against the SLA."""
        ticket_key = ticket.get("key")
        fields = ticket.get("fields", {})

        self._log(f"
--- Evaluating {ticket_key} ---", "bold cyan")

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
        # Collect all matches and pick the most recently created one
        target_ticket = None
        resolved_date = None
        candidates = []

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
                    lpm_created = parse_jira_date(linked_ticket_fields.get("created"))
                    candidates.append((linked_key, lpm_created, category_value))
                    self._log(f"      MATCH! Candidate: {linked_key} (created {lpm_created})", "green")
                else:
                    self._log(f"      No match", "red")

            except Exception as e:
                self._log(f"      Error fetching linked ticket: {e}", "red")
                continue

        # Pick the most recently created LPM ticket
        lpm_category = ""
        if candidates:
            candidates.sort(key=lambda c: c[1] or datetime.min, reverse=True)
            target_ticket, resolved_date, lpm_category = candidates[0]
            self._log(f"  Selected most recent LPM ticket: {target_ticket}", "green")

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
            lpm_category=lpm_category,
        )
