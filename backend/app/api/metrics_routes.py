"""API routes for Engineering Metrics & Performance Standards dashboard."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_role
from app.models.database import CloudCredential, Team, get_db
from app.models.metrics_schemas import (
    AICapabilitiesResponse,
    CompositeScoreResponse,
    DORAMetricsResponse,
    DXCore4Response,
    MetricsDashboardOverview,
    RecommendationsResponse,
    SPACEMetricsResponse,
    SurveySubmission,
    SurveySubmissionResponse,
)
from app.models.schemas import UserRole
from app.services.metrics_collector import MetricsCollector
from app.services.metrics_scorer import MetricsScorer

logger = structlog.get_logger()
router = APIRouter(prefix="/metrics", tags=["Engineering Metrics"])


async def _enrich_user(user: dict, db: AsyncSession) -> dict:
    """Load GitHub/GCP tokens from DB if not in JWT (same pattern as orchestrator)."""
    enriched = dict(user)
    user_id = user.get("sub", user.get("login", ""))

    # Load GitHub token from DB if missing or empty
    if not enriched.get("github_token"):
        try:
            from app.utils.encryption import decrypt
            result = await db.execute(
                select(CloudCredential).where(
                    CloudCredential.user_id == user_id,
                    CloudCredential.provider == "github",
                    CloudCredential.is_active == True,
                )
            )
            cred = result.scalar_one_or_none()
            if cred:
                enriched["github_token"] = decrypt(cred.encrypted_refresh_token)
                enriched["login"] = cred.project_id
        except Exception as e:
            logger.debug("No GitHub credentials in DB", error=str(e))

    # Load GCP credentials
    if not enriched.get("gcp_access_token"):
        try:
            from app.api.gcp_oauth import get_user_gcp_access_token
            result = await get_user_gcp_access_token(user_id, db)
            if result:
                enriched["gcp_access_token"] = result[0]
                enriched["gcp_project_id"] = result[1]
        except Exception as e:
            logger.debug("No GCP credentials", error=str(e))

    return enriched


def _build_collector(user: dict) -> MetricsCollector:
    return MetricsCollector(
        github_token=user.get("github_token") or None,
        gcp_access_token=user.get("gcp_access_token") or None,
        gcp_project_id=user.get("gcp_project_id") or None,
    )


# ─── Layer 1: DORA Metrics ────────────────────────────────────────────────


@router.get("/dora", response_model=DORAMetricsResponse)
async def get_dora_metrics(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all 5 DORA metrics with tier classification and industry benchmarks."""
    user = await _enrich_user(user, db)
    collector = _build_collector(user)
    scorer = MetricsScorer()

    raw = await collector.collect_all_dora(repo, days)
    dora = scorer.compute_dora_metrics(raw)

    # Build radar chart data for frontend
    radar_data = [
        {"metric": "Deploy Frequency", "value": dora.deployment_frequency.value, "tier": dora.deployment_frequency.tier.value},
        {"metric": "Lead Time", "value": dora.lead_time.value, "tier": dora.lead_time.tier.value},
        {"metric": "Change Fail Rate", "value": dora.change_failure_rate.value, "tier": dora.change_failure_rate.tier.value},
        {"metric": "Recovery Time", "value": dora.recovery_time.value, "tier": dora.recovery_time.tier.value},
        {"metric": "Rework Rate", "value": dora.rework_rate.value, "tier": dora.rework_rate.tier.value},
    ]

    return DORAMetricsResponse(
        metrics=dora,
        period_days=days,
        collected_at=datetime.now(UTC),
        radar_chart_data=radar_data,
    )


# ─── Layer 2: SPACE Framework ─────────────────────────────────────────────


@router.get("/space", response_model=SPACEMetricsResponse)
async def get_space_metrics(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get SPACE framework metrics across all 5 dimensions."""
    user = await _enrich_user(user, db)
    collector = _build_collector(user)
    scorer = MetricsScorer()

    raw = await collector.collect_all_space_automated(repo, days)
    space = scorer.compute_space_metrics(raw)

    radar_data = [
        {"dimension": "Satisfaction", "score": space.satisfaction.score},
        {"dimension": "Performance", "score": space.performance.score},
        {"dimension": "Activity", "score": space.activity.score},
        {"dimension": "Communication", "score": space.communication.score},
        {"dimension": "Efficiency", "score": space.efficiency.score},
    ]

    return SPACEMetricsResponse(
        metrics=space,
        period_days=days,
        collected_at=datetime.now(UTC),
        radar_chart_data=radar_data,
    )


# ─── Layer 3: DX Core 4 ──────────────────────────────────────────────────


@router.get("/dx-core4", response_model=DXCore4Response)
async def get_dx_core4(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get DX Core 4 pillar scores (Speed, Effectiveness, Quality, Business Impact)."""
    user = await _enrich_user(user, db)
    collector = _build_collector(user)
    scorer = MetricsScorer()

    dora_raw = await collector.collect_all_dora(repo, days)
    dora = scorer.compute_dora_metrics(dora_raw)

    space_raw = await collector.collect_all_space_automated(repo, 7)
    space = scorer.compute_space_metrics(space_raw)

    dx_core4 = scorer.compute_dx_core4(dora, space)

    return DXCore4Response(
        scores=dx_core4,
        period="monthly",
        collected_at=datetime.now(UTC),
    )


# ─── Layer 4: AI Capabilities ─────────────────────────────────────────────


@router.get("/ai-capabilities", response_model=AICapabilitiesResponse)
async def get_ai_capabilities(
    team_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get DORA AI Capabilities Model assessment (7 capabilities heatmap)."""
    scorer = MetricsScorer()

    # Load latest assessment from DB if available
    assessment_data = {}
    if team_id and db:
        from sqlalchemy import select

        from app.models.database import SurveyResponse

        try:
            result = await db.execute(
                select(SurveyResponse)
                .where(
                    SurveyResponse.team_id == uuid.UUID(team_id),
                    SurveyResponse.survey_type == "ai_capabilities",
                )
                .order_by(SurveyResponse.submitted_at.desc())
                .limit(1)
            )
            survey = result.scalar_one_or_none()
            if survey:
                assessment_data = survey.responses
        except Exception as e:
            logger.debug("Failed to load AI capabilities assessment", error=str(e))

    ai_cap = scorer.compute_ai_capabilities(assessment_data)

    heatmap_data = [
        {
            "capability": c.name,
            "maturity": c.maturity_level,
            "label": c.maturity_label,
            "color": "green" if c.maturity_level >= 3 else ("yellow" if c.maturity_level == 2 else "red"),
        }
        for c in ai_cap.capabilities
    ]

    return AICapabilitiesResponse(
        assessment=ai_cap,
        team_id=team_id,
        assessed_at=datetime.now(UTC),
        heatmap_data=heatmap_data,
    )


# ─── Composite Score ──────────────────────────────────────────────────────


@router.get("/composite", response_model=CompositeScoreResponse)
async def get_composite_score(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get overall composite score with tier classification.

    Formula: (DORA × 0.40) + (SPACE × 0.25) + (DX Core 4 × 0.20) + (AI Cap × 0.15)
    """
    user = await _enrich_user(user, db)
    collector = _build_collector(user)
    scorer = MetricsScorer()

    dora_raw = await collector.collect_all_dora(repo, days)
    dora = scorer.compute_dora_metrics(dora_raw)

    space_raw = await collector.collect_all_space_automated(repo, 7)
    space_raw["change_failure_rate"] = dora_raw.get("change_failure_rate", {})
    ci_raw = await collector.collect_ci_pipeline_metrics(repo, days)
    space_raw["ci_pipeline"] = ci_raw
    space = scorer.compute_space_metrics(space_raw)

    dx_core4 = scorer.compute_dx_core4(dora, space)
    ai_cap = scorer.compute_ai_capabilities({})

    composite = scorer.compute_composite_score(dora, space, dx_core4, ai_cap)

    return CompositeScoreResponse(
        score=composite,
        period="monthly",
        computed_at=datetime.now(UTC),
        tier_breakdown={
            "dora": {"score": dora.overall_score, "elite_count": dora.elite_count},
            "space": {"score": space.overall_score},
            "dx_core4": {"score": dx_core4.overall_score},
            "ai_capabilities": {"score": ai_cap.normalized_score, "avg_maturity": ai_cap.average_maturity},
        },
    )


# ─── Recommendations ─────────────────────────────────────────────────────


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get AI-generated improvement recommendations based on gap analysis."""
    user = await _enrich_user(user, db)
    collector = _build_collector(user)
    scorer = MetricsScorer()

    dora_raw = await collector.collect_all_dora(repo, 30)
    dora = scorer.compute_dora_metrics(dora_raw)

    space_raw = await collector.collect_all_space_automated(repo, 7)
    space_raw["change_failure_rate"] = dora_raw.get("change_failure_rate", {})
    space = scorer.compute_space_metrics(space_raw)

    dx_core4 = scorer.compute_dx_core4(dora, space)
    ai_cap = scorer.compute_ai_capabilities({})

    recs = scorer.generate_recommendations(dora, space, dx_core4, ai_cap)

    return RecommendationsResponse(
        recommendations=recs,
        lowest_scoring_area=recs[0].area if recs else "N/A",
        generated_at=datetime.now(UTC),
    )


# ─── Survey Submission ───────────────────────────────────────────────────


@router.post("/survey", response_model=SurveySubmissionResponse)
async def submit_survey(
    submission: SurveySubmission,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a developer survey response (satisfaction, burnout, AI capabilities, etc.)."""
    from app.models.database import SurveyResponse

    team_id = submission.team_id
    if not team_id:
        raise HTTPException(status_code=400, detail="team_id is required")

    try:
        survey = SurveyResponse(
            team_id=uuid.UUID(team_id),
            survey_type=submission.survey_type,
            respondent_id=user.get("sub", user.get("login", "anonymous")),
            responses={q.question_id: q.response_value for q in submission.responses},
        )
        db.add(survey)
        await db.commit()
        await db.refresh(survey)

        return SurveySubmissionResponse(id=survey.id)
    except Exception as e:
        logger.error("Failed to save survey", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save survey response")


# ─── CI/CD Pipeline Health ───────────────────────────────────────────────


@router.get("/ci-pipeline")
async def get_ci_pipeline_health(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get CI/CD pipeline health metrics against TruScholar standards."""
    user = await _enrich_user(user, db)
    collector = _build_collector(user)

    ci = await collector.collect_ci_pipeline_metrics(repo, days)

    build_time = ci.get("avg_build_duration_minutes", 99)
    success_rate = ci.get("success_rate_pct", 0)

    return {
        "metrics": ci,
        "standards_compliance": {
            "build_time": {
                "value": build_time,
                "target": "< 10 minutes",
                "compliant": build_time < 10,
            },
            "success_rate": {
                "value": success_rate,
                "target": "> 95%",
                "compliant": success_rate > 95,
            },
        },
        "quality_gates": [
            {"gate": "Lint", "stage": "Pre-commit", "status": "configured" if success_rate > 0 else "unknown"},
            {"gate": "Build", "stage": "CI", "status": "configured"},
            {"gate": "Unit Test", "stage": "CI", "target": ">= 80% coverage"},
            {"gate": "Integration", "stage": "CI", "target": "All critical paths pass"},
            {"gate": "Security", "stage": "CI", "target": "Zero critical/high"},
            {"gate": "Performance", "stage": "Pre-deploy", "target": "P95 < threshold"},
            {"gate": "Canary", "stage": "Deploy", "target": "Error rate < 1%"},
        ],
    }


# ─── Dashboard Overview ──────────────────────────────────────────────────


@router.get("/dashboard")
async def get_metrics_dashboard(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get complete metrics dashboard data — all 4 layers + composite score + recommendations.

    Automatically persists results to PostgreSQL + Qdrant vector DB so data is never lost.
    """
    from app.services.metrics_store import MetricsStore

    user = await _enrich_user(user, db)
    collector = _build_collector(user)
    scorer = MetricsScorer()
    store = MetricsStore(db)

    # Collect all data
    dora_raw = await collector.collect_all_dora(repo, days)
    dora = scorer.compute_dora_metrics(dora_raw)

    space_raw = await collector.collect_all_space_automated(repo, 7)
    space_raw["change_failure_rate"] = dora_raw.get("change_failure_rate", {})
    ci_raw = await collector.collect_ci_pipeline_metrics(repo, days)
    space_raw["ci_pipeline"] = ci_raw
    space = scorer.compute_space_metrics(space_raw)

    dx_core4 = scorer.compute_dx_core4(dora, space)
    ai_cap = scorer.compute_ai_capabilities({})
    composite = scorer.compute_composite_score(dora, space, dx_core4, ai_cap)
    recs = scorer.generate_recommendations(dora, space, dx_core4, ai_cap)

    # Persist to PostgreSQL + Qdrant (auto-creates team if needed)
    try:
        team_id = await _get_or_create_team_for_repo(repo, db)
        await store.save_full_dashboard(
            team_id=team_id,
            dora_data=dora.model_dump(),
            space_data=space.model_dump(),
            dx_core4_data=dx_core4.model_dump(),
            ai_cap_data=ai_cap.model_dump(),
            composite_data=composite.model_dump(),
        )
        logger.info("Metrics persisted", repo=repo, tier=composite.overall_tier)
    except Exception as e:
        logger.warning("Failed to persist metrics (non-blocking)", error=str(e))

    return MetricsDashboardOverview(
        composite=composite,
        dora=dora,
        space=space,
        dx_core4=dx_core4,
        ai_capabilities=ai_cap,
        top_recommendations=recs[:3],
        last_updated=datetime.now(UTC),
    )


async def _get_or_create_team_for_repo(repo: str, db: AsyncSession) -> uuid.UUID:
    """Get or create a team entry for a GitHub repo."""
    from app.models.database import Team

    slug = repo.replace("/", "-").lower()
    result = await db.execute(select(Team).where(Team.slug == slug))
    team = result.scalar_one_or_none()

    if not team:
        team = Team(
            name=repo,
            slug=slug,
            github_repos=[repo],
        )
        db.add(team)
        await db.flush()

    return team.id


# ─── Stored History & Search ─────────────────────────────────────────────


@router.get("/history")
async def get_metrics_history(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    layer: str = Query("composite", description="Metric layer: dora, space, dx_core4, ai_capabilities, composite"),
    limit: int = Query(30, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get stored metric snapshots history for trend analysis.

    Returns historical data from PostgreSQL — no GitHub API calls needed.
    """
    from app.services.metrics_store import MetricsStore

    slug = repo.replace("/", "-").lower()
    result = await db.execute(select(Team).where(Team.slug == slug))
    team = result.scalar_one_or_none()

    if not team:
        return {"snapshots": [], "message": "No stored metrics found. Visit the dashboard to collect initial data."}

    store = MetricsStore(db)
    snapshots = await store.get_snapshots_history(team.id, layer, limit)
    return {"team": repo, "layer": layer, "snapshots": snapshots}


@router.get("/stored")
async def get_stored_dashboard(
    repo: str = Query(..., description="GitHub repo in 'owner/repo' format"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest STORED metrics without making any external API calls.

    Returns cached data from PostgreSQL + Qdrant. Fast and free.
    Use /dashboard to fetch fresh data (which also auto-stores).
    """
    from app.models.database import Team
    from app.services.metrics_store import MetricsStore

    slug = repo.replace("/", "-").lower()
    result = await db.execute(select(Team).where(Team.slug == slug))
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(status_code=404, detail="No stored metrics for this repo. Use GET /metrics/dashboard first to collect data.")

    store = MetricsStore(db)
    layers = {}
    for layer in ["dora", "space", "dx_core4", "ai_capabilities", "composite"]:
        snapshot = await store.get_latest_snapshot(team.id, layer)
        if snapshot:
            layers[layer] = snapshot

    if not layers:
        raise HTTPException(status_code=404, detail="No stored snapshots. Use GET /metrics/dashboard first.")

    return {
        "team": repo,
        "layers": layers,
        "stored_at": layers.get("composite", {}).get("snapshot_date"),
    }


@router.get("/search")
async def search_metrics(
    query: str = Query(..., description="Search query (e.g., 'DORA lead time trend', 'deployment frequency')"),
    repo: str | None = Query(None),
    layer: str | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search across all stored metric snapshots via Qdrant vector DB.

    Used by the AI agent to find relevant historical metrics context.
    """
    from app.services.metrics_store import MetricsStore

    team_id = None
    if repo:
        from app.models.database import Team
        slug = repo.replace("/", "-").lower()
        result = await db.execute(select(Team).where(Team.slug == slug))
        team = result.scalar_one_or_none()
        if team:
            team_id = str(team.id)

    store = MetricsStore(db)
    results = await store.search_metrics(query, team_id=team_id, layer=layer, limit=limit)
    return {"query": query, "results": results}


# ─── Team Management ─────────────────────────────────────────────────────


@router.post("/teams")
async def create_team(
    data: dict,
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Create a new team for metrics tracking."""
    from app.models.database import Team

    team = Team(
        name=data["name"],
        slug=data.get("slug", data["name"].lower().replace(" ", "-")),
        description=data.get("description"),
        github_repos=data.get("github_repos", []),
        gcp_projects=data.get("gcp_projects", []),
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)

    return {
        "id": str(team.id),
        "name": team.name,
        "slug": team.slug,
        "github_repos": team.github_repos,
    }


@router.get("/teams")
async def list_teams(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all teams."""
    from sqlalchemy import select

    from app.models.database import Team

    result = await db.execute(select(Team).order_by(Team.name))
    teams = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "github_repos": t.github_repos,
            "gcp_projects": t.gcp_projects,
        }
        for t in teams
    ]
