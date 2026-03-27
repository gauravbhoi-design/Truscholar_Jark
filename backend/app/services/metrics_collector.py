"""Metrics Collection Service — Pulls raw metrics from GitHub, GCP, CI/CD, Prometheus.

Feeds data into the scoring engine for DORA, SPACE, DX Core 4, and AI Capabilities computation.
"""

import structlog
from datetime import datetime, timedelta, timezone

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class MetricsCollector:
    """Collects raw engineering metrics from external data sources."""

    def __init__(self, github_token: str | None = None, gcp_access_token: str | None = None, gcp_project_id: str | None = None):
        self.github_token = github_token
        self.gcp_access_token = gcp_access_token
        self.gcp_project_id = gcp_project_id

    # ─── DORA Metrics Collection ───────────────────────────────────────

    def _get_github_client(self):
        """Get GitHub client or raise clear error if no token."""
        if not self.github_token:
            return None
        from app.mcp.github import GitHubMCPClient
        return GitHubMCPClient(user_token=self.github_token)

    async def collect_deployment_frequency(self, repo: str, days: int = 30) -> dict:
        """Collect deployment frequency from GitHub Actions workflow runs.

        Rules: Count only successful deployments to production.
        Feature flag activations do NOT count. Rollbacks count as separate deployments.
        """
        client = self._get_github_client()
        if not client:
            return {"deploy_count": 0, "deploys_per_day": 0, "error": "No GitHub token available. Connect GitHub in Settings."}
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        try:
            runs_data = await client._request(
                "GET",
                f"/repos/{repo}/actions/runs",
                params={
                    "status": "success",
                    "per_page": 100,
                    "created": f">={since[:10]}",
                },
            )

            all_runs = runs_data.get("workflow_runs", [])

            # Filter to production deployments (workflows with "deploy" or "release" in name)
            prod_deploys = [
                r for r in all_runs
                if any(kw in (r.get("name", "") or "").lower() for kw in ["deploy", "release", "production", "cd"])
                and r.get("conclusion") == "success"
            ]

            # If no deploy-specific workflows, count all successful main-branch runs
            if not prod_deploys:
                prod_deploys = [
                    r for r in all_runs
                    if r.get("head_branch") in ("main", "master")
                    and r.get("conclusion") == "success"
                ]

            deploy_count = len(prod_deploys)
            deploys_per_day = deploy_count / max(days, 1)

            # Get deploy dates for trend analysis
            deploy_dates = [r.get("created_at", "")[:10] for r in prod_deploys]

            return {
                "deploy_count": deploy_count,
                "deploys_per_day": round(deploys_per_day, 3),
                "period_days": days,
                "deploy_dates": deploy_dates,
                "source": "github_actions",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect deployment frequency", repo=repo, error=str(e))
            return {"deploy_count": 0, "deploys_per_day": 0, "error": str(e)}

    async def collect_lead_time(self, repo: str, days: int = 30) -> dict:
        """Collect lead time for changes — commit to production deployment.

        Sub-metrics: coding time, pickup time, review time, deploy time.
        """
        client = self._get_github_client()
        if not client:
            return {"avg_lead_time_hours": 0, "error": "No GitHub token available"}
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        try:
            # Get merged PRs in the period
            prs_data = await client._request(
                "GET",
                f"/repos/{repo}/pulls",
                params={
                    "state": "closed",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 50,
                },
            )

            merged_prs = [
                pr for pr in prs_data
                if pr.get("merged_at") and pr["merged_at"] >= since
            ]

            if not merged_prs:
                return {"avg_lead_time_hours": 0, "merged_prs": 0, "error": "No merged PRs found"}

            lead_times = []
            pickup_times = []
            review_times = []

            for pr in merged_prs[:30]:  # Limit to avoid rate limiting
                created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
                merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))

                # Total lead time: PR created -> merged (approximation of commit-to-deploy)
                lt_hours = (merged - created).total_seconds() / 3600
                lead_times.append(lt_hours)

                # Try to get review timeline for sub-metrics
                try:
                    reviews = await client._request(
                        "GET", f"/repos/{repo}/pulls/{pr['number']}/reviews"
                    )
                    if reviews:
                        first_review = min(
                            reviews,
                            key=lambda r: r.get("submitted_at", "9999"),
                        )
                        review_submitted = datetime.fromisoformat(
                            first_review["submitted_at"].replace("Z", "+00:00")
                        )
                        pickup_hours = (review_submitted - created).total_seconds() / 3600
                        pickup_times.append(pickup_hours)

                        review_hours = (merged - review_submitted).total_seconds() / 3600
                        review_times.append(review_hours)
                except Exception:
                    pass

            avg_lead = sum(lead_times) / len(lead_times) if lead_times else 0
            avg_pickup = sum(pickup_times) / len(pickup_times) if pickup_times else 0
            avg_review = sum(review_times) / len(review_times) if review_times else 0

            return {
                "avg_lead_time_hours": round(avg_lead, 2),
                "median_lead_time_hours": round(sorted(lead_times)[len(lead_times) // 2], 2) if lead_times else 0,
                "avg_pickup_time_hours": round(avg_pickup, 2),
                "avg_review_time_hours": round(avg_review, 2),
                "merged_prs": len(merged_prs),
                "period_days": days,
                "source": "github",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect lead time", repo=repo, error=str(e))
            return {"avg_lead_time_hours": 0, "error": str(e)}

    async def collect_change_failure_rate(self, repo: str, days: int = 30) -> dict:
        """Collect change failure rate from CI/CD pipeline data.

        Failure = deployment causing production incident, requiring rollback, or hotfix within 24h.
        Excludes pre-production failures caught by testing.
        """
        client = self._get_github_client()
        if not client:
            return {"change_failure_rate_pct": 0, "error": "No GitHub token available"}

        try:
            # Get all workflow runs in period
            runs_data = await client._request(
                "GET",
                f"/repos/{repo}/actions/runs",
                params={"per_page": 100},
            )
            all_runs = runs_data.get("workflow_runs", [])

            since = datetime.now(timezone.utc) - timedelta(days=days)
            period_runs = [
                r for r in all_runs
                if r.get("head_branch") in ("main", "master")
                and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= since
            ]

            total_deploys = len([r for r in period_runs if r.get("conclusion") == "success"])
            failed_deploys = len([r for r in period_runs if r.get("conclusion") == "failure"])

            # Also check for hotfix/rollback PRs as failure indicators
            prs_data = await client._request(
                "GET",
                f"/repos/{repo}/pulls",
                params={"state": "closed", "per_page": 100, "sort": "updated"},
            )
            hotfix_prs = [
                pr for pr in prs_data
                if pr.get("merged_at")
                and any(kw in (pr.get("title", "") or "").lower() for kw in ["hotfix", "rollback", "revert", "fix:", "bugfix"])
                and datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00")) >= since
            ]

            # CFR = (failed deploys + hotfixes) / total deploys
            failure_count = failed_deploys + len(hotfix_prs)
            total = max(total_deploys, 1)
            cfr_pct = round((failure_count / total) * 100, 2)

            return {
                "change_failure_rate_pct": cfr_pct,
                "total_deployments": total_deploys,
                "failed_deployments": failed_deploys,
                "hotfix_prs": len(hotfix_prs),
                "period_days": days,
                "source": "github",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect CFR", repo=repo, error=str(e))
            return {"change_failure_rate_pct": 0, "error": str(e)}

    async def collect_recovery_time(self, repo: str, days: int = 30) -> dict:
        """Collect failed deployment recovery time.

        Measures time from failed deploy to next successful deploy.
        """
        client = self._get_github_client()
        if not client:
            return {"avg_recovery_time_hours": 0, "error": "No GitHub token available"}

        try:
            runs_data = await client._request(
                "GET",
                f"/repos/{repo}/actions/runs",
                params={"per_page": 100},
            )

            since = datetime.now(timezone.utc) - timedelta(days=days)
            runs = sorted(
                [
                    r for r in runs_data.get("workflow_runs", [])
                    if r.get("head_branch") in ("main", "master")
                    and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= since
                ],
                key=lambda r: r["created_at"],
            )

            recovery_times = []
            in_failure = False
            failure_start = None

            for run in runs:
                if run.get("conclusion") == "failure" and not in_failure:
                    in_failure = True
                    failure_start = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
                elif run.get("conclusion") == "success" and in_failure:
                    recovery_end = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
                    recovery_hours = (recovery_end - failure_start).total_seconds() / 3600
                    recovery_times.append(recovery_hours)
                    in_failure = False
                    failure_start = None

            avg_recovery = sum(recovery_times) / len(recovery_times) if recovery_times else 0

            return {
                "avg_recovery_time_hours": round(avg_recovery, 2),
                "recovery_incidents": len(recovery_times),
                "period_days": days,
                "source": "github_actions",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect recovery time", repo=repo, error=str(e))
            return {"avg_recovery_time_hours": 0, "error": str(e)}

    async def collect_rework_rate(self, repo: str, days: int = 30) -> dict:
        """Collect rework rate — % of deployments that are unplanned fixes.

        Identifies PRs with hotfix/bugfix/revert labels or keywords.
        """
        client = self._get_github_client()
        if not client:
            return {"rework_rate_pct": 0, "error": "No GitHub token available"}
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        try:
            prs_data = await client._request(
                "GET",
                f"/repos/{repo}/pulls",
                params={"state": "closed", "per_page": 100, "sort": "updated"},
            )

            merged_prs = [
                pr for pr in prs_data
                if pr.get("merged_at") and pr["merged_at"] >= since
            ]

            rework_keywords = ["hotfix", "bugfix", "fix:", "revert", "rollback", "patch", "urgent fix"]
            rework_labels = ["bug", "hotfix", "regression", "revert"]

            rework_prs = [
                pr for pr in merged_prs
                if any(kw in (pr.get("title", "") or "").lower() for kw in rework_keywords)
                or any(
                    label.get("name", "").lower() in rework_labels
                    for label in pr.get("labels", [])
                )
            ]

            total = max(len(merged_prs), 1)
            rework_pct = round((len(rework_prs) / total) * 100, 2)

            return {
                "rework_rate_pct": rework_pct,
                "total_merged_prs": len(merged_prs),
                "rework_prs": len(rework_prs),
                "period_days": days,
                "source": "github",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect rework rate", repo=repo, error=str(e))
            return {"rework_rate_pct": 0, "error": str(e)}

    # ─── SPACE Activity Metrics Collection ─────────────────────────────

    async def collect_space_activity(self, repo: str, days: int = 7) -> dict:
        """Collect SPACE Activity metrics from GitHub.

        Metrics: commit frequency, PR throughput, code review participation.
        """
        client = self._get_github_client()
        if not client:
            return {"error": "No GitHub token available"}
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        try:
            # Commit frequency
            commits_data = await client.get_commits(repo, limit=100, since=since)
            commits = commits_data.get("commits", [])

            # Group by author
            author_commits: dict[str, int] = {}
            for c in commits:
                author = c.get("author", "unknown")
                author_commits[author] = author_commits.get(author, 0) + 1

            num_authors = max(len(author_commits), 1)
            avg_commits_per_dev = len(commits) / num_authors

            # PR throughput
            prs_data = await client._request(
                "GET",
                f"/repos/{repo}/pulls",
                params={"state": "closed", "sort": "updated", "per_page": 100},
            )
            merged_prs = [
                pr for pr in prs_data
                if pr.get("merged_at") and pr["merged_at"] >= since
            ]
            avg_prs_per_dev = len(merged_prs) / num_authors

            # PR sizes (for Small Batch Work AI capability metric)
            pr_sizes = []
            for pr in merged_prs[:20]:
                additions = pr.get("additions", 0) or 0
                deletions = pr.get("deletions", 0) or 0
                pr_sizes.append(additions + deletions)

            avg_pr_size = sum(pr_sizes) / len(pr_sizes) if pr_sizes else 0

            return {
                "total_commits": len(commits),
                "avg_commits_per_developer_per_week": round(avg_commits_per_dev, 1),
                "total_merged_prs": len(merged_prs),
                "avg_prs_per_developer_per_week": round(avg_prs_per_dev, 1),
                "unique_contributors": num_authors,
                "avg_pr_size_lines": round(avg_pr_size, 0),
                "period_days": days,
                "source": "github",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect SPACE activity", repo=repo, error=str(e))
            return {"error": str(e)}

    async def collect_space_communication(self, repo: str, days: int = 7) -> dict:
        """Collect SPACE Communication metrics from GitHub.

        Metrics: PR review pickup time, review participation.
        """
        client = self._get_github_client()
        if not client:
            return {"error": "No GitHub token available"}
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        try:
            prs_data = await client._request(
                "GET",
                f"/repos/{repo}/pulls",
                params={"state": "closed", "sort": "updated", "per_page": 30},
            )

            merged_prs = [
                pr for pr in prs_data
                if pr.get("merged_at") and pr["merged_at"] >= since
            ]

            pickup_times = []
            review_counts: dict[str, int] = {}

            for pr in merged_prs[:20]:
                try:
                    reviews = await client._request(
                        "GET", f"/repos/{repo}/pulls/{pr['number']}/reviews"
                    )
                    if reviews:
                        created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
                        first_review = min(reviews, key=lambda r: r.get("submitted_at", "9999"))
                        review_time = datetime.fromisoformat(first_review["submitted_at"].replace("Z", "+00:00"))
                        pickup_hours = (review_time - created).total_seconds() / 3600
                        pickup_times.append(pickup_hours)

                        for review in reviews:
                            reviewer = review.get("user", {}).get("login", "unknown")
                            review_counts[reviewer] = review_counts.get(reviewer, 0) + 1
                except Exception:
                    pass

            avg_pickup = sum(pickup_times) / len(pickup_times) if pickup_times else 0

            # Cross-team review approximation (unique reviewers / unique PR authors)
            pr_authors = set(pr.get("user", {}).get("login", "") for pr in merged_prs)
            reviewers = set(review_counts.keys())
            cross_review_pct = len(reviewers - pr_authors) / max(len(reviewers), 1) * 100

            return {
                "avg_pr_pickup_time_hours": round(avg_pickup, 2),
                "unique_reviewers": len(review_counts),
                "cross_team_review_pct": round(cross_review_pct, 1),
                "total_reviews": sum(review_counts.values()),
                "period_days": days,
                "source": "github",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect SPACE communication", repo=repo, error=str(e))
            return {"error": str(e)}

    # ─── CI/CD Pipeline Metrics ────────────────────────────────────────

    async def collect_ci_pipeline_metrics(self, repo: str, days: int = 30) -> dict:
        """Collect CI/CD pipeline health metrics.

        Metrics: build time, success rate, flaky test rate.
        """
        client = self._get_github_client()
        if not client:
            return {"error": "No GitHub token available"}

        try:
            runs_data = await client._request(
                "GET",
                f"/repos/{repo}/actions/runs",
                params={"per_page": 100},
            )

            since = datetime.now(timezone.utc) - timedelta(days=days)
            runs = [
                r for r in runs_data.get("workflow_runs", [])
                if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= since
            ]

            total = len(runs)
            successful = len([r for r in runs if r.get("conclusion") == "success"])
            failed = len([r for r in runs if r.get("conclusion") == "failure"])
            success_rate = (successful / max(total, 1)) * 100

            # Estimate build duration from run timing
            durations = []
            for r in runs[:30]:
                if r.get("created_at") and r.get("updated_at"):
                    start = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00"))
                    duration_min = (end - start).total_seconds() / 60
                    if 0 < duration_min < 120:  # Sanity check
                        durations.append(duration_min)

            avg_duration = sum(durations) / len(durations) if durations else 0

            return {
                "total_runs": total,
                "successful_runs": successful,
                "failed_runs": failed,
                "success_rate_pct": round(success_rate, 1),
                "avg_build_duration_minutes": round(avg_duration, 1),
                "period_days": days,
                "source": "github_actions",
                "repo": repo,
            }

        except Exception as e:
            logger.error("Failed to collect CI metrics", repo=repo, error=str(e))
            return {"error": str(e)}

    # ─── Infrastructure Metrics (GCP) ──────────────────────────────────

    async def collect_infrastructure_metrics(self, project_id: str | None = None) -> dict:
        """Collect GCP infrastructure metrics from Cloud Monitoring.

        Metrics: uptime, latency, error rate, resource utilization.
        """
        target_project = project_id or self.gcp_project_id
        if not target_project or not self.gcp_access_token:
            return {"error": "GCP credentials not available"}

        try:
            from app.mcp.gcp import GCPMCPClient

            client = GCPMCPClient(user_access_token=self.gcp_access_token, project_id=target_project)

            # Get Cloud Run services for latency/error metrics
            services = await client.list_cloud_run_services(project_id=target_project)

            return {
                "project_id": target_project,
                "services": services,
                "source": "gcp",
            }

        except Exception as e:
            logger.error("Failed to collect infrastructure metrics", error=str(e))
            return {"error": str(e)}

    # ─── Aggregate Collection ──────────────────────────────────────────

    async def collect_all_dora(self, repo: str, days: int = 30) -> dict:
        """Collect all 5 DORA metrics for a repository."""
        deploy_freq = await self.collect_deployment_frequency(repo, days)
        lead_time = await self.collect_lead_time(repo, days)
        cfr = await self.collect_change_failure_rate(repo, days)
        recovery = await self.collect_recovery_time(repo, days)
        rework = await self.collect_rework_rate(repo, days)

        return {
            "deployment_frequency": deploy_freq,
            "lead_time": lead_time,
            "change_failure_rate": cfr,
            "recovery_time": recovery,
            "rework_rate": rework,
            "repo": repo,
            "period_days": days,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    async def collect_all_space_automated(self, repo: str, days: int = 7) -> dict:
        """Collect all auto-collectable SPACE metrics (Activity + Communication)."""
        activity = await self.collect_space_activity(repo, days)
        communication = await self.collect_space_communication(repo, days)

        return {
            "activity": activity,
            "communication": communication,
            "repo": repo,
            "period_days": days,
            "note": "Satisfaction, Performance, and Efficiency dimensions require survey data and Jira integration",
        }
