"""
Jira API Client for Healthcare SLA CLI
"""
import requests
from base64 import b64encode
from datetime import datetime
from typing import Optional


class JiraClient:
    def __init__(self, base_url: str, email: str, token: str):
        self.base_url = base_url.rstrip('/') if base_url else None
        self.email = email
        self.token = token

        if not all([self.base_url, self.email, self.token]):
            raise ValueError(
                "Missing Jira credentials. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_TOKEN environment variables."
            )

        # Create auth header
        auth_string = f"{self.email}:{self.token}"
        auth_bytes = b64encode(auth_string.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {auth_bytes}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request to Jira API."""
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def search_issues(self, jql: str, fields: list[str] = None, max_results: int = 100) -> list[dict]:
        """Search for issues using JQL."""
        all_issues = []
        start_at = 0

        while True:
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
            }
            if fields:
                params["fields"] = ",".join(fields)

            data = self._make_request("/rest/api/3/search/jql", params)
            issues = data.get("issues", [])
            all_issues.extend(issues)

            # Check if we have more pages
            total = data.get("total", 0)
            start_at += len(issues)

            if start_at >= total or len(issues) == 0:
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
        """Get the changelog for an issue to find status transitions."""
        endpoint = f"/rest/api/3/issue/{issue_key}/changelog"
        data = self._make_request(endpoint)
        return data.get("values", [])

    def get_status_transition_date(self, issue_key: str, target_status: str) -> Optional[str]:
        """Find the date when an issue first transitioned to a given status."""
        changelog = self.get_issue_changelog(issue_key)
        for entry in changelog:
            for item in entry.get("items", []):
                if item.get("field") == "status" and (item.get("toString") or "").lower() == target_status.lower():
                    return entry.get("created")
        return None

    def get_issue_comments(self, issue_key: str) -> list[dict]:
        """Get all comments for an issue."""
        endpoint = f"/rest/api/3/issue/{issue_key}/comment"
        data = self._make_request(endpoint)
        return data.get("comments", [])

    def test_connection(self) -> dict:
        """Test the Jira connection."""
        return self._make_request("/rest/api/3/myself")
