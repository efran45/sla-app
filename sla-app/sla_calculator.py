"""
SLA Calculator for Healthcare SLA CLI
"""
from datetime import datetime, timedelta
from typing import Optional
import numpy as np


def get_business_days(start_date: datetime, end_date: datetime) -> int:
    """
    Calculate the number of business days between two dates.
    Excludes weekends (Saturday and Sunday).
    """
    if end_date < start_date:
        return 0

    # Use numpy busday_count for efficiency
    start = np.datetime64(start_date.date())
    end = np.datetime64(end_date.date())

    return int(np.busday_count(start, end))


def get_business_days_elapsed(start_date: datetime) -> int:
    """Calculate business days from start_date until now."""
    return get_business_days(start_date, datetime.now())


def parse_jira_date(date_field) -> Optional[datetime]:
    """Parse Jira date field into datetime object (timezone-naive)."""
    if not date_field:
        return None

    if isinstance(date_field, str):
        formats = [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(date_field, fmt)
                # Convert to naive datetime to avoid comparison issues
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                return dt
            except ValueError:
                continue
    return None


def extract_field_value(field, default: str = "Unknown") -> str:
    """Extract value from various Jira field structures."""
    if field is None:
        return default

    if isinstance(field, str):
        return field

    if isinstance(field, dict):
        for key in ["value", "displayValue", "name", "key"]:
            if key in field:
                return field[key]
        return str(field)

    if isinstance(field, list) and len(field) > 0:
        return extract_field_value(field[0], default)

    return str(field)


def format_elapsed_time(start: datetime, end: datetime) -> str:
    """Format the elapsed time between two datetimes as 'Xd Xh Xm'."""
    delta = end - start
    if delta.total_seconds() < 0:
        return "0d 0h 0m"
    total_minutes = int(delta.total_seconds() // 60)
    days = total_minutes // (24 * 60)
    hours = (total_minutes % (24 * 60)) // 60
    minutes = total_minutes % 60
    return f"{days}d {hours}h {minutes}m"


class SLAResult:
    """Result for a single ticket's SLA evaluation."""

    def __init__(
        self,
        source_ticket: str,
        target_ticket: Optional[str],
        created_date: datetime,
        resolved_date: Optional[datetime],
        days_elapsed: int,
        target_days: int,
        status: str,  # "met", "breached", "in_progress"
        source_of_identification: str = "",
        category_migrated: str = "",
        lpm_category: str = "",
        elapsed_time_str: Optional[str] = None,
    ):
        self.source_ticket = source_ticket
        self.target_ticket = target_ticket
        self.created_date = created_date
        self.resolved_date = resolved_date
        self.days_elapsed = days_elapsed
        self.target_days = target_days
        self.status = status
        self.source_of_identification = source_of_identification
        self.category_migrated = category_migrated
        self.lpm_category = lpm_category
        self.elapsed_time_str = elapsed_time_str

    @property
    def is_met(self) -> bool:
        return self.status == "met"

    @property
    def is_breached(self) -> bool:
        return self.status == "breached"

    @property
    def is_in_progress(self) -> bool:
        return self.status == "in_progress"


class SLASummary:
    """Summary of SLA results."""

    def __init__(self, sla_name: str, target_days: int):
        self.sla_name = sla_name
        self.target_days = target_days
        self.results: list[SLAResult] = []

    def add_result(self, result: SLAResult):
        self.results.append(result)

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def met_count(self) -> int:
        return sum(1 for r in self.results if r.is_met)

    @property
    def breached_count(self) -> int:
        return sum(1 for r in self.results if r.is_breached)

    @property
    def in_progress_count(self) -> int:
        return sum(1 for r in self.results if r.is_in_progress)

    @property
    def met_results(self) -> list[SLAResult]:
        return [r for r in self.results if r.is_met]

    @property
    def breached_results(self) -> list[SLAResult]:
        return [r for r in self.results if r.is_breached]

    @property
    def in_progress_results(self) -> list[SLAResult]:
        return [r for r in self.results if r.is_in_progress]

    @property
    def compliance_rate(self) -> float:
        """Percentage of resolved tickets that met SLA."""
        resolved = self.met_count + self.breached_count
        if resolved == 0:
            return 100.0
        return (self.met_count / resolved) * 100
