"""Metrics Scoring Engine — Computes scores, tiers, and recommendations.

Implements the TruScholar Scoring & Comparison Model (Section 12).
"""


import structlog

from app.models.metrics_constants import (
    AI_CAPABILITIES,
    COMPOSITE_WEIGHTS,
    DORA_CHANGE_FAILURE_RATE,
    DORA_DEPLOYMENT_FREQUENCY,
    DORA_LEAD_TIME,
    DORA_RECOVERY_TIME,
    DORA_REWORK_RATE,
    DX_BUSINESS_IMPACT_WEIGHTS,
    DX_QUALITY_WEIGHTS,
    DX_SPEED_WEIGHTS,
    TIER_SCORE_MAP,
    OverallTier,
    Tier,
)
from app.models.metrics_schemas import (
    AICapabilitiesAssessment,
    AICapabilityScore,
    CompositeScore,
    DORAMetricDetail,
    DORAMetrics,
    DXCore4Pillar,
    DXCore4PillarScore,
    DXCore4Scores,
    LeadTimeBreakdown,
    MetricCard,
    Recommendation,
    SPACEDimension,
    SPACEDimensionScore,
    SPACEMetrics,
)

logger = structlog.get_logger()


class MetricsScorer:
    """Computes scores, tier classifications, and recommendations from raw metrics."""

    # ─── DORA Tier Classification ──────────────────────────────────────

    @staticmethod
    def _get_float(d: dict, key: str) -> float:
        """Safely extract a float from a constants dict."""
        return float(d[key])  # type: ignore[arg-type]

    @staticmethod
    def classify_deployment_frequency(deploys_per_day: float) -> Tier:
        _f = MetricsScorer._get_float
        if deploys_per_day >= _f(DORA_DEPLOYMENT_FREQUENCY[Tier.ELITE], "min"):
            return Tier.ELITE
        elif deploys_per_day >= _f(DORA_DEPLOYMENT_FREQUENCY[Tier.HIGH], "min"):
            return Tier.HIGH
        elif deploys_per_day >= _f(DORA_DEPLOYMENT_FREQUENCY[Tier.MEDIUM], "min"):
            return Tier.MEDIUM
        return Tier.LOW

    @staticmethod
    def classify_lead_time(hours: float) -> Tier:
        _f = MetricsScorer._get_float
        if hours <= _f(DORA_LEAD_TIME[Tier.ELITE], "max_hours"):
            return Tier.ELITE
        elif hours <= _f(DORA_LEAD_TIME[Tier.HIGH], "max_hours"):
            return Tier.HIGH
        elif hours <= _f(DORA_LEAD_TIME[Tier.MEDIUM], "max_hours"):
            return Tier.MEDIUM
        return Tier.LOW

    @staticmethod
    def classify_change_failure_rate(pct: float) -> Tier:
        _f = MetricsScorer._get_float
        if pct <= _f(DORA_CHANGE_FAILURE_RATE[Tier.ELITE], "max_pct"):
            return Tier.ELITE
        elif pct <= _f(DORA_CHANGE_FAILURE_RATE[Tier.HIGH], "max_pct"):
            return Tier.HIGH
        elif pct <= _f(DORA_CHANGE_FAILURE_RATE[Tier.MEDIUM], "max_pct"):
            return Tier.MEDIUM
        return Tier.LOW

    @staticmethod
    def classify_recovery_time(hours: float) -> Tier:
        _f = MetricsScorer._get_float
        if hours <= _f(DORA_RECOVERY_TIME[Tier.ELITE], "max_hours"):
            return Tier.ELITE
        elif hours <= _f(DORA_RECOVERY_TIME[Tier.HIGH], "max_hours"):
            return Tier.HIGH
        elif hours <= _f(DORA_RECOVERY_TIME[Tier.MEDIUM], "max_hours"):
            return Tier.MEDIUM
        return Tier.LOW

    @staticmethod
    def classify_rework_rate(pct: float) -> Tier:
        _f = MetricsScorer._get_float
        if pct <= _f(DORA_REWORK_RATE[Tier.ELITE], "max_pct"):
            return Tier.ELITE
        elif pct <= _f(DORA_REWORK_RATE[Tier.HIGH], "max_pct"):
            return Tier.HIGH
        elif pct <= _f(DORA_REWORK_RATE[Tier.MEDIUM], "max_pct"):
            return Tier.MEDIUM
        return Tier.LOW

    # ─── DORA Score Computation ────────────────────────────────────────

    def compute_dora_metrics(self, raw_data: dict) -> DORAMetrics:
        """Compute DORA metrics with tier classification from collected raw data."""
        # Deployment Frequency
        df_data = raw_data.get("deployment_frequency", {})
        df_value = df_data.get("deploys_per_day", 0)
        df_tier = self.classify_deployment_frequency(df_value)

        # Lead Time
        lt_data = raw_data.get("lead_time", {})
        lt_value = lt_data.get("avg_lead_time_hours", 0)
        lt_tier = self.classify_lead_time(lt_value)

        # Change Failure Rate
        cfr_data = raw_data.get("change_failure_rate", {})
        cfr_value = cfr_data.get("change_failure_rate_pct", 0)
        cfr_tier = self.classify_change_failure_rate(cfr_value)

        # Recovery Time
        rt_data = raw_data.get("recovery_time", {})
        rt_value = rt_data.get("avg_recovery_time_hours", 0)
        rt_tier = self.classify_recovery_time(rt_value)

        # Rework Rate
        rr_data = raw_data.get("rework_rate", {})
        rr_value = rr_data.get("rework_rate_pct", 0)
        rr_tier = self.classify_rework_rate(rr_value)

        tiers = [df_tier, lt_tier, cfr_tier, rt_tier, rr_tier]
        elite_count = sum(1 for t in tiers if t == Tier.ELITE)
        overall_score = sum(TIER_SCORE_MAP[t] for t in tiers) / len(tiers)

        lead_time_breakdown = LeadTimeBreakdown(
            coding_time_hours=None,  # Requires commit-to-PR analysis
            pickup_time_minutes=(lt_data.get("avg_pickup_time_hours", 0) * 60) or None,
            review_time_hours=lt_data.get("avg_review_time_hours") or None,
            deploy_time_minutes=None,  # Requires CI/CD timing data
        )

        return DORAMetrics(
            deployment_frequency=DORAMetricDetail(
                value=df_value,
                tier=df_tier,
                label=str(DORA_DEPLOYMENT_FREQUENCY[df_tier]["label"]),
                industry_percentile=MetricsScorer._get_float(DORA_DEPLOYMENT_FREQUENCY[df_tier], "industry_pct"),
            ),
            lead_time=DORAMetricDetail(
                value=lt_value,
                tier=lt_tier,
                label=str(DORA_LEAD_TIME[lt_tier]["label"]),
                industry_percentile=MetricsScorer._get_float(DORA_LEAD_TIME[lt_tier], "industry_pct"),
            ),
            change_failure_rate=DORAMetricDetail(
                value=cfr_value,
                tier=cfr_tier,
                label=str(DORA_CHANGE_FAILURE_RATE[cfr_tier]["label"]),
                industry_percentile=MetricsScorer._get_float(DORA_CHANGE_FAILURE_RATE[cfr_tier], "industry_pct"),
            ),
            recovery_time=DORAMetricDetail(
                value=rt_value,
                tier=rt_tier,
                label=str(DORA_RECOVERY_TIME[rt_tier]["label"]),
                industry_percentile=MetricsScorer._get_float(DORA_RECOVERY_TIME[rt_tier], "industry_pct"),
            ),
            rework_rate=DORAMetricDetail(
                value=rr_value,
                tier=rr_tier,
                label=str(DORA_REWORK_RATE[rr_tier]["label"]),
            ),
            lead_time_breakdown=lead_time_breakdown,
            overall_score=round(overall_score, 1),
            elite_count=elite_count,
        )

    # ─── SPACE Score Computation ───────────────────────────────────────

    def compute_space_metrics(self, raw_data: dict, survey_data: dict | None = None) -> SPACEMetrics:
        """Compute SPACE framework metrics from collected data."""
        activity_data = raw_data.get("activity", {})
        comm_data = raw_data.get("communication", {})

        # Activity dimension (auto-collected)
        activity_score = self._score_space_activity(activity_data)

        # Communication dimension (auto-collected)
        comm_score = self._score_space_communication(comm_data)

        # Satisfaction dimension (requires survey)
        satisfaction_score = self._score_space_satisfaction(survey_data or {})

        # Performance dimension (partial auto)
        performance_score = self._score_space_performance(raw_data)

        # Efficiency dimension (partial auto)
        efficiency_score = self._score_space_efficiency(raw_data)

        dimensions = [
            satisfaction_score, performance_score, activity_score,
            comm_score, efficiency_score,
        ]
        scored_dims = [d for d in dimensions if d.data_completeness_pct > 0]
        avg = sum(d.score for d in scored_dims) / max(len(scored_dims), 1)

        return SPACEMetrics(
            satisfaction=satisfaction_score,
            performance=performance_score,
            activity=activity_score,
            communication=comm_score,
            efficiency=efficiency_score,
            overall_score=round(avg * 20, 1),  # Scale 0-5 -> 0-100
        )

    def _score_space_activity(self, data: dict) -> SPACEDimensionScore:
        commits_per_dev = data.get("avg_commits_per_developer_per_week", 0)
        prs_per_dev = data.get("avg_prs_per_developer_per_week", 0)

        # Score: 5 if in target range, scale down outside
        commit_score = min(commits_per_dev / 15, 1.0) * 5 if commits_per_dev <= 30 else max(5 - (commits_per_dev - 30) / 10, 2)
        pr_score = min(prs_per_dev / 3, 1.0) * 5 if prs_per_dev <= 5 else max(5 - (prs_per_dev - 5) / 3, 2)
        avg_score = (commit_score + pr_score) / 2

        sub_metrics = [
            MetricCard(name="Commit Frequency", current_value=round(commits_per_dev, 1), target="15-30/dev/week", tier=Tier.HIGH if 15 <= commits_per_dev <= 30 else Tier.MEDIUM, unit="commits/dev/week"),
            MetricCard(name="PR Throughput", current_value=round(prs_per_dev, 1), target="3-5/dev/week", tier=Tier.HIGH if 3 <= prs_per_dev <= 5 else Tier.MEDIUM, unit="PRs/dev/week"),
        ]

        completeness = 100 if data and "error" not in data else 0

        return SPACEDimensionScore(
            dimension=SPACEDimension.ACTIVITY,
            score=round(avg_score, 2),
            sub_metrics=sub_metrics,
            data_completeness_pct=completeness,
        )

    def _score_space_communication(self, data: dict) -> SPACEDimensionScore:
        pickup_hours = data.get("avg_pr_pickup_time_hours", 0)
        cross_review_pct = data.get("cross_team_review_pct", 0)

        # Pickup time: 5 if < 2h, scale down
        pickup_score = 5.0 if pickup_hours <= 2 else max(5 - (pickup_hours - 2) / 2, 1)
        cross_score = min(cross_review_pct / 20, 1.0) * 5

        avg_score = (pickup_score + cross_score) / 2

        sub_metrics = [
            MetricCard(name="PR Pickup Time", current_value=round(pickup_hours, 1), target="< 2 hours", tier=Tier.ELITE if pickup_hours < 2 else Tier.MEDIUM, unit="hours"),
            MetricCard(name="Cross-team Reviews", current_value=round(cross_review_pct, 1), target=">= 20%", tier=Tier.HIGH if cross_review_pct >= 20 else Tier.MEDIUM, unit="%"),
        ]

        completeness = 100 if data and "error" not in data else 0

        return SPACEDimensionScore(
            dimension=SPACEDimension.COMMUNICATION,
            score=round(avg_score, 2),
            sub_metrics=sub_metrics,
            data_completeness_pct=completeness,
        )

    def _score_space_satisfaction(self, survey_data: dict) -> SPACEDimensionScore:
        nps = survey_data.get("developer_nps", 0)
        tool_sat = survey_data.get("tool_satisfaction", 0)

        if nps == 0 and tool_sat == 0:
            return SPACEDimensionScore(
                dimension=SPACEDimension.SATISFACTION,
                score=0,
                sub_metrics=[MetricCard(name="Developer NPS", current_value="No data", target=">= 7.5/10", tier=Tier.LOW)],
                data_completeness_pct=0,
            )

        nps_score = min(nps / 7.5, 1.0) * 5
        tool_score = min(tool_sat / 4, 1.0) * 5 if tool_sat else nps_score
        avg = (nps_score + tool_score) / 2

        return SPACEDimensionScore(
            dimension=SPACEDimension.SATISFACTION,
            score=round(avg, 2),
            sub_metrics=[
                MetricCard(name="Developer NPS", current_value=nps, target=">= 7.5/10", tier=Tier.HIGH if nps >= 7.5 else Tier.MEDIUM),
                MetricCard(name="Tool Satisfaction", current_value=tool_sat, target=">= 4/5", tier=Tier.HIGH if tool_sat >= 4 else Tier.MEDIUM),
            ],
            data_completeness_pct=100 if nps > 0 else 0,
        )

    def _score_space_performance(self, raw_data: dict) -> SPACEDimensionScore:
        cfr = raw_data.get("change_failure_rate", {}).get("change_failure_rate_pct", 0)
        # Bug escape rate approximated from CFR
        perf_score = 5.0 if cfr < 5 else max(5 - cfr / 5, 1)

        return SPACEDimensionScore(
            dimension=SPACEDimension.PERFORMANCE,
            score=round(perf_score, 2),
            sub_metrics=[
                MetricCard(name="Bug Escape Rate (est.)", current_value=f"{cfr}%", target="< 5%", tier=Tier.HIGH if cfr < 5 else Tier.MEDIUM, unit="%"),
            ],
            data_completeness_pct=50,  # Partial — needs NPS/CSAT data too
        )

    def _score_space_efficiency(self, raw_data: dict) -> SPACEDimensionScore:
        ci_data = raw_data.get("ci_pipeline", {})
        build_time = ci_data.get("avg_build_duration_minutes", 0)

        build_score = 5.0 if build_time <= 10 else max(5 - (build_time - 10) / 10, 1)

        return SPACEDimensionScore(
            dimension=SPACEDimension.EFFICIENCY,
            score=round(build_score, 2),
            sub_metrics=[
                MetricCard(name="Build Wait Time", current_value=round(build_time, 1), target="< 10 min", tier=Tier.ELITE if build_time < 10 else Tier.MEDIUM, unit="minutes"),
            ],
            data_completeness_pct=50 if build_time > 0 else 0,
        )

    # ─── DX Core 4 Computation ─────────────────────────────────────────

    def compute_dx_core4(
        self,
        dora: DORAMetrics,
        space: SPACEMetrics,
        survey_data: dict | None = None,
    ) -> DXCore4Scores:
        """Compute DX Core 4 scores from DORA + SPACE + survey data.

        Speed = 40% deploy_freq + 40% lead_time + 20% productivity survey
        Effectiveness = Developer Experience Index from surveys
        Quality = 40% CFR + 30% rework + 30% code quality survey
        Business Impact = 50% feature adoption + 50% customer satisfaction delta
        """
        survey = survey_data or {}

        # Speed
        speed_dora = (
            TIER_SCORE_MAP[dora.deployment_frequency.tier] * DX_SPEED_WEIGHTS["deploy_frequency_tier"]
            + TIER_SCORE_MAP[dora.lead_time.tier] * DX_SPEED_WEIGHTS["lead_time_tier"]
        )
        speed_survey = survey.get("perceived_productivity", 50) * DX_SPEED_WEIGHTS["perceived_productivity_survey"]
        speed_score = speed_dora + speed_survey

        # Effectiveness (survey-driven)
        effectiveness_score = survey.get("developer_experience_index", 50)

        # Quality
        quality_dora = (
            TIER_SCORE_MAP[dora.change_failure_rate.tier] * DX_QUALITY_WEIGHTS["change_fail_rate_tier"]
            + TIER_SCORE_MAP[dora.rework_rate.tier] * DX_QUALITY_WEIGHTS["rework_rate_tier"]
        )
        quality_survey = survey.get("code_quality_perception", 50) * DX_QUALITY_WEIGHTS["code_quality_survey"]
        quality_score = quality_dora + quality_survey

        # Business Impact (survey-driven)
        feature_adoption = survey.get("feature_adoption_rate", 50) * DX_BUSINESS_IMPACT_WEIGHTS["feature_adoption_rate"]
        csat_delta = survey.get("customer_satisfaction_delta", 50) * DX_BUSINESS_IMPACT_WEIGHTS["customer_satisfaction_delta"]
        biz_score = feature_adoption + csat_delta

        overall = (speed_score + effectiveness_score + quality_score + biz_score) / 4

        return DXCore4Scores(
            speed=DXCore4PillarScore(
                pillar=DXCore4Pillar.SPEED, score=round(speed_score, 1),
                signal="Are we shipping fast enough?",
                components={"deploy_freq": TIER_SCORE_MAP[dora.deployment_frequency.tier], "lead_time": TIER_SCORE_MAP[dora.lead_time.tier]},
            ),
            effectiveness=DXCore4PillarScore(
                pillar=DXCore4Pillar.EFFECTIVENESS, score=round(effectiveness_score, 1),
                signal="Is the dev environment enabling or blocking?",
            ),
            quality=DXCore4PillarScore(
                pillar=DXCore4Pillar.QUALITY, score=round(quality_score, 1),
                signal="Is what we ship reliable?",
                components={"cfr": TIER_SCORE_MAP[dora.change_failure_rate.tier], "rework": TIER_SCORE_MAP[dora.rework_rate.tier]},
            ),
            business_impact=DXCore4PillarScore(
                pillar=DXCore4Pillar.BUSINESS_IMPACT, score=round(biz_score, 1),
                signal="Does engineering output drive revenue?",
            ),
            overall_score=round(overall, 1),
        )

    # ─── AI Capabilities Scoring ───────────────────────────────────────

    def compute_ai_capabilities(self, assessment_data: dict) -> AICapabilitiesAssessment:
        """Compute AI Capabilities maturity scores from assessment data.

        Each capability scored 1-4. Average maturity * 25 = 0-100 normalized score.
        """
        capabilities = []
        for cap_id, cap_info in AI_CAPABILITIES.items():
            level = assessment_data.get(str(cap_id), assessment_data.get(cap_info["name"], 1))
            level = max(1, min(4, int(level)))

            capabilities.append(AICapabilityScore(
                capability_id=cap_id,
                name=str(cap_info["name"]),
                maturity_level=level,
                maturity_label=str(cap_info["maturity_levels"][level]),  # type: ignore[index]
            ))

        avg_maturity = sum(c.maturity_level for c in capabilities) / max(len(capabilities), 1)
        normalized = avg_maturity * 25  # Scale 1-4 -> 25-100

        all_above_2 = all(c.maturity_level >= 2 for c in capabilities)
        first_three_above_3 = all(c.maturity_level >= 3 for c in capabilities[:3])

        return AICapabilitiesAssessment(
            capabilities=capabilities,
            average_maturity=round(avg_maturity, 2),
            normalized_score=round(normalized, 1),
            ready_for_ai_coding=all_above_2,
            ready_for_ai_production=first_three_above_3,
        )

    # ─── Composite Score ───────────────────────────────────────────────

    def compute_composite_score(
        self,
        dora: DORAMetrics,
        space: SPACEMetrics,
        dx_core4: DXCore4Scores,
        ai_capabilities: AICapabilitiesAssessment,
    ) -> CompositeScore:
        """Final score = (DORA * 0.40) + (SPACE * 0.25) + (DX Core 4 * 0.20) + (AI Cap * 0.15)"""
        final = (
            dora.overall_score * COMPOSITE_WEIGHTS["dora"]
            + space.overall_score * COMPOSITE_WEIGHTS["space"]
            + dx_core4.overall_score * COMPOSITE_WEIGHTS["dx_core4"]
            + ai_capabilities.normalized_score * COMPOSITE_WEIGHTS["ai_capabilities"]
        )

        tier = self._classify_overall_tier(dora, space, ai_capabilities)

        return CompositeScore(
            dora_score=dora.overall_score,
            space_score=space.overall_score,
            dx_core4_score=dx_core4.overall_score,
            ai_capabilities_score=ai_capabilities.normalized_score,
            final_score=round(final, 1),
            overall_tier=tier,
        )

    def _classify_overall_tier(
        self,
        dora: DORAMetrics,
        space: SPACEMetrics,
        ai_cap: AICapabilitiesAssessment,
    ) -> OverallTier:
        """Classify into Platinum/Gold/Silver/Bronze per Section 12.1."""
        space_avg = space.overall_score / 20  # Back to 0-5 scale

        # Platinum: Elite in >= 4 of 5 DORA, SPACE >= 4.0, AI >= 3.5
        if dora.elite_count >= 4 and space_avg >= 4.0 and ai_cap.average_maturity >= 3.5:
            return OverallTier.PLATINUM

        # Gold: High in >= 4 of 5 DORA, SPACE >= 3.5, AI >= 3.0
        dora_high_plus = sum(
            1 for t in [
                dora.deployment_frequency.tier, dora.lead_time.tier,
                dora.change_failure_rate.tier, dora.recovery_time.tier,
                dora.rework_rate.tier,
            ]
            if t in (Tier.ELITE, Tier.HIGH)
        )
        if dora_high_plus >= 4 and space_avg >= 3.5 and ai_cap.average_maturity >= 3.0:
            return OverallTier.GOLD

        # Silver: Medium in >= 4 of 5 DORA, SPACE >= 3.0, AI >= 2.5
        dora_medium_plus = sum(
            1 for t in [
                dora.deployment_frequency.tier, dora.lead_time.tier,
                dora.change_failure_rate.tier, dora.recovery_time.tier,
                dora.rework_rate.tier,
            ]
            if t in (Tier.ELITE, Tier.HIGH, Tier.MEDIUM)
        )
        if dora_medium_plus >= 4 and space_avg >= 3.0 and ai_cap.average_maturity >= 2.5:
            return OverallTier.SILVER

        return OverallTier.BRONZE

    # ─── Recommendations Engine ────────────────────────────────────────

    def generate_recommendations(
        self,
        dora: DORAMetrics,
        space: SPACEMetrics,
        dx_core4: DXCore4Scores,
        ai_capabilities: AICapabilitiesAssessment,
    ) -> list[Recommendation]:
        """Generate 3-5 actionable recommendations based on gap analysis.

        Identifies lowest-scoring metrics, cross-references with AI capabilities,
        and generates specific improvement steps with expected impact.
        """
        recommendations = []
        priority = 1

        # Collect all scored areas
        metric_scores = [
            ("DORA - Deployment Frequency", TIER_SCORE_MAP[dora.deployment_frequency.tier], dora.deployment_frequency),
            ("DORA - Lead Time", TIER_SCORE_MAP[dora.lead_time.tier], dora.lead_time),
            ("DORA - Change Failure Rate", TIER_SCORE_MAP[dora.change_failure_rate.tier], dora.change_failure_rate),
            ("DORA - Recovery Time", TIER_SCORE_MAP[dora.recovery_time.tier], dora.recovery_time),
            ("DORA - Rework Rate", TIER_SCORE_MAP[dora.rework_rate.tier], dora.rework_rate),
        ]

        # Sort by score (lowest first) — focus on biggest gaps
        metric_scores.sort(key=lambda x: x[1])

        for area, score, detail in metric_scores[:3]:  # Top 3 weakest areas
            rec = self._generate_dora_recommendation(area, detail, ai_capabilities, priority)
            if rec:
                recommendations.append(rec)
                priority += 1

        # Check SPACE gaps
        for dim in [space.satisfaction, space.performance, space.activity, space.communication, space.efficiency]:
            if dim.score < 3.0 and dim.data_completeness_pct > 0:
                recommendations.append(Recommendation(
                    priority=priority,
                    area=f"SPACE - {dim.dimension.value.title()}",
                    current_state=f"Score: {dim.score}/5.0",
                    target_state="Score: >= 3.5/5.0",
                    actions=self._get_space_improvement_actions(dim.dimension),
                    expected_impact="Improved developer productivity and wellbeing",
                ))
                priority += 1

        # Check AI Capabilities readiness
        low_caps = [c for c in ai_capabilities.capabilities if c.maturity_level < 2]
        if low_caps:
            cap_names = ", ".join(c.name for c in low_caps)
            recommendations.append(Recommendation(
                priority=priority,
                area="AI Capabilities Readiness",
                current_state=f"Capabilities below minimum: {cap_names}",
                target_state="All capabilities at maturity level 2+",
                actions=[
                    f"Prioritize improving: {cap_names}",
                    "Conduct structured team assessment for each capability",
                    "Create improvement roadmap with quarterly milestones",
                ],
                expected_impact="Prerequisite for safe AI coding assistant adoption",
                related_capability=cap_names,
            ))

        return recommendations[:5]  # Max 5 recommendations

    def _generate_dora_recommendation(
        self, area: str, detail: DORAMetricDetail, ai_cap: AICapabilitiesAssessment, priority: int
    ) -> Recommendation | None:
        if detail.tier in (Tier.ELITE, Tier.HIGH):
            return None

        actions_map = {
            "DORA - Deployment Frequency": [
                "Implement trunk-based development with feature flags",
                "Add automated deployment pipeline triggers on merge to main",
                "Reduce deployment batch sizes — aim for < 100 LOC per deploy",
            ],
            "DORA - Lead Time": [
                "Enable GitHub review request auto-assignment",
                "Set team SLA of 2-hour first review",
                "Add Slack notification on PR creation",
                "Reduce PR size limit to < 200 lines for faster reviews",
            ],
            "DORA - Change Failure Rate": [
                "Increase unit test coverage to >= 80%",
                "Add integration tests for all critical API paths",
                "Implement canary deployments with auto-rollback",
                "Add SAST scanning to PR gates",
            ],
            "DORA - Recovery Time": [
                "Implement automated rollback on health check failure",
                "Create runbooks for top 5 failure scenarios",
                "Set up PagerDuty with < 15 min acknowledgment SLA",
                "Practice incident response drills quarterly",
            ],
            "DORA - Rework Rate": [
                "Invest in code review quality — substantive reviews, not rubber stamps",
                "Track and resolve recurring bug categories",
                "Add mutation testing to catch test gaps",
                "Review AI-generated code more carefully (flag PRs with > 50% AI code)",
            ],
        }

        next_tier = Tier.HIGH if detail.tier == Tier.MEDIUM else Tier.MEDIUM
        return Recommendation(
            priority=priority,
            area=area,
            current_state=f"{detail.label} ({detail.tier.value} tier)",
            target_state=f"Move to {next_tier.value} tier",
            actions=actions_map.get(area, ["Review metrics and identify specific bottlenecks"]),
            expected_impact=f"Moving from {detail.tier.value} to {next_tier.value} tier",
        )

    def _get_space_improvement_actions(self, dimension: SPACEDimension) -> list[str]:
        actions = {
            SPACEDimension.SATISFACTION: [
                "Conduct developer NPS survey",
                "Address top 3 developer pain points from survey results",
                "Improve tooling based on satisfaction feedback",
            ],
            SPACEDimension.PERFORMANCE: [
                "Reduce bug escape rate with better test coverage",
                "Implement code quality gates (SonarQube/CodeClimate)",
                "Track and reduce P1 incident frequency",
            ],
            SPACEDimension.ACTIVITY: [
                "Review PR throughput targets with team",
                "Reduce PR size to encourage more frequent merges",
                "Track documentation contributions per sprint",
            ],
            SPACEDimension.COMMUNICATION: [
                "Set PR review pickup SLA (< 2 hours)",
                "Encourage cross-team code reviews (>= 20%)",
                "Reduce meeting load to < 8 hours/week",
            ],
            SPACEDimension.EFFICIENCY: [
                "Optimize CI pipeline to < 10 minutes",
                "Reduce cycle time (issue to deployed) to < 5 days",
                "Minimize context switching (< 5 task switches/day)",
            ],
        }
        return actions.get(dimension, ["Investigate root causes and create improvement plan"])
