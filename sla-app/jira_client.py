"""
Jira API Client for Healthcare SLA CLI
"""
import logging
import time
import requests
from base64 import b64encode
from datetime import datetime
from typing import Optional

_log = logging.getLogger(__name__)


def _resolve_base_url(instance_url: str, token: str) -> str:
    """
    Scoped service account tokens must use the Atlassian API gateway
    (api.atlassian.com/ex/jira/{cloudId}) rather than the instance URL
    (yourcompany.atlassian.net). This fetches the cloud ID from the
    instance's public tenant_info endpoint and returns the gateway URL.
    Falls back to the original URL if the lookup fails.
    """
    instance_url = instance_url.rstrip('/')
    try:
        resp = requests.get(f"{instance_url}/_edge/tenant_info", timeout=10)
        resp.raise_for_status()
        cloud_id = resp.json().get("cloudId")
        if cloud_id:
            gateway = f"https://api.atlassian.com/ex/jira/{cloud_id}"
            _log.info("Resolved cloud ID: %s → using gateway URL: %s", cloud_id, gateway)
            return gateway
    except Exception as e:
        _log.warning("Could not resolve cloud ID from %s: %s — using instance URL", instance_url, e)
    return instance_url


class JiraClient:
    def __init__(self, base_url: str, email: str, token: str, use_gateway: bool = True):
        """
        Args:
            base_url:    Your Jira instance URL (e.g. https://yourcompany.atlassian.net).
            email:       The email address associated with the account or service account.
            token:       API token (personal or scoped service account token).
            use_gateway: If True (default), automatically resolve the Atlassian API gateway
                         URL using the cloud ID. Set to False to use the instance URL directly.
        """
        if not all([base_url, email, token]):
            raise ValueError(
                "Missing Jira credentials. JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN are all required."
            )

        self.email = email
        self.token = token
        self.instance_url = base_url.rstrip('/')
        self.base_url = _resolve_base_url(self.instance_url, token) if use_gateway else self.instance_url

        auth_string = f"{self.email}:{self.token}"
        auth_bytes = b64encode(auth_string.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {auth_bytes}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _make_request(self, endpoint: str, params: dict = None, _retries: int = 5) -> dict:
        """Make a GET request to Jira API with retry/backoff on rate limits."""
        url = f"{self.base_url}{endpoint}"
        for attempt in range(_retries):
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json()
        response.raise_for_status()  # raise after exhausting retries

    def _post_request(self, endpoint: str, body: dict, _retries: int = 5) -> dict:
        """Make a POST request to Jira API with retry/backoff on rate limits."""
        url = f"{self.base_url}{endpoint}"
        for attempt in range(_retries):
            response = requests.post(url, headers=self.headers, json=body)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json()
        response.raise_for_status()  # raise after exhausting retries

    def search_issues(self, jql: str, fields: list[str] = None, max_results: int = 100) -> list[dict]:
        """Search for issues using JQL, paging through all results via nextPageToken."""
        all_issues = []
        next_page_token = None

        while True:
            body = {"jql": jql, "maxResults": max_results}
            if fields:
                body["fields"] = [f for f in fields if f]  # strip empty field IDs
            if next_page_token:
                body["nextPageToken"] = next_page_token

            data = self._post_request("/rest/api/3/search/jql", body)
            issues = data.get("issues", [])
            all_issues.extend(issues)

            next_page_token = data.get("nextPageToken")
            if not issues or not next_page_token:
                break

        return all_issues

    def get_issue(self, issue_key: str, fields: list[str] = None) -> dict:
        """Get a single issue by key."""
        endpoint = f"/rest/api/3/issue/{issue_key}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        return self._make_request(endpoint, params)

    def get_issue_links(self, issue_key: str) -> list[dict]:
        """Get all links for an issue."""
        issue = self.get_issue(issue_key, fields=["issuelinks"])
        return issue.get("fields", {}).get("issuelinks", [])

    def get_issue_changelog(self, issue_key: str) -> list[dict]:
        """Get all changelog entries for an issue, paging through all results."""
        endpoint = f"/rest/api/3/issue/{issue_key}/changelog"
        all_values = []
        start_at = 0
        while True:
            data = self._make_request(endpoint, params={"startAt": start_at, "maxResults": 100})
            values = data.get("values", [])
            all_values.extend(values)
            start_at += len(values)
            if start_at >= data.get("total", 0) or not values:
                break
        return all_values

    def get_status_transition_date(self, issue_key: str, target_status) -> Optional[str]:
        """Find the date when an issue first transitioned to a given status (or any status in a list)."""
        if isinstance(target_status, str):
            target_statuses = {target_status.lower()}
        else:
            target_statuses = {s.lower() for s in target_status}

        changelog = self.get_issue_changelog(issue_key)
        for entry in changelog:
            for item in entry.get("items", []):
                if item.get("field") == "status" and (item.get("toString") or "").lower() in target_statuses:
                    return entry.get("created")
        return None

    def get_issue_comments(self, issue_key: str) -> list[dict]:
        """Get all comments for an issue, paging through all results."""
        endpoint = f"/rest/api/3/issue/{issue_key}/comment"
        all_comments = []
        start_at = 0
        while True:
            data = self._make_request(endpoint, params={"startAt": start_at, "maxResults": 100})
            comments = data.get("comments", [])
            all_comments.extend(comments)
            start_at += len(comments)
            if start_at >= data.get("total", 0) or not comments:
                break
        return all_comments

    def test_connection(self) -> dict:
        """Test the Jira connection."""
        return self._make_request("/rest/api/3/myself")
