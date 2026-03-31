"""
AI DevOps Platform — GitHub Integration

Real GitHub API integration for:
- Listing repos, PRs, issues
- Getting repo health status
- Webhook events (future)
"""

import logging
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubClient:
    def __init__(self):
        self.token = settings.github_token
        self._client = None

    @property
    def headers(self):
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    @property
    def client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=GITHUB_API,
                headers=self.headers,
                timeout=30.0,
            )
        return self._client

    @property
    def is_connected(self) -> bool:
        return bool(self.token)

    # ── Repos ──────────────────────────────────────────────────

    async def list_repos(self, org: str = None, per_page: int = 30) -> List[Dict[str, Any]]:
        """List repos for authenticated user or org."""
        try:
            if org:
                resp = await self.client.get(f"/orgs/{org}/repos", params={"per_page": per_page, "sort": "updated"})
            else:
                resp = await self.client.get("/user/repos", params={"per_page": per_page, "sort": "updated", "affiliation": "owner,collaborator,organization_member"})
            resp.raise_for_status()
            repos = resp.json()
            return [self._format_repo(r) for r in repos]
        except Exception as e:
            logger.error(f"GitHub list_repos error: {e}")
            return []

    async def get_repo(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self.client.get(f"/repos/{owner}/{repo}")
            resp.raise_for_status()
            return self._format_repo(resp.json())
        except Exception as e:
            logger.error(f"GitHub get_repo error: {e}")
            return None

    async def get_repo_health(self, owner: str, repo: str) -> Dict[str, Any]:
        """Get comprehensive repo health: issues, PRs, commits, CI status."""
        health = {"issues": 0, "prs": 0, "status": "unknown", "last_commit": None}
        try:
            # Open issues
            resp = await self.client.get(f"/repos/{owner}/{repo}/issues", params={"state": "open", "per_page": 1})
            if resp.status_code == 200:
                # Total count from header or list length
                health["issues"] = int(resp.headers.get("X-Total-Count", len(resp.json())))

            # Open PRs
            resp = await self.client.get(f"/repos/{owner}/{repo}/pulls", params={"state": "open", "per_page": 1})
            if resp.status_code == 200:
                health["prs"] = int(resp.headers.get("X-Total-Count", len(resp.json())))

            # Latest commit
            resp = await self.client.get(f"/repos/{owner}/{repo}/commits", params={"per_page": 1})
            if resp.status_code == 200:
                commits = resp.json()
                if commits:
                    health["last_commit"] = commits[0].get("sha", "")[:7]
                    health["last_commit_date"] = commits[0].get("commit", {}).get("committer", {}).get("date")
                    health["last_commit_msg"] = commits[0].get("commit", {}).get("message", "")[:80]

            # Determine status
            if health["issues"] > 10:
                health["status"] = "critical"
            elif health["issues"] > 5:
                health["status"] = "warning"
            else:
                health["status"] = "healthy"

        except Exception as e:
            logger.error(f"GitHub health check error: {e}")

        return health

    # ── Issues ─────────────────────────────────────────────────

    async def list_issues(self, owner: str, repo: str, state: str = "open", limit: int = 20) -> List[Dict[str, Any]]:
        try:
            resp = await self.client.get(
                f"/repos/{owner}/{repo}/issues",
                params={"state": state, "per_page": limit, "sort": "updated"}
            )
            resp.raise_for_status()
            return [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "state": i["state"],
                    "labels": [l["name"] for l in i.get("labels", [])],
                    "created_at": i["created_at"],
                    "updated_at": i["updated_at"],
                    "user": i.get("user", {}).get("login", ""),
                    "comments": i.get("comments", 0),
                    "url": i.get("html_url", ""),
                }
                for i in resp.json()
                if "pull_request" not in i  # Filter out PRs from issues
            ]
        except Exception as e:
            logger.error(f"GitHub list_issues error: {e}")
            return []

    # ── Pull Requests ──────────────────────────────────────────

    async def list_prs(self, owner: str, repo: str, state: str = "open", limit: int = 20) -> List[Dict[str, Any]]:
        try:
            resp = await self.client.get(
                f"/repos/{owner}/{repo}/pulls",
                params={"state": state, "per_page": limit, "sort": "updated"}
            )
            resp.raise_for_status()
            return [
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "state": pr["state"],
                    "user": pr.get("user", {}).get("login", ""),
                    "created_at": pr["created_at"],
                    "updated_at": pr["updated_at"],
                    "head_branch": pr.get("head", {}).get("ref", ""),
                    "base_branch": pr.get("base", {}).get("ref", ""),
                    "mergeable": pr.get("mergeable"),
                    "draft": pr.get("draft", False),
                    "url": pr.get("html_url", ""),
                    "additions": pr.get("additions", 0),
                    "deletions": pr.get("deletions", 0),
                    "changed_files": pr.get("changed_files", 0),
                }
                for pr in resp.json()
            ]
        except Exception as e:
            logger.error(f"GitHub list_prs error: {e}")
            return []

    # ── Branches ───────────────────────────────────────────────

    async def list_branches(self, owner: str, repo: str) -> List[str]:
        try:
            resp = await self.client.get(f"/repos/{owner}/{repo}/branches", params={"per_page": 30})
            resp.raise_for_status()
            return [b["name"] for b in resp.json()]
        except Exception as e:
            logger.error(f"GitHub list_branches error: {e}")
            return []

    # ── Workflows / CI ─────────────────────────────────────────

    async def get_ci_status(self, owner: str, repo: str, branch: str = "main") -> Dict[str, Any]:
        try:
            resp = await self.client.get(
                f"/repos/{owner}/{repo}/actions/runs",
                params={"branch": branch, "per_page": 5}
            )
            resp.raise_for_status()
            runs = resp.json().get("workflow_runs", [])
            if runs:
                latest = runs[0]
                return {
                    "status": latest.get("conclusion", latest.get("status", "unknown")),
                    "name": latest.get("name", ""),
                    "url": latest.get("html_url", ""),
                    "created_at": latest.get("created_at"),
                    "duration": None,
                }
            return {"status": "none", "name": "", "url": ""}
        except Exception as e:
            logger.error(f"GitHub CI status error: {e}")
            return {"status": "unknown"}

    # ── User Info ──────────────────────────────────────────────

    async def get_authenticated_user(self) -> Optional[Dict[str, str]]:
        try:
            resp = await self.client.get("/user")
            resp.raise_for_status()
            u = resp.json()
            return {"login": u["login"], "name": u.get("name", ""), "avatar": u.get("avatar_url", "")}
        except:
            return None

    # ── Helpers ─────────────────────────────────────────────────

    def _format_repo(self, r: dict) -> Dict[str, Any]:
        return {
            "id": str(r["id"]),
            "name": r["name"],
            "full_name": r["full_name"],
            "language": r.get("language", ""),
            "default_branch": r.get("default_branch", "main"),
            "stars": r.get("stargazers_count", 0),
            "open_issues": r.get("open_issues_count", 0),
            "url": r.get("html_url", ""),
            "description": r.get("description", "") or "",
            "topics": r.get("topics", []),
            "visibility": r.get("visibility", "private"),
            "updated_at": r.get("updated_at"),
            "fork": r.get("fork", False),
            "size": r.get("size", 0),
        }

    async def close(self):
        if self._client:
            await self._client.aclose()


github_client = GitHubClient()
