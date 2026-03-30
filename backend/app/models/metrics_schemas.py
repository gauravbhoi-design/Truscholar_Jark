"""Pydantic schemas for Engineering Metrics & Performance Standards."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.metrics_constants import OverallTier, Tier

# ─── Enums ─────────────────────────────────────────────────────────────────


class MetricSource(str, Enum):
    GITHUB = "github"
    GCP = "gcp"
    CI_CD = "ci_cd"
    PROMETHEUS = "prometheus"
    SURVEY = "survey"
    MANUAL = "manual"
    JIRA = "jira"


class SPACEDimension(str, Enum):
    SATISFACTION = "satisfaction"
    PERFORMANCE = "performance"
    ACTIVITY = "activity"
    COMMUNICATION = "communication"
    EFFICIENCY = "efficiency"


class DXCore4Pillar(str, Enum):
    SPEED = "speed"
    EFFECTIVENESS = "effectiveness"
    QUALITY = "quality"
    BUSINESS_IMPACT = "business_impact"


class TrendDirection(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


# ─── Metric Card (Universal Display Unit) ──────────────────────────────────


class MetricCard(BaseModel):
    """Every metric card must show: current value, target, tier badge, and 30-day trend."""
    name: str
    current_value: float | str
    target: str
    tier: Tier
    trend: TrendDirection = TrendDirection.STABLE
    trend_delta: float | None = None  # % change over 30 days
    unit: str = ""
    source: MetricSource = MetricSource.GITHUB
    last_updated: datetime | None = None


# ─── Layer 1: DORA Metrics ─────────────────────────────────────────────────


class DORAMetricDetail(BaseModel):
    value: float
    tier: Tier
    label: str
    industry_percentile: float | None = None
    trend: TrendDirection = TrendDirection.STABLE


class LeadTimeBreakdown(BaseModel):
    coding_time_hours: float | None = None
    pickup_time_minutes: float | None = None
    review_time_hours: float | None = None
    deploy_time_minutes: float | None = None


class DORAMetrics(BaseModel):
    """All 5 DORA key metrics with tier classification."""
    deployment_frequency: DORAMetricDetail = Field(
        ..., description="Deploys per day (averaged)"
    )
    lead_time: DORAMetricDetail = Field(
        ..., description="Hours from commit to production"
    )
    change_failure_rate: DORAMetricDetail = Field(
        ..., description="% of deployments causing failures"
    )
    recovery_time: DORAMetricDetail = Field(
        ..., description="Hours to recover from failed deployment"
    )
    rework_rate: DORAMetricDetail = Field(
        ..., description="% of deployments that are unplanned fixes"
    )
    lead_time_breakdown: LeadTimeBreakdown | None = None
    overall_score: float = Field(0, description="Normalized 0-100 DORA score")
    elite_count: int = Field(0, description="Number of metrics at Elite tier")


class DORAMetricsResponse(BaseModel):
    metrics: DORAMetrics
    team_id: str | None = None
    period_days: int = 30
    collected_at: datetime | None = None
    radar_chart_data: list[dict] | None = None  # For 5-metric radar chart


# ─── Layer 2: SPACE Framework ──────────────────────────────────────────────


class SPACEDimensionScore(BaseModel):
    dimension: SPACEDimension
    score: float = Field(0, ge=0, le=5, description="Normalized 0-5 score")
    sub_metrics: list[MetricCard] = []
    data_completeness_pct: float = 0  # % of sub-metrics with actual data


class SPACEMetrics(BaseModel):
    satisfaction: SPACEDimensionScore
    performance: SPACEDimensionScore
    activity: SPACEDimensionScore
    communication: SPACEDimensionScore
    efficiency: SPACEDimensionScore
    overall_score: float = Field(0, description="Average across 5 dimensions, normalized 0-100")


class SPACEMetricsResponse(BaseModel):
    metrics: SPACEMetrics
    team_id: str | None = None
    period_days: int = 30
    collected_at: datetime | None = None
    radar_chart_data: list[dict] | None = None  # For 5-dimension radar chart


# ─── Layer 3: DX Core 4 ───────────────────────────────────────────────────


class DXCore4PillarScore(BaseModel):
    pillar: DXCore4Pillar
    score: float = Field(0, ge=0, le=100)
    components: dict = {}  # Breakdown of how score was computed
    signal: str = ""  # Question this pillar answers


class DXCore4Scores(BaseModel):
    speed: DXCore4PillarScore
    effectiveness: DXCore4PillarScore
    quality: DXCore4PillarScore
    business_impact: DXCore4PillarScore
    overall_score: float = Field(0, description="Average of all 4 pillars")


class DXCore4Response(BaseModel):
    scores: DXCore4Scores
    team_id: str | None = None
    period: str = "monthly"
    collected_at: datetime | None = None


# ─── Layer 4: AI Capabilities ─────────────────────────────────────────────


class AICapabilityScore(BaseModel):
    capability_id: int = Field(..., ge=1, le=7)
    name: str
    maturity_level: int = Field(1, ge=1, le=4)
    maturity_label: str = ""
    notes: str = ""


class AICapabilitiesAssessment(BaseModel):
    capabilities: list[AICapabilityScore] = []
    average_maturity: float = 0
    normalized_score: float = Field(0, description="average_maturity * 25, scaled 0-100")
    ready_for_ai_coding: bool = False  # True if all capabilities >= 2
    ready_for_ai_production: bool = False  # True if capabilities 1-3 >= 3


class AICapabilitiesResponse(BaseModel):
    assessment: AICapabilitiesAssessment
    team_id: str | None = None
    assessed_at: datetime | None = None
    heatmap_data: list[dict] | None = None  # For 7-capability heatmap


# ─── Composite Score & Tier ───────────────────────────────────────────────


class CompositeScore(BaseModel):
    """Final score = (DORA * 0.40) + (SPACE * 0.25) + (DX Core 4 * 0.20) + (AI Cap * 0.15)"""
    dora_score: float = Field(0, description="DORA component (0-100)")
    dora_weight: float = 0.40
    space_score: float = Field(0, description="SPACE component (0-100)")
    space_weight: float = 0.25
    dx_core4_score: float = Field(0, description="DX Core 4 component (0-100)")
    dx_core4_weight: float = 0.20
    ai_capabilities_score: float = Field(0, description="AI Cap component (0-100)")
    ai_capabilities_weight: float = 0.15
    final_score: float = Field(0, description="Weighted composite 0-100")
    overall_tier: OverallTier = OverallTier.BRONZE


class CompositeScoreResponse(BaseModel):
    score: CompositeScore
    team_id: str | None = None
    period: str = "monthly"
    computed_at: datetime | None = None
    tier_breakdown: dict = {}  # Per-layer tier details


# ─── Recommendations ─────────────────────────────────────────────────────


class Recommendation(BaseModel):
    priority: int = Field(..., ge=1)
    area: str  # e.g., "DORA - Lead Time", "SPACE - Communication"
    current_state: str
    target_state: str
    actions: list[str] = []
    expected_impact: str = ""
    related_capability: str | None = None  # Cross-reference to AI Capabilities


class RecommendationsResponse(BaseModel):
    recommendations: list[Recommendation] = []
    lowest_scoring_area: str = ""
    improvement_velocity: TrendDirection = TrendDirection.STABLE
    team_id: str | None = None
    generated_at: datetime | None = None


# ─── Trend Data ──────────────────────────────────────────────────────────


class MetricTrendPoint(BaseModel):
    date: datetime
    value: float
    tier: Tier | None = None


class MetricTrend(BaseModel):
    metric_name: str
    layer: str  # dora, space, dx_core4, ai_capabilities
    data_points: list[MetricTrendPoint] = []
    direction: TrendDirection = TrendDirection.STABLE
    delta_pct: float = 0  # % change over period


class TrendsResponse(BaseModel):
    trends: list[MetricTrend] = []
    period_days: int = 30
    team_id: str | None = None


# ─── Survey Submission ───────────────────────────────────────────────────


class SurveyQuestion(BaseModel):
    question_id: str
    question_text: str
    response_value: float  # Numeric response
    scale_min: float = 1
    scale_max: float = 10


class SurveySubmission(BaseModel):
    survey_type: str  # "developer_satisfaction", "burnout", "tool_satisfaction", "ai_capabilities"
    team_id: str | None = None
    responses: list[SurveyQuestion] = []
    submitted_at: datetime | None = None


class SurveySubmissionResponse(BaseModel):
    id: uuid.UUID
    status: str = "recorded"
    message: str = "Survey response saved successfully"


# ─── Metrics Dashboard Overview ──────────────────────────────────────────


class MetricsDashboardOverview(BaseModel):
    """Complete dashboard data for the metrics panel."""
    composite: CompositeScore
    dora: DORAMetrics
    space: SPACEMetrics
    dx_core4: DXCore4Scores
    ai_capabilities: AICapabilitiesAssessment
    top_recommendations: list[Recommendation] = []
    team_id: str | None = None
    last_updated: datetime | None = None
