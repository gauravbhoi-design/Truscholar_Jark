"""Zoho Sprints MCP Client — Sprint boards, tasks, and project management integration."""

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

ZOHO_SPRINTS_API = "https://sprints.zoho.com/zsapi"


class ZohoSprintsMCPClient:
    """MCP-compatible client for Zoho Sprints operations.

    Uses per-user OAuth tokens for accessing their Zoho Sprints data.
    """

    def __init__(self, access_token: str, portal_name: str = ""):
        if not access_token:
            raise ValueError("Zoho access token required. Connect Zoho in Settings.")
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        self.portal_name = portal_name

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make authenticated request to Zoho Sprints API."""
        url = f"{ZOHO_SPRINTS_API}{path}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.request(method, url, headers=self.headers, **kwargs)
            if resp.status_code == 401:
                return {"error": "Zoho token expired. Please reconnect in Settings."}
            if resp.status_code == 403:
                return {"error": "Permission denied. Check Zoho Sprints permissions."}
            if resp.status_code != 200:
                return {"error": f"Zoho API error {resp.status_code}: {resp.text[:200]}"}
            return resp.json()

    # ─── Portal & Teams ────────────────────────────────────────────────

    async def get_portals(self) -> dict:
        """List all Zoho Sprints portals the user has access to."""
        data = await self._request("GET", "/portals/")
        if "error" in data:
            return data
        portals = data.get("portals", [])
        return {
            "portals": [
                {
                    "id": p.get("id_string", p.get("id", "")),
                    "name": p.get("name", ""),
                    "is_default": p.get("is_default", False),
                }
                for p in portals
            ]
        }

    async def get_teams(self, portal_id: str) -> dict:
        """List all teams/projects in a portal."""
        data = await self._request("GET", f"/portals/{portal_id}/teams/")
        if "error" in data:
            return data
        teams = data.get("teams", [])
        return {
            "teams": [
                {
                    "id": t.get("id_string", t.get("id", "")),
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "owner": t.get("owner_name", ""),
                }
                for t in teams
            ]
        }

    # ─── Sprints ───────────────────────────────────────────────────────

    async def get_sprints(self, portal_id: str, team_id: str) -> dict:
        """List sprints for a team."""
        data = await self._request("GET", f"/portals/{portal_id}/teams/{team_id}/sprints/")
        if "error" in data:
            return data
        sprints = data.get("sprints", [])
        return {
            "sprints": [
                {
                    "id": s.get("id_string", s.get("id", "")),
                    "name": s.get("name", ""),
                    "status": s.get("status", ""),
                    "start_date": s.get("start_date", ""),
                    "end_date": s.get("end_date", ""),
                    "completed_points": s.get("completed_points", 0),
                    "total_points": s.get("total_points", 0),
                }
                for s in sprints
            ]
        }

    async def get_active_sprint(self, portal_id: str, team_id: str) -> dict:
        """Get the currently active sprint with items."""
        sprints_data = await self.get_sprints(portal_id, team_id)
        if "error" in sprints_data:
            return sprints_data

        active = None
        for s in sprints_data.get("sprints", []):
            if s.get("status") == "active":
                active = s
                break

        if not active:
            return {"error": "No active sprint found", "sprints": sprints_data.get("sprints", [])}

        # Get sprint items
        items_data = await self.get_sprint_items(portal_id, team_id, active["id"])

        return {
            "sprint": active,
            "items": items_data.get("items", []),
            "summary": items_data.get("summary", {}),
        }

    # ─── Sprint Items (User Stories, Tasks, Bugs) ──────────────────────

    async def get_sprint_items(self, portal_id: str, team_id: str, sprint_id: str) -> dict:
        """Get all items in a sprint with status breakdown."""
        data = await self._request(
            "GET",
            f"/portals/{portal_id}/teams/{team_id}/sprints/{sprint_id}/items/",
        )
        if "error" in data:
            return data

        items = data.get("items", data.get("sprintItems", []))
        formatted = []
        status_counts: dict[str, int] = {}

        for item in items:
            status = item.get("status", {}).get("name", "Unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

            formatted.append({
                "id": item.get("id_string", item.get("id", "")),
                "title": item.get("name", item.get("title", "")),
                "type": item.get("type", {}).get("name", "item"),
                "status": status,
                "priority": item.get("priority", {}).get("name", "None"),
                "assignee": item.get("owner_name", "Unassigned"),
                "points": item.get("points", 0),
                "created_date": item.get("created_date", ""),
            })

        return {
            "sprint_id": sprint_id,
            "total_items": len(formatted),
            "items": formatted,
            "summary": status_counts,
        }

    # ─── Backlog ───────────────────────────────────────────────────────

    async def get_backlog(self, portal_id: str, team_id: str) -> dict:
        """Get backlog items."""
        data = await self._request(
            "GET",
            f"/portals/{portal_id}/teams/{team_id}/backlog/",
        )
        if "error" in data:
            return data

        items = data.get("items", data.get("backlogItems", []))
        return {
            "total_items": len(items),
            "items": [
                {
                    "id": item.get("id_string", ""),
                    "title": item.get("name", item.get("title", "")),
                    "type": item.get("type", {}).get("name", "item"),
                    "priority": item.get("priority", {}).get("name", "None"),
                    "points": item.get("points", 0),
                }
                for item in items[:50]
            ],
        }

    # ─── Team Members ──────────────────────────────────────────────────

    async def get_team_members(self, portal_id: str, team_id: str) -> dict:
        """Get team members."""
        data = await self._request(
            "GET",
            f"/portals/{portal_id}/teams/{team_id}/members/",
        )
        if "error" in data:
            return data

        members = data.get("members", [])
        return {
            "total_members": len(members),
            "members": [
                {
                    "id": m.get("id_string", ""),
                    "name": m.get("name", ""),
                    "email": m.get("email", ""),
                    "role": m.get("role", ""),
                }
                for m in members
            ],
        }
