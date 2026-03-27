"""GitHub MCP Client — Connects to repositories, PRs, issues, and CI status."""

import httpx
import structlog
from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

GITHUB_API = "https://api.github.com"


class GitHubMCPClient:
    """MCP-compatible client for GitHub operations.

    Uses per-user OAuth tokens when available (from GitHub sign-in),
    falls back to the global token from settings.
    """

    def __init__(self, user_token: str | None = None):
        token = user_token or settings.github_token
        if not token:
            raise ValueError(
                "No GitHub token available. Please sign in with GitHub to authorize repository access."
            )
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(self, method: str, path: str, **kwargs):
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"{GITHUB_API}{path}"
            resp = await client.request(method, url, headers=self.headers, **kwargs)
            if resp.status_code == 404:
                params = kwargs.get("params", {})
                branch = params.get("sha", params.get("ref", ""))
                detail = f" (branch: '{branch}')" if branch else ""
                raise httpx.HTTPStatusError(
                    f"GitHub 404: {path}{detail} not found. Check that the repo, branch, or resource exists.",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
            return resp.json()

    # ─── Repository Operations ──────────────────────────────────────────

    async def read_file(self, repo: str, path: str, ref: str = "main") -> dict:
        """Read a file from a GitHub repository."""
        data = await self._request("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
        import base64
        content = base64.b64decode(data.get("content", "")).decode("utf-8")
        return {"path": path, "content": content, "sha": data.get("sha"), "size": data.get("size")}

    async def search_code(self, repo: str, query: str, file_type: str | None = None) -> dict:
        """Search code in a repository."""
        q = f"{query} repo:{repo}"
        if file_type:
            q += f" language:{file_type}"
        data = await self._request("GET", "/search/code", params={"q": q, "per_page": 20})
        return {
            "total_count": data.get("total_count", 0),
            "items": [
                {"path": item["path"], "name": item["name"], "url": item["html_url"]}
                for item in data.get("items", [])
            ],
        }

    async def list_tree(self, repo: str, path: str = "", ref: str = "main") -> dict:
        """List directory contents in a repository."""
        data = await self._request(
            "GET", f"/repos/{repo}/contents/{path}", params={"ref": ref}
        )
        if isinstance(data, list):
            return {
                "items": [
                    {"name": item["name"], "type": item["type"], "path": item["path"], "size": item.get("size", 0)}
                    for item in data
                ]
            }
        return {"items": [data]}

    async def create_or_update_file(
        self, repo: str, path: str, content: str, message: str, branch: str = "main"
    ) -> dict:
        """Create or update a file in a GitHub repository."""
        import base64

        encoded = base64.b64encode(content.encode()).decode()
        body: dict = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }

        # Check if file exists to get its SHA (required for updates)
        try:
            existing = await self._request("GET", f"/repos/{repo}/contents/{path}", params={"ref": branch})
            body["sha"] = existing["sha"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{GITHUB_API}/repos/{repo}/contents/{path}",
                headers=self.headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "path": data["content"]["path"],
            "sha": data["content"]["sha"],
            "commit_sha": data["commit"]["sha"],
            "commit_message": data["commit"]["message"],
            "url": data["content"]["html_url"],
        }

    # ─── Commit Operations ──────────────────────────────────────────────

    async def get_commits(
        self, repo: str, branch: str = "main", limit: int = 20, since: str | None = None
    ) -> dict:
        """Get recent commits."""
        params = {"sha": branch, "per_page": min(limit, 100)}
        if since:
            params["since"] = since
        data = await self._request("GET", f"/repos/{repo}/commits", params=params)
        return {
            "commits": [
                {
                    "sha": c["sha"],
                    "message": c["commit"]["message"],
                    "author": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                    "url": c["html_url"],
                }
                for c in data
            ]
        }

    async def get_commit_diff(self, repo: str, sha: str) -> dict:
        """Get diff for a specific commit."""
        data = await self._request("GET", f"/repos/{repo}/commits/{sha}")
        return {
            "sha": sha,
            "message": data["commit"]["message"],
            "stats": data.get("stats", {}),
            "files": [
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                    "patch": f.get("patch", "")[:2000],  # Truncate large diffs
                }
                for f in data.get("files", [])
            ],
        }

    async def compare(self, repo: str, base: str, head: str) -> dict:
        """Compare two refs."""
        data = await self._request("GET", f"/repos/{repo}/compare/{base}...{head}")
        return {
            "status": data.get("status"),
            "ahead_by": data.get("ahead_by"),
            "behind_by": data.get("behind_by"),
            "total_commits": data.get("total_commits"),
            "files_changed": len(data.get("files", [])),
            "commits": [
                {"sha": c["sha"][:8], "message": c["commit"]["message"][:100]}
                for c in data.get("commits", [])[:20]
            ],
        }

    # ─── PR Operations ──────────────────────────────────────────────────

    async def get_pull_request(self, repo: str, pr_number: int) -> dict:
        """Get PR details."""
        data = await self._request("GET", f"/repos/{repo}/pulls/{pr_number}")
        return {
            "number": data["number"],
            "title": data["title"],
            "state": data["state"],
            "body": (data.get("body") or "")[:2000],
            "user": data["user"]["login"],
            "created_at": data["created_at"],
            "merged": data.get("merged", False),
            "additions": data.get("additions", 0),
            "deletions": data.get("deletions", 0),
            "changed_files": data.get("changed_files", 0),
        }

    # ─── CI/CD Operations ───────────────────────────────────────────────

    async def get_workflow_runs(self, repo: str, run_id: int | None = None) -> dict:
        """Get GitHub Actions workflow run status."""
        if run_id:
            data = await self._request("GET", f"/repos/{repo}/actions/runs/{run_id}")
            return self._format_run(data)
        else:
            data = await self._request(
                "GET", f"/repos/{repo}/actions/runs", params={"per_page": 5}
            )
            return {
                "runs": [self._format_run(r) for r in data.get("workflow_runs", [])[:5]]
            }

    def _format_run(self, run: dict) -> dict:
        return {
            "id": run["id"],
            "name": run.get("name"),
            "status": run["status"],
            "conclusion": run.get("conclusion"),
            "branch": run["head_branch"],
            "commit_sha": run["head_sha"][:8],
            "created_at": run["created_at"],
            "url": run["html_url"],
        }

    # ─── CI/CD Deep Analysis ─────────────────────────────────────────

    async def list_workflow_files(self, repo: str) -> dict:
        """List all GitHub Actions workflow files in .github/workflows/."""
        try:
            data = await self._request("GET", f"/repos/{repo}/contents/.github/workflows")
            if isinstance(data, list):
                return {
                    "workflows": [
                        {"name": f["name"], "path": f["path"]}
                        for f in data if f["name"].endswith((".yml", ".yaml"))
                    ]
                }
            return {"workflows": []}
        except httpx.HTTPStatusError:
            return {"workflows": [], "note": "No .github/workflows directory found"}

    async def get_workflow_file_content(self, repo: str, workflow_path: str) -> dict:
        """Read a workflow YAML file and return its content."""
        return await self.read_file(repo, workflow_path)

    async def get_failed_runs(self, repo: str, limit: int = 10) -> dict:
        """Get recent failed workflow runs with failure details."""
        data = await self._request(
            "GET",
            f"/repos/{repo}/actions/runs",
            params={"status": "failure", "per_page": min(limit, 30)},
        )
        runs = []
        for r in data.get("workflow_runs", [])[:limit]:
            run_info = self._format_run(r)
            # Try to get failed job logs
            try:
                jobs_data = await self._request("GET", f"/repos/{repo}/actions/runs/{r['id']}/jobs")
                failed_jobs = []
                for job in jobs_data.get("jobs", []):
                    if job.get("conclusion") == "failure":
                        failed_steps = [
                            {"name": s["name"], "conclusion": s.get("conclusion", "")}
                            for s in job.get("steps", [])
                            if s.get("conclusion") == "failure"
                        ]
                        failed_jobs.append({
                            "name": job["name"],
                            "failed_steps": failed_steps,
                        })
                run_info["failed_jobs"] = failed_jobs
            except Exception:
                pass
            runs.append(run_info)

        return {"total_failed": len(runs), "failed_runs": runs}

    async def get_workflow_run_logs(self, repo: str, run_id: int) -> dict:
        """Get job logs for a specific workflow run."""
        try:
            jobs_data = await self._request("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs")
            jobs = []
            for job in jobs_data.get("jobs", []):
                steps = [
                    {
                        "name": s["name"],
                        "status": s.get("status", ""),
                        "conclusion": s.get("conclusion", ""),
                        "number": s.get("number", 0),
                    }
                    for s in job.get("steps", [])
                ]
                jobs.append({
                    "name": job["name"],
                    "status": job.get("status", ""),
                    "conclusion": job.get("conclusion", ""),
                    "started_at": job.get("started_at", ""),
                    "completed_at": job.get("completed_at", ""),
                    "steps": steps,
                })
            return {"run_id": run_id, "jobs": jobs}
        except Exception as e:
            return {"error": str(e)}

    async def analyze_workflow_gcp_config(self, repo: str) -> dict:
        """Analyze all workflow files for GCP-related configuration.

        Extracts: service accounts, project IDs, regions, secrets used,
        GCP APIs referenced, and potential misconfigurations.
        """
        import base64
        import re

        workflows = await self.list_workflow_files(repo)
        gcp_configs = []

        for wf in workflows.get("workflows", []):
            try:
                file_data = await self._request(
                    "GET", f"/repos/{repo}/contents/{wf['path']}"
                )
                content = base64.b64decode(file_data.get("content", "")).decode("utf-8")

                config = {
                    "workflow": wf["name"],
                    "path": wf["path"],
                    "gcp_project_ids": list(set(re.findall(r'project[_-]?id:\s*["\']?(\S+?)["\']?\s', content, re.I))),
                    "service_accounts": list(set(re.findall(r'[\w.-]+@[\w.-]+\.iam\.gserviceaccount\.com', content))),
                    "gcp_regions": list(set(re.findall(r'region:\s*["\']?([\w-]+)["\']?', content))),
                    "gcp_secrets": list(set(re.findall(r'\$\{\{\s*secrets\.(GCP_\w+|GOOGLE_\w+|GCLOUD_\w+)\s*\}\}', content))),
                    "gcp_actions": list(set(re.findall(r'google-github-actions/[\w-]+', content))),
                    "uses_workload_identity": "workload_identity_provider" in content.lower(),
                    "uses_sa_key": "credentials_json" in content.lower() or "GOOGLE_APPLICATION_CREDENTIALS" in content,
                    "docker_push_to_gcr": "gcr.io" in content or "docker.pkg.dev" in content,
                    "deploys_to_cloud_run": "cloud-run" in content.lower() or "run deploy" in content.lower(),
                    "deploys_to_gke": "gke" in content.lower() or "get-gke-credentials" in content.lower(),
                    "uses_terraform": "terraform" in content.lower(),
                }

                # Flag potential issues
                issues = []
                if config["uses_sa_key"] and not config["uses_workload_identity"]:
                    issues.append("Uses SA key JSON instead of Workload Identity Federation (less secure)")
                if not config["gcp_secrets"] and config["service_accounts"]:
                    issues.append("Service account referenced but no GCP secrets found — may be hardcoded")
                if "GOOGLE_APPLICATION_CREDENTIALS" in content and "secrets." not in content:
                    issues.append("GOOGLE_APPLICATION_CREDENTIALS may be hardcoded instead of using GitHub secrets")

                config["issues"] = issues
                gcp_configs.append(config)

            except Exception as e:
                gcp_configs.append({"workflow": wf["name"], "error": str(e)})

        return {
            "repo": repo,
            "total_workflows": len(workflows.get("workflows", [])),
            "gcp_workflows": len([c for c in gcp_configs if c.get("gcp_project_ids") or c.get("service_accounts") or c.get("gcp_actions")]),
            "configs": gcp_configs,
        }
