"""Zoho Sprints MCP Client — Sprint boards, tasks, and project management integration."""

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Zoho Sprints REST API base. The UI and API share the same host —
# https://sprints.zoho.in/zsapi/ (or .com / .eu etc for other regions).
# The separate `sprintsapi.zoho.*` hostname is a red herring and
# returns 404 for everything. Can be overridden via env var for
# non-India accounts.
#
# IMPORTANT: every Zoho Sprints API call must include an `action`
# query parameter (e.g. ?action=data). Without it Zoho returns
# 7404 "Given URL is wrong" — this is easy to mistake for a bad path.
ZOHO_SPRINTS_API = getattr(
    settings, "zoho_sprints_api_base", None
) or "https://sprints.zoho.in/zsapi"


class ZohoSprintsMCPClient:
    """MCP-compatible client for Zoho Sprints operations.

    Uses per-user OAuth tokens for accessing their Zoho Sprints data.
    """

    def __init__(self, access_token: str, portal_name: str = ""):
        if not access_token:
            raise ValueError("Zoho access token required. Connect Zoho in Settings.")
        # Zoho Sprints /zsapi/ endpoints accept the standard "Bearer"
        # scheme — confirmed via /auth/zoho/debug/exact which returned
        # HTTP 200 for Bearer on /team/{id}/projects/{id}/priority/.
        # The legacy "Zoho-oauthtoken" scheme also works but Bearer is
        # the cleaner convention and what the rest of the codebase uses.
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        self.portal_name = portal_name

    async def _request(self, method: str, path: str, action: str = "data", **kwargs) -> dict:
        """Make authenticated request to Zoho Sprints API.

        Zoho Sprints uses an action-based API: every endpoint needs an
        `action` query parameter. The most common value is `data` for
        list/get operations. Caller can override via the `action` arg.
        """
        url = f"{ZOHO_SPRINTS_API}{path}"
        params = kwargs.pop("params", {}) or {}
        if "action" not in params:
            params["action"] = action

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.request(method, url, headers=self.headers, params=params, **kwargs)
            logger.info(
                "Zoho API call",
                method=method,
                path=path,
                action=params.get("action"),
                status=resp.status_code,
                body_preview=resp.text[:300],
            )
            if resp.status_code == 401:
                return {"error": "Zoho token expired. Please reconnect in Settings."}
            if resp.status_code == 403:
                return {"error": "Permission denied. Check Zoho Sprints permissions."}
            if resp.status_code != 200:
                return {"error": f"Zoho API error {resp.status_code}: {resp.text[:200]}"}
            try:
                return resp.json()
            except Exception as e:
                return {"error": f"Zoho returned non-JSON: {str(e)[:100]}", "raw": resp.text[:300]}

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
        data = await self._request("GET", f"/portals/{portal_id}/team/")
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

    # ─── Auto-discovery: groups → projects → sprints ──────────────────

    async def list_project_groups(self, workspace_id: str) -> dict:
        """List project groups in a workspace.

        Confirmed-working URL shape:
        GET /zsapi/team/{workspace_id}/projectgroups/?action=data
        """
        data = await self._request(
            "GET",
            f"/team/{workspace_id}/projectgroups/",
            params={"action": "data", "index": "1", "range": "250"},
        )
        if "error" in data:
            return data

        logger.info("Zoho project groups response keys", keys=list(data.keys())[:20])

        group_ids = data.get("groupIds", [])
        group_obj = data.get("groupJObj", {})
        group_prop = data.get("group_prop", {})
        name_idx = group_prop.get("groupName", 0)
        default_idx = group_prop.get("isDefault", 1)

        groups = []
        for gid in group_ids:
            values = group_obj.get(gid, [])
            groups.append({
                "id": gid,
                "name": values[name_idx] if len(values) > name_idx else "",
                "is_default": bool(values[default_idx]) if len(values) > default_idx else False,
            })

        return {"groups": groups}

    async def list_projects_in_group(self, workspace_id: str, group_id: str) -> dict:
        """List projects within a project group.

        URL shape guessed from the pattern confirmed for project groups.
        Tries a few path/action combinations and returns the first 200.
        """
        candidates = [
            (
                f"/team/{workspace_id}/projectgroups/{group_id}/projects/",
                {"action": "data", "index": "1", "range": "250"},
            ),
            (
                f"/team/{workspace_id}/projects/",
                {"action": "data", "groupId": group_id, "index": "1", "range": "250"},
            ),
            (
                f"/team/{workspace_id}/projects/",
                {"action": "allprojects", "groupId": group_id, "index": "1", "range": "250"},
            ),
            (
                f"/team/{workspace_id}/projects/",
                {"action": "data", "index": "1", "range": "250"},
            ),
        ]

        data = None
        last_error = None
        for path, params in candidates:
            resp = await self._request("GET", path, params=params)
            if "error" not in resp:
                data = resp
                logger.info(
                    "Zoho projects-in-group candidate matched",
                    path=path,
                    params=params,
                )
                break
            last_error = resp["error"]
            if "7404" not in last_error:
                break

        if data is None:
            return {"error": last_error or "No working project-list endpoint found"}

        logger.info(
            "Zoho projects-in-group response keys",
            group_id=group_id,
            keys=list(data.keys())[:20],
        )

        # Zoho's usual shape: ids list + JObj + prop index
        project_ids = data.get("projectIds", []) or data.get("projIds", [])
        project_obj = data.get("projectJObj", {}) or data.get("projJObj", {})
        project_prop = data.get("project_prop", {}) or data.get("proj_prop", {})

        name_idx = project_prop.get("projectName", 0) or project_prop.get("projName", 0)

        projects = []
        for pid in project_ids:
            values = project_obj.get(pid, [])
            projects.append({
                "id": pid,
                "name": values[name_idx] if len(values) > name_idx else "",
                "raw": values,
            })

        return {
            "projects": projects,
            "raw_response_keys": list(data.keys())[:20],
        }

    async def list_all_projects(self, workspace_id: str) -> dict:
        """Walk every project group and collect all projects across them."""
        groups_data = await self.list_project_groups(workspace_id)
        if "error" in groups_data:
            return groups_data

        all_projects = []
        for group in groups_data.get("groups", []):
            projects_data = await self.list_projects_in_group(workspace_id, group["id"])
            if "error" in projects_data:
                logger.warning(
                    "Failed to list projects in group",
                    group_id=group["id"],
                    error=projects_data.get("error"),
                )
                continue
            for p in projects_data.get("projects", []):
                p["group_name"] = group["name"]
                p["group_id"] = group["id"]
                all_projects.append(p)

        return {"projects": all_projects}

    # ─── Sprint discovery via team_id + project_id (confirmed working) ─

    async def get_sprints_for_project(self, team_id: str, project_id: str) -> dict:
        """List sprints for a specific project within a team.

        Confirmed URL shape from the Zoho web UI:
        /zsapi/team/{team_id}/projects/{project_id}/sprints/{sprint_id}/...

        For listing (no sprint_id), Zoho uses action-based query params
        and the action name varies per endpoint. We try the most
        likely ones in order and return the first that responds.
        """
        path = f"/team/{team_id}/projects/{project_id}/sprints/"

        # Try the most likely action names in order. First 200 wins.
        # `data` is the generic Zoho list action (confirmed on
        # /projectgroups/ and /priority/). Others are fallbacks.
        candidate_actions = ["data", "allsprints", "sprintlist", "sprintsinproject"]

        data = None
        last_error = None
        for action in candidate_actions:
            resp = await self._request(
                "GET",
                path,
                params={"action": action, "index": "1", "range": "250"},
            )
            if "error" not in resp:
                data = resp
                logger.info("Zoho sprint list action matched", action=action)
                break
            last_error = resp["error"]
            # 7404 "URL wrong" means wrong action name — keep trying.
            # Other errors (auth, permission) won't improve with another action name.
            if "7404" not in last_error:
                break

        if data is None:
            return {"error": last_error or "Zoho sprint list: no action name matched"}
        if "error" in data:
            return data

        # Zoho's response shape is undocumented — log everything so we
        # can map it out from real responses, and try a few common shapes.
        logger.info("Zoho sprints response keys", keys=list(data.keys())[:20])

        sprints = (
            data.get("sprints")
            or data.get("sprint")
            or data.get("sprintList")
            or data.get("allSprints")
            or []
        )

        # Zoho often returns lookups as a parallel structure:
        # { "sprintPropertyName": {field: index}, "sprintJObj": {id: [values]} }
        # If we see that shape, convert to a list of dicts.
        if not sprints and "sprintJObj" in data and "sprint_prop" in data:
            prop: dict = data["sprint_prop"]
            obj: dict = data["sprintJObj"]
            sprints = []
            for sprint_id, values in obj.items():
                row = {"id": sprint_id}
                for field, idx in prop.items():
                    try:
                        row[field] = values[idx]
                    except (IndexError, TypeError):
                        pass
                sprints.append(row)

        return {
            "team_id": team_id,
            "project_id": project_id,
            "sprints": [
                {
                    "id": str(s.get("id") or s.get("sprintId") or s.get("id_string", "")),
                    "name": s.get("name") or s.get("sprintName") or "",
                    "status": s.get("status") or s.get("sprintStatus") or "",
                    "start_date": s.get("start_date") or s.get("startDate") or "",
                    "end_date": s.get("end_date") or s.get("endDate") or "",
                    "completed_points": s.get("completed_points", 0),
                    "total_points": s.get("total_points", 0),
                }
                for s in sprints
            ],
            "raw_response_keys": list(data.keys())[:20],  # for debugging
        }

    async def get_active_sprint_for_project(self, team_id: str, project_id: str) -> dict:
        """Get the active sprint for a specific project, with items.

        Uses get_sprints_for_project then picks the first sprint whose
        status looks active. Falls back to the most recent sprint.
        """
        sprints_data = await self.get_sprints_for_project(team_id, project_id)
        if "error" in sprints_data:
            return sprints_data

        sprints = sprints_data.get("sprints", [])
        if not sprints:
            return {
                "error": "No sprints found for this project. Check your team_id and project_id in Settings.",
                "sprints": [],
                "raw_response_keys": sprints_data.get("raw_response_keys"),
            }

        active_keywords = {"active", "in progress", "inprogress", "started", "running", "open"}
        active = None
        for s in sprints:
            status = (s.get("status") or "").strip().lower()
            if status in active_keywords:
                active = s
                break

        if not active:
            # Fallback: most recent by start_date
            try:
                active = sorted(sprints, key=lambda x: x.get("start_date") or "", reverse=True)[0]
            except Exception:
                active = sprints[0]

        return {
            "sprint": active,
            "items": [],  # TODO: fetch items once we know the items URL shape
            "summary": {},
            "all_sprints": sprints,
        }

    # ─── Legacy portals/teams methods (kept for backward compat) ───────

    async def get_sprints(self, portal_id: str, team_id: str) -> dict:
        """List sprints for a team."""
        data = await self._request("GET", f"/portals/{portal_id}/team/{team_id}/sprints/")
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
        """Get the currently active sprint with items.

        Zoho's status field varies by region/account ('Active', 'active',
        'In Progress', 'Started', etc.) so the match is case-insensitive
        and tries several common variants. If nothing matches, fall back
        to the most recently started sprint so the dashboard still
        renders something useful.
        """
        sprints_data = await self.get_sprints(portal_id, team_id)
        if "error" in sprints_data:
            return sprints_data

        sprints = sprints_data.get("sprints", [])
        logger.info(
            "Zoho sprints retrieved",
            count=len(sprints),
            statuses=[s.get("status") for s in sprints[:10]],
        )

        active_keywords = {"active", "in progress", "inprogress", "started", "running", "open"}
        active = None
        for s in sprints:
            status = (s.get("status") or "").strip().lower()
            if status in active_keywords:
                active = s
                break

        # Fallback: most recent by start_date so the user always sees data
        if not active and sprints:
            try:
                active = sorted(
                    sprints,
                    key=lambda x: x.get("start_date") or "",
                    reverse=True,
                )[0]
                logger.info("No active sprint, falling back to most recent", sprint=active.get("name"))
            except Exception:
                active = sprints[0]

        if not active:
            return {
                "error": "No sprints found in this team. Create one in Zoho Sprints first.",
                "sprints": sprints,
            }

        # Get sprint items
        items_data = await self.get_sprint_items(portal_id, team_id, active["id"])

        return {
            "sprint": active,
            "items": items_data.get("items", []),
            "summary": items_data.get("summary", {}),
            "all_sprints": sprints,
        }

    # ─── Sprint Items (User Stories, Tasks, Bugs) ──────────────────────

    async def get_sprint_items(self, portal_id: str, team_id: str, sprint_id: str) -> dict:
        """Get all items in a sprint with status breakdown."""
        data = await self._request(
            "GET",
            f"/portals/{portal_id}/team/{team_id}/sprints/{sprint_id}/items/",
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
            f"/portals/{portal_id}/team/{team_id}/backlog/",
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
            f"/portals/{portal_id}/team/{team_id}/members/",
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
