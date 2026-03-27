"""TruScholar Engineering Metrics & Performance Standards — Constants & Benchmarks.

Based on: DORA 2025, SPACE Framework, DX Core 4, DORA AI Capabilities Model.
Document Version 1.0 | March 2026
"""

from enum import Enum


# ─── Tier Definitions ──────────────────────────────────────────────────────


class Tier(str, Enum):
    ELITE = "elite"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OverallTier(str, Enum):
    PLATINUM = "platinum"
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"


TIER_COLORS = {
    OverallTier.PLATINUM: "#7C3AED",  # purple
    OverallTier.GOLD: "#F59E0B",      # amber
    OverallTier.SILVER: "#3B82F6",    # blue
    OverallTier.BRONZE: "#6B7280",    # gray
}


# ─── Layer 1: DORA Metrics (5 Keys) ───────────────────────────────────────
# Each metric maps tier -> (threshold, comparison_operator)
# "lt" = value must be less than threshold, "gt" = greater than, "lte"/"gte"

DORA_DEPLOYMENT_FREQUENCY = {
    # Measured in deploys per day (averaged over period)
    Tier.ELITE: {"min": 1.0, "label": "Multiple deploys/day", "industry_pct": 16.2},
    Tier.HIGH: {"min": 0.14, "label": "Once/day to once/week", "industry_pct": 21.9},  # ~1/week
    Tier.MEDIUM: {"min": 0.033, "label": "Once/week to once/month", "industry_pct": 18.4},  # ~1/month
    Tier.LOW: {"min": 0, "label": "Once/month to once/6 months", "industry_pct": 43.5},
}

DORA_LEAD_TIME = {
    # Measured in hours (commit to production)
    Tier.ELITE: {"max_hours": 1, "label": "< 1 hour", "industry_pct": 9.4},
    Tier.HIGH: {"max_hours": 24, "label": "< 1 day", "industry_pct": 15.2},
    Tier.MEDIUM: {"max_hours": 168, "label": "1 day to 1 week", "industry_pct": 31.9},
    Tier.LOW: {"max_hours": float("inf"), "label": "> 1 week", "industry_pct": 43.5},
}

# Lead time sub-metrics (elite targets)
LEAD_TIME_SUB_METRICS = {
    "coding_time": {"definition": "First commit to PR opened", "elite_target_hours": 2, "source": "GitHub"},
    "pickup_time": {"definition": "PR created to first review started", "elite_target_minutes": 30, "source": "GitHub"},
    "review_time": {"definition": "First review to PR merged", "elite_target_hours": 2, "source": "GitHub"},
    "deploy_time": {"definition": "PR merged to production deploy", "elite_target_minutes": 15, "source": "CI/CD"},
}

DORA_CHANGE_FAILURE_RATE = {
    # Measured as percentage (0-100)
    Tier.ELITE: {"max_pct": 2, "label": "0-2%", "industry_pct": 8.5},
    Tier.HIGH: {"max_pct": 8, "label": "2-8%", "industry_pct": 26.0},
    Tier.MEDIUM: {"max_pct": 16, "label": "8-16%", "industry_pct": 26.0},
    Tier.LOW: {"max_pct": 100, "label": "> 16%", "industry_pct": 39.5},
}

DORA_RECOVERY_TIME = {
    # Measured in hours
    Tier.ELITE: {"max_hours": 1, "label": "< 1 hour", "industry_pct": 21.3},
    Tier.HIGH: {"max_hours": 24, "label": "< 1 day", "industry_pct": 22.2},
    Tier.MEDIUM: {"max_hours": 168, "label": "1 day to 1 week", "industry_pct": 56.5},
    Tier.LOW: {"max_hours": float("inf"), "label": "> 1 week", "industry_pct": 10.0},
}

DORA_REWORK_RATE = {
    # Measured as percentage of deployments that are unplanned fixes
    Tier.ELITE: {"max_pct": 5, "label": "< 5%", "interpretation": "Minimal unplanned rework"},
    Tier.HIGH: {"max_pct": 10, "label": "5-10%", "interpretation": "Manageable technical debt"},
    Tier.MEDIUM: {"max_pct": 15, "label": "10-15%", "interpretation": "Significant friction"},
    Tier.LOW: {"max_pct": 100, "label": "> 15%", "interpretation": "High debt, eroding velocity"},
}

# What counts as a "failure" for Change Failure Rate
CFR_FAILURE_CRITERIA = [
    "Any deployment that causes a production incident",
    "Any deployment requiring an immediate rollback",
    "Any deployment requiring a hotfix within 24 hours",
]
CFR_EXCLUSIONS = [
    "Pre-production failures caught by testing",
    "Planned maintenance deployments",
]

# Measurement rules for Deployment Frequency
DEPLOY_FREQ_RULES = [
    "Count only successful deployments to production (not staging/dev)",
    "Feature flag activations do NOT count as deployments",
    "Rollbacks count as separate deployments",
    "Measure per-team, per-application — not organization-wide averages",
    "Automated deployments via CI/CD are the primary data source",
]


# ─── Layer 2: SPACE Framework ─────────────────────────────────────────────

SPACE_SATISFACTION = {
    "developer_nps": {"target": 7.5, "scale": "1-10", "method": "Anonymous survey", "frequency": "Monthly"},
    "burnout_rate": {"target_max_pct": 10, "method": "Maslach Burnout Inventory", "frequency": "Quarterly"},
    "retention_rate": {"target_min_pct": 90, "method": "HR data — voluntary attrition", "frequency": "Quarterly"},
    "work_life_balance": {"target_min": 4, "scale": "1-5", "method": "Survey — hours + flexibility", "frequency": "Monthly"},
    "tool_satisfaction": {"target_min": 4, "scale": "1-5", "method": "Survey — dev tools effectiveness", "frequency": "Quarterly"},
}

SPACE_PERFORMANCE = {
    "code_quality_score": {"target": "A", "method": "SonarQube / CodeClimate", "frequency": "Per PR"},
    "bug_escape_rate": {"target_max_pct": 5, "method": "Bugs found in prod vs dev", "frequency": "Weekly"},
    "customer_satisfaction": {"target_min": 8, "scale": "1-10", "method": "NPS / CSAT from users", "frequency": "Monthly"},
    "feature_adoption_rate": {"target_min_pct": 30, "period": "30 days", "method": "% users using new features", "frequency": "Monthly"},
    "incident_severity_distribution": {"target_max_p1_pct": 5, "method": "P1/P2/P3 ratio", "frequency": "Monthly"},
}

SPACE_ACTIVITY = {
    "commit_frequency": {"target_min": 15, "target_max": 30, "unit": "commits/developer/week", "method": "GitHub", "frequency": "Weekly"},
    "pr_throughput": {"target_min": 3, "target_max": 5, "unit": "PRs merged/developer/week", "method": "GitHub", "frequency": "Weekly"},
    "code_review_participation": {"target_min": 5, "target_max": 10, "unit": "reviews/developer/week", "method": "GitHub", "frequency": "Weekly"},
    "documentation_contributions": {"target_min": 1, "unit": "per sprint", "method": "Docs updated or created", "frequency": "Per sprint"},
    "design_doc_ratio": {"target_min": 1, "unit": "per major feature", "method": "Design docs per feature", "frequency": "Per sprint"},
}

SPACE_COMMUNICATION = {
    "pr_review_pickup_time": {"target_max_hours": 2, "method": "Time from PR creation to first review", "frequency": "Per PR"},
    "knowledge_sharing_index": {"target_min_pct": 20, "method": "Cross-team PR reviews + pairing", "frequency": "Monthly"},
    "documentation_quality": {"target_min": 4, "scale": "1-5", "method": "Team survey on doc usefulness", "frequency": "Quarterly"},
    "meeting_load": {"target_max_hours": 8, "unit": "hours/week", "method": "Calendar analysis", "frequency": "Weekly"},
    "async_response_time": {"target_max_hours": 4, "method": "Slack/email response on work items", "frequency": "Weekly"},
}

SPACE_EFFICIENCY = {
    "cycle_time": {"target_max_days": 5, "method": "Issue created to deployed", "frequency": "Per sprint"},
    "flow_efficiency": {"target_min_pct": 40, "method": "Value-add time / total time", "frequency": "Per sprint"},
    "context_switching": {"target_max": 5, "unit": "task switches/day", "method": "Calendar + tool tracking", "frequency": "Weekly"},
    "onboarding_time": {"target_max_days": 14, "method": "Days to first meaningful PR", "frequency": "Per new hire"},
    "build_wait_time": {"target_max_minutes": 10, "method": "Time waiting for CI pipeline", "frequency": "Per build"},
}


# ─── Layer 3: DX Core 4 ──────────────────────────────────────────────────

DX_CORE4_PILLARS = {
    "speed": {
        "dora_metrics": ["deploy_frequency", "lead_time"],
        "devex_added": "Perceived productivity survey",
        "signal": "Are we shipping fast enough?",
    },
    "effectiveness": {
        "dora_metrics": [],
        "devex_added": "Developer Experience Index (DXI)",
        "signal": "Is the dev environment enabling or blocking?",
    },
    "quality": {
        "dora_metrics": ["change_fail_rate", "rework_rate"],
        "devex_added": "Code quality perceptions survey",
        "signal": "Is what we ship reliable?",
    },
    "business_impact": {
        "dora_metrics": [],
        "devex_added": "ROI measurement + value creation",
        "signal": "Does engineering output drive revenue?",
    },
}

# DX Core 4 scoring weights
DX_SPEED_WEIGHTS = {
    "deploy_frequency_tier": 0.40,
    "lead_time_tier": 0.40,
    "perceived_productivity_survey": 0.20,
}

DX_QUALITY_WEIGHTS = {
    "change_fail_rate_tier": 0.40,
    "rework_rate_tier": 0.30,
    "code_quality_survey": 0.30,
}

DX_BUSINESS_IMPACT_WEIGHTS = {
    "feature_adoption_rate": 0.50,
    "customer_satisfaction_delta": 0.50,
}


# ─── Layer 4: DORA AI Capabilities Model ─────────────────────────────────

AI_CAPABILITIES = {
    1: {
        "name": "AI Policy & Guidelines",
        "what_to_measure": "Documented AI usage policies, governance, review requirements",
        "maturity_levels": {
            1: "None/Informal",
            2: "Documented",
            3: "Enforced",
            4: "Continuously improved",
        },
    },
    2: {
        "name": "Healthy Data Ecosystem",
        "what_to_measure": "Data quality, accessibility, structure for AI tools",
        "maturity_levels": {
            1: "Siloed",
            2: "Accessible",
            3: "Structured",
            4: "AI-optimized",
        },
    },
    3: {
        "name": "Internal Knowledge Access",
        "what_to_measure": "Documentation quality, searchability, currency",
        "maturity_levels": {
            1: "Sparse",
            2: "Exists",
            3: "Searchable",
            4: "AI-indexed",
        },
    },
    4: {
        "name": "Small Batch Work",
        "what_to_measure": "Average PR size, batch size, deployment granularity",
        "maturity_levels": {
            1: "> 500 LOC",
            2: "200-500 LOC",
            3: "100-200 LOC",
            4: "< 100 LOC",
        },
    },
    5: {
        "name": "Platform Engineering",
        "what_to_measure": "Internal dev platform maturity, self-service tooling",
        "maturity_levels": {
            1: "None",
            2: "Basic",
            3: "Mature",
            4: "Self-service",
        },
    },
    6: {
        "name": "Code Review Quality",
        "what_to_measure": "Review depth, time-to-feedback, knowledge transfer",
        "maturity_levels": {
            1: "Rubber stamp",
            2: "Checklist",
            3: "Substantive",
            4: "Mentoring",
        },
    },
    7: {
        "name": "Testing & Quality Automation",
        "what_to_measure": "Test coverage, automated gate coverage",
        "maturity_levels": {
            1: "< 30%",
            2: "30-60%",
            3: "60-80%",
            4: "> 80% automated",
        },
    },
}

AI_CAPABILITY_ASSESSMENT_RULES = [
    "Each capability is scored on a 4-level maturity scale (1-4)",
    "Assessment is done quarterly via structured team survey + tool audit",
    "Minimum score of 2 on ALL capabilities before adopting AI coding assistants org-wide",
    "Score of 3+ on capabilities 1-3 before using AI for production code generation",
    "Dashboard displays a heatmap of all 7 capabilities per team",
]


# ─── Section 7: Code Quality Standards ────────────────────────────────────

STATIC_ANALYSIS_RULES = {
    "code_complexity": {"standard": "Cyclomatic complexity < 15 per function", "tool": "SonarQube / ESLint", "enforcement": "PR gate (block merge)"},
    "code_duplication": {"standard": "< 3% duplicated blocks", "tool": "SonarQube / jscpd", "enforcement": "PR gate (warning)"},
    "security_vulnerabilities": {"standard": "Zero critical/high SAST findings", "tool": "Snyk / Bandit / Semgrep", "enforcement": "PR gate (block merge)"},
    "dependency_vulnerabilities": {"standard": "Zero critical CVEs in deps", "tool": "Snyk / Dependabot", "enforcement": "PR gate (block merge)"},
    "code_smells": {"standard": "< 5 code smells per 1000 LOC", "tool": "SonarQube", "enforcement": "PR gate (warning)"},
    "type_safety": {"standard": "Strict mode enabled (TS/Python typing)", "tool": "mypy / tsc --strict", "enforcement": "PR gate (block merge)"},
}

TESTING_STANDARDS = {
    "unit_tests": {"coverage_target": 80, "when": "Every commit (CI)", "failure_action": "Block merge"},
    "integration_tests": {"coverage_target": 60, "unit": "API endpoint coverage %", "when": "Every PR (CI)", "failure_action": "Block merge"},
    "e2e_tests": {"coverage_target": "Critical user flows (top 10)", "when": "Pre-deploy (CD)", "failure_action": "Block deploy"},
    "performance_tests": {"target": "P95 latency < 500ms", "when": "Weekly + pre-release", "failure_action": "Alert + review"},
    "security_tests_dast": {"target": "Zero critical findings", "when": "Weekly", "failure_action": "Alert + ticket"},
    "mutation_testing": {"target": ">= 60% mutation score", "when": "Weekly (optional)", "failure_action": "Advisory"},
}

CODE_REVIEW_STANDARDS = {
    "minimum_reviewers": {"standard": 2, "rationale": "Reduces single-point-of-failure risk"},
    "review_turnaround": {"standard_hours": 2, "rationale": "Prevents lead time bloat"},
    "pr_size_limit": {"ideal_lines": 200, "max_lines": 400, "rationale": "Smaller PRs = better reviews = fewer bugs"},
    "self_merge_prohibition": {"standard": True, "rationale": "Enforces independent verification"},
    "review_checklist": {"items": ["Security", "Performance", "Edge cases", "Tests"], "rationale": "Consistent review quality"},
    "ai_generated_code_flag": {"threshold_pct": 50, "rationale": "Ensures human oversight of AI output"},
}


# ─── Section 8: CI/CD Pipeline Standards ──────────────────────────────────

BUILD_PIPELINE_RULES = {
    "build_time": {"target_minutes": 10, "measurement": "CI system metrics"},
    "build_success_rate": {"target_pct": 95, "measurement": "CI system metrics"},
    "flaky_test_rate": {"target_max_pct": 2, "measurement": "Test result tracking"},
    "artifact_versioning": {"standard": "Semantic versioning (semver) enforced"},
    "build_reproducibility": {"standard": "Same commit = identical artifact"},
    "parallel_execution": {"standard": "Tests run in parallel when possible"},
}

DEPLOYMENT_PIPELINE_RULES = {
    "zero_downtime_deploys": {"requirement": "Rolling updates or blue-green required"},
    "automated_rollback": {"requirement": "Auto-rollback on health check failure"},
    "canary_deployments": {"requirement": "Required for user-facing services"},
    "deploy_approval": {"requirement": "Auto for staging, manual gate for prod (optional)"},
    "environment_parity": {"requirement": "Staging must mirror prod config"},
    "deploy_audit_trail": {"requirement": "Every deploy logged with who, what, when"},
}

PIPELINE_QUALITY_GATES = [
    {"gate": 1, "name": "Lint", "checks": "Code formatting + linting", "pass_criteria": "Zero errors", "stage": "Pre-commit"},
    {"gate": 2, "name": "Build", "checks": "Compilation + dependency resolution", "pass_criteria": "Success", "stage": "CI"},
    {"gate": 3, "name": "Unit Test", "checks": "Unit test suite", "pass_criteria": ">= 80% coverage, all pass", "stage": "CI"},
    {"gate": 4, "name": "Integration", "checks": "API + integration tests", "pass_criteria": "All critical paths pass", "stage": "CI"},
    {"gate": 5, "name": "Security", "checks": "SAST + dependency scan", "pass_criteria": "Zero critical/high", "stage": "CI"},
    {"gate": 6, "name": "Performance", "checks": "Load test benchmarks", "pass_criteria": "P95 < threshold", "stage": "Pre-deploy"},
    {"gate": 7, "name": "Canary", "checks": "Health checks on canary instances", "pass_criteria": "Error rate < 1%", "stage": "Deploy"},
]


# ─── Section 9: GCP Infrastructure Standards ─────────────────────────────

INFRASTRUCTURE_STANDARDS = {
    "uptime_sla": {"target": "99.9%", "measurement": "Cloud Monitoring"},
    "error_budget_minutes": {"target_max": 43.8, "unit": "minutes/month", "measurement": "SLO dashboard"},
    "p95_latency_ms": {"target_max": 500, "measurement": "Cloud Trace"},
    "p99_latency_ms": {"target_max": 2000, "measurement": "Cloud Trace"},
    "error_rate": {"target_max_pct": 0.1, "measurement": "Cloud Monitoring"},
    "resource_utilization": {"target_range": "40-70%", "measurement": "Cloud Monitoring"},
    "autoscaling_response_seconds": {"target_max": 60, "measurement": "Cloud Monitoring"},
    "backup_frequency": {"standard": "Every 6 hours + daily snapshots"},
    "rto_hours": {"target_max": 4, "label": "Recovery Time Objective"},
    "rpo_hours": {"target_max": 1, "label": "Recovery Point Objective"},
    "iac_coverage_pct": {"target": 100, "tool": "Terraform/Pulumi"},
    "secret_management": {"standard": "100% via Secret Manager, no secrets in code"},
}

MONITORING_ALERTING_RULES = [
    "Every production service MUST have: health check endpoint, uptime check, error rate alert, latency alert",
    "Alert response SLA: P1 (service down) < 15 min, P2 (degraded) < 1 hour, P3 (minor) < 4 hours",
    "Structured logging (JSON) with trace correlation required for all services",
    "Dashboards must show: request rate, error rate, latency (RED method) per service",
    "Monthly cost review: flag any service exceeding 120% of budgeted cost",
]


# ─── Section 10: Security & Compliance Standards ─────────────────────────

SECURITY_STANDARDS = {
    "sast_scanning": {"standard": "Zero critical/high vulnerabilities in code", "enforcement": "PR gate — block merge", "frequency": "Every PR"},
    "dependency_scanning": {"standard": "Zero critical CVEs in dependencies", "enforcement": "PR gate — block merge", "frequency": "Every PR"},
    "container_scanning": {"standard": "Zero critical CVEs in Docker images", "enforcement": "Build gate — block deploy", "frequency": "Every build"},
    "secret_detection": {"standard": "No secrets/keys committed to repos", "enforcement": "Pre-commit hook + CI scan", "frequency": "Every commit"},
    "dast_scanning": {"standard": "Zero critical findings on running services", "enforcement": "Alert + ticket", "frequency": "Weekly"},
    "access_control": {"standard": "Least-privilege IAM, no service account keys", "enforcement": "IAM audit", "frequency": "Monthly"},
    "data_encryption": {"standard": "At-rest (AES-256) + in-transit (TLS 1.3)", "enforcement": "Config audit", "frequency": "Monthly"},
    "audit_logging": {"standard": "All admin actions logged + retained 90 days", "enforcement": "Cloud Audit Logs", "frequency": "Continuous"},
    "incident_response": {"standard": "Documented IR plan, tested quarterly", "enforcement": "IR drill", "frequency": "Quarterly"},
    "compliance": {"standard": "SOC 2 Type II controls where applicable", "enforcement": "Annual audit", "frequency": "Annually"},
}


# ─── Section 11: Dashboard Implementation Rules ──────────────────────────

MCP_SERVER_METRIC_MAPPING = {
    "github": {
        "metrics": ["PR cycle time", "commit freq", "review time", "rework rate"],
        "dora_fed": ["lead_time", "rework_rate"],
        "space_dimensions": ["Activity", "Communication"],
    },
    "gcp": {
        "metrics": ["deploy count", "uptime", "error spikes", "rollbacks"],
        "dora_fed": ["deploy_frequency", "change_fail_rate", "recovery_time"],
        "space_dimensions": ["Performance"],
    },
    "ci_cd": {
        "metrics": ["build pass rate", "test coverage", "pipeline duration"],
        "dora_fed": ["change_fail_rate"],
        "space_dimensions": ["Efficiency"],
    },
    "incident_tracking": {
        "metrics": ["MTTR", "incident count", "severity distribution"],
        "dora_fed": ["recovery_time"],
        "space_dimensions": ["Performance"],
    },
    "project_management": {
        "metrics": ["cycle time", "sprint velocity", "WIP count"],
        "dora_fed": ["lead_time"],
        "space_dimensions": ["Efficiency", "Activity"],
    },
    "developer_surveys": {
        "metrics": ["NPS", "burnout", "satisfaction", "tool ratings"],
        "dora_fed": [],
        "space_dimensions": ["Satisfaction", "Communication"],
    },
}

DATA_COLLECTION_RULES = [
    "All automated metrics must be collected without requiring manual developer input",
    "Survey-based metrics must use validated instruments (eNPS, Maslach BI, etc.)",
    "Data retention: 24 months of historical metrics for trend analysis",
    "Data granularity: team-level aggregation by default, individual-level ONLY for activity metrics",
    "Never use individual-level metrics for performance reviews — team-level only",
    "Claude agent MUST explain metric context when displaying scores (not just numbers)",
    "All dashboards must show trend direction (improving/declining) with time-series charts",
]

DASHBOARD_DISPLAY_RULES = {
    "metric_card": "Every metric card must show: current value, target, tier badge, and 30-day trend",
    "dora_chart": "DORA metrics displayed as a 5-metric radar chart with industry benchmark overlay",
    "space_chart": "SPACE dimensions displayed as a 5-dimension radar chart",
    "dx_core4_chart": "DX Core 4 displayed as a 4-pillar bar chart with target line",
    "ai_capabilities_chart": "AI Capabilities Model displayed as a 7-capability heatmap (red/yellow/green)",
}


# ─── Section 12: Scoring & Comparison Model ──────────────────────────────

# Tier classification thresholds
TIER_CLASSIFICATION = {
    OverallTier.PLATINUM: {
        "dora": "Elite in >= 4 of 5 metrics",
        "space": ">= 4.0/5 in all dimensions",
        "ai_cap": ">= 3.5/4 average",
        "overall": "Top 10%",
    },
    OverallTier.GOLD: {
        "dora": "High in >= 4 of 5 metrics",
        "space": ">= 3.5/5 average",
        "ai_cap": ">= 3.0/4 average",
        "overall": "Top 25%",
    },
    OverallTier.SILVER: {
        "dora": "Medium in >= 4 of 5 metrics",
        "space": ">= 3.0/5 average",
        "ai_cap": ">= 2.5/4 average",
        "overall": "Top 50%",
    },
    OverallTier.BRONZE: {
        "dora": "Any metric at Low tier",
        "space": "< 3.0/5 average",
        "ai_cap": "< 2.5/4 average",
        "overall": "Bottom 50%",
    },
}

# Composite score weights
COMPOSITE_WEIGHTS = {
    "dora": 0.40,
    "space": 0.25,
    "dx_core4": 0.20,
    "ai_capabilities": 0.15,
}

# DORA tier to numeric score mapping (for normalization to 0-100)
TIER_SCORE_MAP = {
    Tier.ELITE: 100,
    Tier.HIGH: 75,
    Tier.MEDIUM: 50,
    Tier.LOW: 25,
}


# ─── Section 13: Anti-Patterns to Avoid ──────────────────────────────────

ANTI_PATTERNS = [
    {"pattern": "Using metrics for individual ranking", "harm": "Creates gaming, destroys collaboration", "alternative": "Measure teams, not individuals"},
    {"pattern": "Optimizing one metric at expense of others", "harm": "Speed without quality = more incidents", "alternative": "Track all 5 DORA metrics together"},
    {"pattern": "Setting metrics as hard targets", "harm": "Goodhart's Law — metric stops being useful", "alternative": "Use as improvement signals, not KPIs"},
    {"pattern": "Ignoring developer satisfaction", "harm": "Burnout reduces all other metrics over time", "alternative": "Include SPACE satisfaction in reviews"},
    {"pattern": "Comparing teams with different contexts", "harm": "Unequal teams have inherent constraints", "alternative": "Compare to own historical baseline"},
    {"pattern": "Gaming deploy frequency", "harm": "Empty deploys inflate numbers meaninglessly", "alternative": "Count meaningful changes only"},
]


# ─── Measurement Frequency ───────────────────────────────────────────────

MEASUREMENT_FREQUENCY = {
    "dora_delivery": {"collection": "Auto-collected from CI/CD + GitHub", "frequency": "Real-time / Daily", "owner": "Platform Team"},
    "space_activity": {"collection": "Auto-collected from GitHub + Jira", "frequency": "Weekly", "owner": "Engineering Manager"},
    "space_satisfaction": {"collection": "Developer surveys", "frequency": "Monthly", "owner": "Engineering Manager"},
    "dx_core4_composite": {"collection": "Aggregated from Layer 1 + 2", "frequency": "Monthly", "owner": "VP Engineering"},
    "ai_capabilities": {"collection": "Structured team survey + audit", "frequency": "Quarterly", "owner": "CTO / VP Engineering"},
}
