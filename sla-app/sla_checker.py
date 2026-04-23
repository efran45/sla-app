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
        """Build JQL filter clauses — always excludes cancelled tickets, plus any date range."""
        parts = ['status NOT IN ("Cancelled", "Canceled")']
        if self.date_from:
            parts.append(f'created >= "{self.date_from}"')
        if self.date_to:
            parts.append(f'created <= "{self.date_to}"')
        return " AND " + " AND ".join(parts)

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
        Matches public comments that mention 'impact report' (case-insensitive)
        in the body text. Attachments may be added separately to the ticket
        rather than embedded in the comment ADF, so we do not require a media node.
        """
        if not self._is_public_comment(comment):
            return False
        body = comment.get("body", {})
        if not body:
            return False
        text = self._extract_adf_text(body).lower()
        return "impact report" in text

    def check_impact_report_delivery(self) -> SLASummary:
        """
        Check the "Impact Report Delivery" SLA.

        Queries the SR project directly for all Sub-task issues with Health Plan = LA Blue.
        For each sub-task:
          - SLA start: sub-task creation date
          - SLA end:   first public "impact report" comment on the ACS ticket linked
                       to the sub-task's parent SR ticket
          - Target:    30 business days

        lpm_category is repurposed to store the parent SR ticket key for display.
        """
        sla_config = SLA_DEFINITIONS["impact_report_delivery"]
        summary = SLASummary(
            sla_name=sla_config["name"],
            target_days=sla_config["target_days"],
        )

        health_plan_field = self.field_ids.get("health_plan", "")
        acs_project = sla_config["acs_project"]
        target_days = sla_config["target_days"]

        jql = (
            f'project = {sla_config["sr_project"]} '
            f'AND issuetype = Sub-task '
            f'AND "{sla_config["health_plan_field"]}" = "{sla_config["health_plan_value"]}"'
            f'{self._date_filter_jql()}'
        )

        self._log(f"[Impact Report SLA] JQL Query: {jql}", "yellow")

        fields = ["key", "created", "summary", "status", "parent", "issuelinks", health_plan_field]
        subtasks = self.jira.search_issues(jql, fields=fields)

        self._log(f"[Impact Report SLA] SR sub-tasks returned: {len(subtasks)}", "green")

        for subtask in subtasks:
            subtask_key = subtask.get("key")
            subtask_fields = subtask.get("fields", {})

            self._log(f"\n--- [Impact Report] Processing sub-task {subtask_key} ---", "bold cyan")

            subtask_status = (subtask_fields.get("status", {}).get("name") or "").lower()
            if subtask_status in {"cancelled", "canceled"}:
                self._log(f"  Skipping {subtask_key}: canceled", "dim")
                continue

            created_date = parse_jira_date(subtask_fields.get("created"))
            if not created_date:
                self._log(f"  Skipping {subtask_key}: could not parse creation date", "dim")
                continue

            # Parent SR ticket — used to find the linked ACS ticket
            parent_key = (subtask_fields.get("parent") or {}).get("key", "")
            self._log(f"  Parent SR ticket: {parent_key or 'none'}", "dim")

            report_comment_date = None
            acs_ticket_key = None

            if parent_key:
                try:
                    parent_data = self.jira.get_issue(parent_key, fields=["issuelinks"])
                    parent_links = parent_data.get("fields", {}).get("issuelinks", [])

                    for link in parent_links:
                        linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
                        if not linked_issue:
                            continue
                        acs_key = linked_issue.get("key", "")
                        if not acs_key.startswith(acs_project):
                            continue

                        self._log(f"  Found ACS ticket linked to SR parent: {acs_key}", "dim")

                        try:
                            comments = self.jira.get_issue_comments(acs_key)
                            self._log(f"    {len(comments)} comments on {acs_key}", "dim")

                            for comment in comments:
                                if self._comment_is_impact_report(comment):
                                    comment_date = parse_jira_date(comment.get("created"))
                                    if comment_date and (report_comment_date is None or comment_date < report_comment_date):
                                        report_comment_date = comment_date
                                        acs_ticket_key = acs_key
                                        self._log(f"    MATCH! Impact report comment on {acs_key} at {comment_date}", "green")

                        except Exception as e:
                            self._log(f"    Error fetching comments for {acs_key}: {e}", "red")
                            continue

                except Exception as e:
                    self._log(f"  Error fetching parent SR ticket {parent_key}: {e}", "red")

            if report_comment_date:
                days_elapsed = get_business_days(created_date, report_comment_date)
                status = "met" if days_elapsed <= target_days else "breached"
            else:
                days_elapsed = get_business_days_elapsed(created_date)
                status = "breached" if days_elapsed > target_days else "in_progress"

            self._log(f"  Result: {status} ({days_elapsed} biz days)", "bold")

            result = SLAResult(
                source_ticket=subtask_key,
                target_ticket=acs_ticket_key,
                created_date=created_date,
                resolved_date=report_comment_date,
                days_elapsed=days_elapsed,
                target_days=target_days,
                status=status,
                lpm_category=parent_key,  # parent SR ticket key — shown as "SR Parent" in the UI
            )
            summary.add_result(result)

        return summary

    def check_identification_resolution_config(self) -> SLASummary:
        """
        Check the "Identification of Resolution for Configuration Issues" SLA.

        SLA: Time from ACS ticket creation (for LA Blue health plan) to
             linked LPM ticket with category "break fix" must be <= 30 business days.
        """
        sla_config = SLA_DEFINITIONS["identification_resolution_config"]
        summary = SLASummary(
            sla_name=sla_config["name"],
            target_days=sla_config["target_days"],
        )

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

            if not result.target_ticket:
                ticket_status = (ticket.get("fields", {}).get("status", {}).get("name", "") or "").lower()
                if ticket_status in excluded_statuses:
                    self._log(f"  Excluding {result.source_ticket}: no LPM ticket and status is '{ticket_status}'", "dim")
                    continue
                self._log(f"  {result.source_ticket}: no LPM ticket reached 'ready for config' yet (tracking as in progress)", "dim")

            summary.add_result(result)

        return summary

    def check_resolution_config(self) -> SLASummary:
        """
        Check the "Resolution of Configuration Issues" SLA.

        SLA: Time from ACS ticket creation (for LA Blue health plan) to
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
                self._log(f"  {result.source_ticket}: no LPM ticket reached a target status yet (tracking as in progress)", "dim")

            summary.add_result(result)

        return summary

    def check_first_response(self) -> SLASummary:
        """
        Check the "Time to First Response" SLA.

        SLA: Time from ACS ticket creation (for LA Blue health plan) to the first
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

            self._log(f"\n--- [First Response] Evaluating {ticket_key} ---", "bold cyan")

            created_str = ticket_fields.get("created")
            created_date = parse_jira_date(created_str)
            if not created_date:
                created_date = datetime.now()

            try:
                comments = self.jira.get_issue_comments(ticket_key)
            except Exception as e:
                self._log(f"  Error fetching comments: {e}", "red")
                comments = []

            self._log(f"  Total comments: {len(comments)}", "dim")

            first_response_date = None
            for comment in comments:
                jsd_public = comment.get("jsdPublic")
                visibility = comment.get("visibility")

                if jsd_public is not None:
                    if not jsd_public:
                        continue
                elif visibility:
                    continue

                comment_date = parse_jira_date(comment.get("created"))
                if comment_date and (first_response_date is None or comment_date < first_response_date):
                    first_response_date = comment_date
                    author = comment.get("author", {})
                    self._log(f"  Public comment found: {author.get('displayName', 'Unknown')} on {comment_date}", "green")

            source_of_id = extract_field_value(ticket_fields.get(SOURCE_OF_ID_FIELD_ID), default="")
            category_migrated = extract_field_value(ticket_fields.get(CATEGORY_FIELD_ID), default="")

            if first_response_date:
                days_elapsed = get_business_days(created_date, first_response_date)
                elapsed_time_str = format_elapsed_time(created_date, first_response_date)
            else:
                days_elapsed = get_business_days_elapsed(created_date)
                elapsed_time_str = format_elapsed_time(created_date, datetime.now())

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

    def get_recent_fix_version_lpm_tickets(self) -> list[dict]:
        """
        Fallback for Impact Report SLA when no SR sub-tasks are found via direct links.

        Queries LPM/LA Blue tickets that have fixVersions set, collects all non-archived
        versions (past, present, and future), and returns each version with its tickets
        and all linked ticket keys for visibility.
        """
        sla_config = SLA_DEFINITIONS["impact_report_delivery"]
        health_plan_field = self.field_ids.get("health_plan", "")

        jql = (
            f'project = {sla_config["lpm_project"]} '
            f'AND "{sla_config["health_plan_field"]}" = "{sla_config["health_plan_value"]}" '
            f'AND fixVersion is not EMPTY'
        )

        self._log(f"[Fix Versions] JQL: {jql}", "yellow")

        fields = ["key", "summary", "status", "fixVersions", "issuelinks", health_plan_field]
        tickets = self.jira.search_issues(jql, fields=fields)

        self._log(f"[Fix Versions] Tickets with fixVersions: {len(tickets)}", "green")

        if not tickets:
            return []

        # Collect unique non-archived versions and their tickets
        versions = {}        # version_id -> version dict
        version_tickets = {}  # version_id -> list of ticket dicts

        for ticket in tickets:
            ticket_fields = ticket.get("fields", {})
            fix_versions = ticket_fields.get("fixVersions", [])

            # Collect all linked ticket keys
            links = ticket_fields.get("issuelinks", [])
            linked_keys = []
            for link in links:
                linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
                if linked_issue:
                    key = linked_issue.get("key", "")
                    if key:
                        linked_keys.append(key)

            ticket_entry = {
                "key": ticket.get("key"),
                "summary": (ticket_fields.get("summary") or "").strip(),
                "status": ticket_fields.get("status", {}).get("name", ""),
                "linked_keys": linked_keys,
            }

            for version in fix_versions:
                version_id = version.get("id")
                if not version_id or version.get("archived", False):
                    continue

                if version_id not in versions:
                    versions[version_id] = version
                    version_tickets[version_id] = []

                version_tickets[version_id].append(ticket_entry)

        if not versions:
            return []

        # Sort versions: unreleased first (by release date asc), then released (by release date desc)
        today = datetime.now().date()

        def parse_release_date(v):
            rd = v.get("releaseDate")
            if rd:
                try:
                    return datetime.strptime(rd, "%Y-%m-%d").date()
                except ValueError:
                    pass
            return None

        def version_sort_key(v):
            rd = parse_release_date(v)
            released = v.get("released", False)
            if not released:
                # Unreleased: sort ascending by release date (soonest first), no-date last
                return (0, rd or datetime.max.date())
            else:
                # Released: sort descending by release date (most recent first)
                return (1, rd or datetime.min.date())

        sorted_versions = sorted(versions.values(), key=version_sort_key)

        # For released versions, reverse their order so most recent is first in that group
        unreleased = [v for v in sorted_versions if not v.get("released", False)]
        released = [v for v in sorted_versions if v.get("released", False)]
        released.sort(key=lambda v: parse_release_date(v) or datetime.min.date(), reverse=True)
        final_versions = unreleased + released

        return [
            {
                "version": v,
                "tickets": version_tickets.get(v["id"], []),
            }
            for v in final_versions
        ]

    def _evaluate_ticket_resolution(self, ticket: dict, sla_config: dict) -> SLAResult:
        """Evaluate a single ACS ticket against the Resolution SLA.

        Stops when a linked LPM ticket first transitions to any of target_statuses.
        """
        ticket_key = ticket.get("key")
        fields = ticket.get("fields", {})

        self._log(f"\n--- [Resolution] Evaluating {ticket_key} ---", "bold cyan")

        created_str = fields.get("created")
        created_date = parse_jira_date(created_str) or datetime.now()

        issue_links = fields.get("issuelinks", [])
        target_ticket = None
        resolved_date = None
        candidates = []

        target_statuses = sla_config.get("target_statuses", [])

        for link in issue_links:
            linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
            if not linked_issue:
                continue

            linked_key = linked_issue.get("key", "")
            if not linked_key.startswith(sla_config["target_project"]):
                continue

            linked_status = (linked_issue.get("fields", {}).get("status", {}).get("name") or "").lower()
            if linked_status in {"cancelled", "canceled"}:
                self._log(f"    Skipping {linked_key}: LPM ticket is canceled", "dim")
                continue

            self._log(f"    Checking LPM {linked_key} for target statuses...", "dim")

            try:
                transition_date_str = self.jira.get_status_transition_date(linked_key, target_statuses)
                if transition_date_str:
                    transition_date = parse_jira_date(transition_date_str)
                    candidates.append((linked_key, transition_date))
                    self._log(f"      MATCH! {linked_key} reached a target status on {transition_date}", "green")
                else:
                    self._log(f"      No target status transition found", "dim")
            except Exception as e:
                self._log(f"      Error fetching changelog for {linked_key}: {e}", "red")
                continue

        if candidates:
            candidates.sort(key=lambda c: c[1] or datetime.min, reverse=True)
            target_ticket, resolved_date = candidates[0]
            self._log(f"  Selected LPM ticket: {target_ticket}", "green")

        source_of_id = extract_field_value(fields.get(SOURCE_OF_ID_FIELD_ID), default="")
        category_migrated = extract_field_value(fields.get(CATEGORY_FIELD_ID), default="")

        # Fetch LPM category for the winning ticket
        target_category = ""
        cat_field = self.field_ids.get("category", "")
        if target_ticket and cat_field:
            try:
                lpm_data = self.jira.get_issue(target_ticket, fields=[cat_field])
                target_category = extract_field_value(lpm_data.get("fields", {}).get(cat_field), default="")
                self._log(f"  LPM category for {target_ticket}: {target_category}", "dim")
            except Exception as e:
                self._log(f"  Could not fetch LPM category for {target_ticket}: {e}", "dim")

        if resolved_date:
            days_elapsed = get_business_days(created_date, resolved_date)
        else:
            days_elapsed = get_business_days_elapsed(created_date)

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
            lpm_candidates=candidates,
            target_category=target_category,
        )

    def _evaluate_ticket(self, ticket: dict, sla_config: dict) -> SLAResult:
        """Evaluate a single ACS ticket against the Identification SLA.

        Stops when a linked LPM ticket first transitions to target_status.
        """
        ticket_key = ticket.get("key")
        fields = ticket.get("fields", {})

        self._log(f"\n--- Evaluating {ticket_key} ---", "bold cyan")

        created_str = fields.get("created")
        created_date = parse_jira_date(created_str) or datetime.now()

        self._log(f"  Created: {created_date}", "dim")

        issue_links = fields.get("issuelinks", [])
        self._log(f"  Issue links found: {len(issue_links)}", "dim")

        target_ticket = None
        resolved_date = None
        candidates = []

        for link in issue_links:
            linked_issue = link.get("outwardIssue") or link.get("inwardIssue")
            if not linked_issue:
                continue

            linked_key = linked_issue.get("key", "")
            if not linked_key.startswith(sla_config["target_project"]):
                continue

            linked_status = (linked_issue.get("fields", {}).get("status", {}).get("name") or "").lower()
            if linked_status in {"cancelled", "canceled"}:
                self._log(f"    Skipping {linked_key}: LPM ticket is canceled", "dim")
                continue

            self._log(f"    Checking LPM {linked_key} for '{sla_config['target_status']}' status...", "dim")

            try:
                transition_date_str = self.jira.get_status_transition_date(linked_key, sla_config["target_status"])
                if transition_date_str:
                    transition_date = parse_jira_date(transition_date_str)
                    candidates.append((linked_key, transition_date))
                    self._log(f"      MATCH! {linked_key} reached '{sla_config['target_status']}' on {transition_date}", "green")
                else:
                    self._log(f"      No '{sla_config['target_status']}' transition found", "dim")
            except Exception as e:
                self._log(f"      Error fetching changelog for {linked_key}: {e}", "red")
                continue

        if candidates:
            candidates.sort(key=lambda c: c[1] or datetime.min, reverse=True)
            target_ticket, resolved_date = candidates[0]
            self._log(f"  Selected LPM ticket: {target_ticket}", "green")

        source_of_id = extract_field_value(fields.get(SOURCE_OF_ID_FIELD_ID), default="")
        category_migrated = extract_field_value(fields.get(CATEGORY_FIELD_ID), default="")

        # Fetch LPM category for the winning ticket
        target_category = ""
        cat_field = self.field_ids.get("category", "")
        if target_ticket and cat_field:
            try:
                lpm_data = self.jira.get_issue(target_ticket, fields=[cat_field])
                target_category = extract_field_value(lpm_data.get("fields", {}).get(cat_field), default="")
                self._log(f"  LPM category for {target_ticket}: {target_category}", "dim")
            except Exception as e:
                self._log(f"  Could not fetch LPM category for {target_ticket}: {e}", "dim")

        if resolved_date:
            days_elapsed = get_business_days(created_date, resolved_date)
        else:
            days_elapsed = get_business_days_elapsed(created_date)

        target_days = sla_config["target_days"]

        if target_ticket and resolved_date:
            if days_elapsed <= target_days:
                status = "met"
            else:
                status = "breached"
        else:
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
            lpm_candidates=candidates,
            target_category=target_category,
        )
