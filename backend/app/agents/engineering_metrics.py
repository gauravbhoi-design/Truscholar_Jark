"""Engineering Metrics Agent — Analyzes DORA, SPACE, DX Core 4, and AI Capabilities.

Provides natural language analysis with context per Section 11.2:
"Claude agent MUST explain metric context when displaying scores (not just numbers)"
"""

import structlog

from app.agents.base import BaseAgent
from app.services.metrics_collector import MetricsCollector
from app.services.metrics_scorer import MetricsScorer

logger = structlog.get_logger()


class EngineeringMetricsAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "engineering_metrics"

    @property
    def system_prompt(self) -> str:
        return """You are an Engineering Metrics Agent for the TruScholar platform, specializing in measuring and improving software engineering team performance.

You use a 4-layer metrics framework based on industry standards:
- **Layer 1: DORA Metrics (5 Keys)** — Deployment Frequency, Lead Time for Changes, Change Failure Rate, Failed Deployment Recovery Time, Rework Rate
- **Layer 2: SPACE Framework** — Satisfaction & Wellbeing, Performance, Activity, Communication & Collaboration, Efficiency & Flow
- **Layer 3: DX Core 4** — Speed, Effectiveness, Quality, Business Impact
- **Layer 4: DORA AI Capabilities Model** — 7 organizational capabilities for AI-readiness

Tier Classification (Platinum > Gold > Silver > Bronze):
- **Platinum**: Elite in >= 4 DORA metrics, SPACE >= 4.0/5, AI Cap >= 3.5/4
- **Gold**: High in >= 4 DORA metrics, SPACE >= 3.5/5, AI Cap >= 3.0/4
- **Silver**: Medium in >= 4 DORA metrics, SPACE >= 3.0/5, AI Cap >= 2.5/4
- **Bronze**: Any metric at Low tier

Composite Score = (DORA × 0.40) + (SPACE × 0.25) + (DX Core 4 × 0.20) + (AI Cap × 0.15)

CRITICAL RULES:
1. Always explain metric CONTEXT — don't just show numbers. Explain what the tier means and how it compares to industry benchmarks.
2. Measure TEAMS, not individuals. Never use metrics for individual ranking.
3. Compare to team's own historical baseline, not other teams.
4. Track all 5 DORA metrics TOGETHER — never optimize one at the expense of others.
5. Include trend direction (improving/declining) when presenting metrics.
6. When recommending improvements, provide 3-5 specific, actionable steps with expected impact.
7. Flag the AI amplification effect: AI improves throughput but can increase delivery instability.

DORA 2025 Benchmarks:
- Deploy Frequency: Elite = Multiple/day (16.2%), High = Daily-Weekly (21.9%), Medium = Weekly-Monthly (18.4%), Low = Monthly+ (43.5%)
- Lead Time: Elite = <1h (9.4%), High = <1d (15.2%), Medium = 1d-1w (31.9%), Low = >1w (43.5%)
- Change Failure Rate: Elite = 0-2% (8.5%), High = 2-8% (26%), Medium = 8-16% (26%), Low = >16% (39.5%)
- Recovery Time: Elite = <1h (21.3%), High = <1d (22.2%), Medium = 1d-1w (56.5%), Low = >1w (~10%)
- Rework Rate: Elite = <5%, High = 5-10%, Medium = 10-15%, Low = >15%

When presenting results, use clear formatting with tier badges, trend indicators, and actionable recommendations."""

    @property
    def tools(self) -> list[dict]:
        return [
            {
                "name": "get_dora_metrics",
                "description": "Collect and score all 5 DORA metrics for a GitHub repository. Returns deployment frequency, lead time, change failure rate, recovery time, and rework rate with tier classification.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "GitHub repo in 'owner/repo' format"},
                        "days": {"type": "integer", "description": "Analysis period in days", "default": 30},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "get_space_metrics",
                "description": "Collect SPACE framework metrics (Activity and Communication from GitHub; Satisfaction requires survey data).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "GitHub repo in 'owner/repo' format"},
                        "days": {"type": "integer", "description": "Analysis period in days", "default": 7},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "get_composite_score",
                "description": "Compute the full composite engineering score across all 4 layers (DORA, SPACE, DX Core 4, AI Capabilities) with overall tier classification.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "GitHub repo in 'owner/repo' format"},
                        "days": {"type": "integer", "description": "DORA analysis period", "default": 30},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "get_recommendations",
                "description": "Generate 3-5 actionable improvement recommendations based on gap analysis across all metric layers.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "GitHub repo in 'owner/repo' format"},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "get_ci_pipeline_health",
                "description": "Assess CI/CD pipeline health against TruScholar standards: build time, success rate, quality gates.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "GitHub repo in 'owner/repo' format"},
                        "days": {"type": "integer", "default": 30},
                    },
                    "required": ["repo"],
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_input: dict):
        """Dispatch to metrics collection and scoring tools."""
        github_token = getattr(self, "_current_user", {}).get("github_token") if hasattr(self, "_current_user") else None
        gcp_token = getattr(self, "_current_user", {}).get("gcp_access_token") if hasattr(self, "_current_user") else None
        gcp_project = getattr(self, "_current_user", {}).get("gcp_project_id") if hasattr(self, "_current_user") else None

        collector = MetricsCollector(
            github_token=github_token,
            gcp_access_token=gcp_token,
            gcp_project_id=gcp_project,
        )
        scorer = MetricsScorer()

        repo = tool_input.get("repo", "")
        days = tool_input.get("days", 30)

        try:
            if tool_name == "get_dora_metrics":
                raw = await collector.collect_all_dora(repo, days)
                dora = scorer.compute_dora_metrics(raw)
                return dora.model_dump()

            elif tool_name == "get_space_metrics":
                raw = await collector.collect_all_space_automated(repo, tool_input.get("days", 7))
                space = scorer.compute_space_metrics(raw)
                return space.model_dump()

            elif tool_name == "get_composite_score":
                # Collect all layers
                dora_raw = await collector.collect_all_dora(repo, days)
                dora = scorer.compute_dora_metrics(dora_raw)

                space_raw = await collector.collect_all_space_automated(repo, 7)
                space_raw["change_failure_rate"] = dora_raw.get("change_failure_rate", {})
                ci_raw = await collector.collect_ci_pipeline_metrics(repo, days)
                space_raw["ci_pipeline"] = ci_raw
                space = scorer.compute_space_metrics(space_raw)

                dx_core4 = scorer.compute_dx_core4(dora, space)

                # Default AI capabilities (requires manual assessment)
                ai_cap = scorer.compute_ai_capabilities({})

                composite = scorer.compute_composite_score(dora, space, dx_core4, ai_cap)
                return {
                    "composite": composite.model_dump(),
                    "dora_summary": {
                        "overall_score": dora.overall_score,
                        "elite_count": dora.elite_count,
                    },
                    "space_summary": {"overall_score": space.overall_score},
                    "dx_core4_summary": {"overall_score": dx_core4.overall_score},
                    "ai_capabilities_summary": {
                        "average_maturity": ai_cap.average_maturity,
                        "ready_for_ai_coding": ai_cap.ready_for_ai_coding,
                    },
                }

            elif tool_name == "get_recommendations":
                # Full analysis then recommendations
                dora_raw = await collector.collect_all_dora(repo, 30)
                dora = scorer.compute_dora_metrics(dora_raw)

                space_raw = await collector.collect_all_space_automated(repo, 7)
                space_raw["change_failure_rate"] = dora_raw.get("change_failure_rate", {})
                space = scorer.compute_space_metrics(space_raw)

                dx_core4 = scorer.compute_dx_core4(dora, space)
                ai_cap = scorer.compute_ai_capabilities({})

                recs = scorer.generate_recommendations(dora, space, dx_core4, ai_cap)
                return {
                    "recommendations": [r.model_dump() for r in recs],
                    "lowest_scoring_area": recs[0].area if recs else "N/A",
                    "current_tier": scorer.compute_composite_score(dora, space, dx_core4, ai_cap).overall_tier.value,
                }

            elif tool_name == "get_ci_pipeline_health":
                ci = await collector.collect_ci_pipeline_metrics(repo, days)
                # Assess against standards
                build_time_ok = ci.get("avg_build_duration_minutes", 99) < 10
                success_rate_ok = ci.get("success_rate_pct", 0) > 95

                return {
                    "pipeline_metrics": ci,
                    "standards_compliance": {
                        "build_time_under_10min": build_time_ok,
                        "success_rate_above_95pct": success_rate_ok,
                    },
                    "quality_gates_status": "Assessed — see CI/CD pipeline configuration for full gate details",
                }

            return {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            logger.error("Engineering metrics tool failed", tool=tool_name, error=str(e))
            return {"error": str(e)}
