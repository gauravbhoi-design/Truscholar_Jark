"""Jira MCP Client — Ticket management, sprint data, automated issue creation."""

import httpx
import structlog
from app.config import get_settings

logger = structlog.get_logger()


class JiraMCPClient:
    """MCP-compatible client for Jira/Atlassian operations."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.jira_base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.jira_api_token}",
            "Content-Type": "application/json",
        }

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str,
        issue_type: str = "Bug",
        priority: str = "Medium",
        labels: list[str] | None = None,
    ) -> dict:
        """Create a Jira issue from agent findings."""
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": issue_type},
                "priority": {"name": priority},
            }
        }
        if labels:
            payload["fields"]["labels"] = labels

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/rest/api/3/issue",
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "key": data["key"],
                "id": data["id"],
                "url": f"{self.base_url}/browse/{data['key']}",
            }

    async def search_issues(self, jql: str, max_results: int = 20) -> dict:
        """Search Jira issues with JQL."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/search",
                headers=self.headers,
                params={"jql": jql, "maxResults": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "total": data.get("total", 0),
                "issues": [
                    {
                        "key": i["key"],
                        "summary": i["fields"]["summary"],
                        "status": i["fields"]["status"]["name"],
                        "priority": i["fields"].get("priority", {}).get("name"),
                        "assignee": (i["fields"].get("assignee") or {}).get("displayName"),
                    }
                    for i in data.get("issues", [])
                ],
            }
