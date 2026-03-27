"""Sentry MCP Client — Error tracking, issue resolution, event correlation."""

import httpx
import structlog
from app.config import get_settings

logger = structlog.get_logger()


class SentryMCPClient:
    """MCP-compatible client for Sentry error tracking."""

    def __init__(self):
        settings = get_settings()
        self.token = settings.sentry_auth_token
        self.base_url = "https://sentry.io/api/0"
        self.headers = {"Authorization": f"Bearer {self.token}"}

    async def get_issues(
        self, org: str, project: str, query: str = "is:unresolved", limit: int = 20
    ) -> dict:
        """Get Sentry issues for a project."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/projects/{org}/{project}/issues/",
                headers=self.headers,
                params={"query": query, "limit": limit},
            )
            resp.raise_for_status()
            issues = resp.json()
            return {
                "total": len(issues),
                "issues": [
                    {
                        "id": i["id"],
                        "title": i["title"],
                        "culprit": i.get("culprit"),
                        "count": i.get("count"),
                        "first_seen": i.get("firstSeen"),
                        "last_seen": i.get("lastSeen"),
                        "level": i.get("level"),
                        "status": i.get("status"),
                    }
                    for i in issues
                ],
            }

    async def get_issue_events(self, org: str, issue_id: str) -> dict:
        """Get events for a specific Sentry issue."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/organizations/{org}/issues/{issue_id}/events/",
                headers=self.headers,
                params={"limit": 10},
            )
            resp.raise_for_status()
            events = resp.json()
            return {
                "issue_id": issue_id,
                "events": [
                    {
                        "id": e["eventID"],
                        "title": e.get("title"),
                        "message": e.get("message", "")[:500],
                        "timestamp": e.get("dateCreated"),
                        "tags": {t["key"]: t["value"] for t in e.get("tags", [])[:10]},
                    }
                    for e in events
                ],
            }
