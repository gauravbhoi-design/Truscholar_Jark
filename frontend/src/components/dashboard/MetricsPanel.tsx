"use client";

import { useState, useEffect } from "react";
import {
  Activity,
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  BarChart3,
  Target,
  Zap,
  Brain,
  ArrowUpRight,
  AlertTriangle,
  CheckCircle2,
  Info,
} from "lucide-react";
import { fetchMetricsDashboard, type MetricsDashboardData } from "@/lib/api";
import { getSelectedRepos, subscribeRepos } from "@/lib/repo-store";

// ─── Tier Colors ──────────────────────────────────────────────────────────

const TIER_STYLES = {
  elite: { bg: "bg-purple-500/10", text: "text-purple-500", label: "Elite" },
  high: { bg: "bg-amber-500/10", text: "text-amber-500", label: "High" },
  medium: { bg: "bg-blue-500/10", text: "text-blue-500", label: "Medium" },
  low: { bg: "bg-gray-500/10", text: "text-gray-400", label: "Low" },
};

const OVERALL_TIER_STYLES = {
  platinum: { bg: "bg-purple-500/15", text: "text-purple-400", border: "border-purple-500/30", label: "Platinum" },
  gold: { bg: "bg-amber-500/15", text: "text-amber-400", border: "border-amber-500/30", label: "Gold" },
  silver: { bg: "bg-blue-500/15", text: "text-blue-400", border: "border-blue-500/30", label: "Silver" },
  bronze: { bg: "bg-gray-500/15", text: "text-gray-400", border: "border-gray-500/30", label: "Bronze" },
};

function TierBadge({ tier }: { tier: string }) {
  const style = TIER_STYLES[tier as keyof typeof TIER_STYLES] || TIER_STYLES.low;
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function TrendIcon({ direction }: { direction: string }) {
  if (direction === "improving") return <TrendingUp className="h-3 w-3 text-green-500" />;
  if (direction === "declining") return <TrendingDown className="h-3 w-3 text-red-500" />;
  return <Minus className="h-3 w-3 text-muted-foreground" />;
}

// ─── Score Ring ───────────────────────────────────────────────────────────

function ScoreRing({ score, size = 120, label }: { score: number; size?: number; label: string }) {
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 75 ? "#7C3AED" : score >= 50 ? "#F59E0B" : score >= 25 ? "#3B82F6" : "#6B7280";

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="currentColor" className="text-muted/20" strokeWidth="6" />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeWidth="6" strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" className="transition-all duration-1000" />
      </svg>
      <div className="absolute flex flex-col items-center justify-center" style={{ width: size, height: size }}>
        <span className="text-2xl font-bold">{Math.round(score)}</span>
        <span className="text-[10px] text-muted-foreground">/100</span>
      </div>
      <span className="text-xs text-muted-foreground font-medium">{label}</span>
    </div>
  );
}

// ─── DORA Metrics Card ───────────────────────────────────────────────────

function DORACard({ metrics }: { metrics: MetricsDashboardData["dora"] }) {
  const doraItems = [
    { label: "Deploy Frequency", value: `${metrics.deployment_frequency.value}/day`, tier: metrics.deployment_frequency.tier, desc: metrics.deployment_frequency.label },
    { label: "Lead Time", value: `${metrics.lead_time.value}h`, tier: metrics.lead_time.tier, desc: metrics.lead_time.label },
    { label: "Change Fail Rate", value: `${metrics.change_failure_rate.value}%`, tier: metrics.change_failure_rate.tier, desc: metrics.change_failure_rate.label },
    { label: "Recovery Time", value: `${metrics.recovery_time.value}h`, tier: metrics.recovery_time.tier, desc: metrics.recovery_time.label },
    { label: "Rework Rate", value: `${metrics.rework_rate.value}%`, tier: metrics.rework_rate.tier, desc: metrics.rework_rate.label },
  ];

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">DORA Metrics (5 Keys)</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Score: {metrics.overall_score}/100</span>
          <span className="text-xs text-muted-foreground">({metrics.elite_count} Elite)</span>
        </div>
      </div>
      <div className="divide-y">
        {doraItems.map((item) => (
          <div key={item.label} className="flex items-center justify-between px-4 py-2.5">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{item.label}</span>
                <TierBadge tier={item.tier} />
              </div>
              <span className="text-[10px] text-muted-foreground">{item.desc}</span>
            </div>
            <span className="text-sm font-mono font-bold">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── SPACE Radar Card ────────────────────────────────────────────────────

function SPACECard({ metrics }: { metrics: MetricsDashboardData["space"] }) {
  const dimensions = [
    { name: "Satisfaction", score: metrics.satisfaction.score, completeness: metrics.satisfaction.data_completeness_pct },
    { name: "Performance", score: metrics.performance.score, completeness: metrics.performance.data_completeness_pct },
    { name: "Activity", score: metrics.activity.score, completeness: metrics.activity.data_completeness_pct },
    { name: "Communication", score: metrics.communication.score, completeness: metrics.communication.data_completeness_pct },
    { name: "Efficiency", score: metrics.efficiency.score, completeness: metrics.efficiency.data_completeness_pct },
  ];

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-cyan-500" />
          <h3 className="text-sm font-semibold">SPACE Framework</h3>
        </div>
        <span className="text-xs text-muted-foreground">Score: {metrics.overall_score}/100</span>
      </div>
      <div className="p-4 space-y-3">
        {dimensions.map((dim) => (
          <div key={dim.name}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium">{dim.name}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono">{dim.score.toFixed(1)}/5</span>
                {dim.completeness < 50 && (
                  <span className="text-[10px] text-amber-500 flex items-center gap-0.5">
                    <Info className="h-2.5 w-2.5" /> Partial data
                  </span>
                )}
              </div>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${(dim.score / 5) * 100}%`,
                  backgroundColor: dim.score >= 4 ? "#7C3AED" : dim.score >= 3 ? "#3B82F6" : dim.score >= 2 ? "#F59E0B" : "#6B7280",
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── DX Core 4 Card ──────────────────────────────────────────────────────

function DXCore4Card({ scores }: { scores: MetricsDashboardData["dx_core4"] }) {
  const pillars = [
    { name: "Speed", score: scores.speed.score, signal: scores.speed.signal, icon: Zap },
    { name: "Effectiveness", score: scores.effectiveness.score, signal: scores.effectiveness.signal, icon: Target },
    { name: "Quality", score: scores.quality.score, signal: scores.quality.signal, icon: CheckCircle2 },
    { name: "Business Impact", score: scores.business_impact.score, signal: scores.business_impact.signal, icon: TrendingUp },
  ];

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-green-500" />
          <h3 className="text-sm font-semibold">DX Core 4</h3>
        </div>
        <span className="text-xs text-muted-foreground">Avg: {scores.overall_score}/100</span>
      </div>
      <div className="grid grid-cols-2 gap-3 p-4">
        {pillars.map((p) => {
          const Icon = p.icon;
          return (
            <div key={p.name} className="border rounded-md p-3">
              <div className="flex items-center gap-2 mb-2">
                <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs font-semibold">{p.name}</span>
              </div>
              <div className="text-xl font-bold">{Math.round(p.score)}</div>
              <p className="text-[10px] text-muted-foreground mt-1">{p.signal}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── AI Capabilities Heatmap ─────────────────────────────────────────────

function AICapabilitiesCard({ assessment }: { assessment: MetricsDashboardData["ai_capabilities"] }) {
  const maturityColors = {
    1: "bg-red-500/20 text-red-400 border-red-500/30",
    2: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    3: "bg-green-500/20 text-green-400 border-green-500/30",
    4: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  };

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-violet-500" />
          <h3 className="text-sm font-semibold">AI Capabilities Model</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Avg: {assessment.average_maturity.toFixed(1)}/4</span>
          {assessment.ready_for_ai_coding ? (
            <span className="text-[10px] text-green-500 flex items-center gap-0.5">
              <CheckCircle2 className="h-2.5 w-2.5" /> AI-ready
            </span>
          ) : (
            <span className="text-[10px] text-amber-500 flex items-center gap-0.5">
              <AlertTriangle className="h-2.5 w-2.5" /> Not AI-ready
            </span>
          )}
        </div>
      </div>
      <div className="p-4 space-y-2">
        {assessment.capabilities.map((cap) => {
          const colorClass = maturityColors[cap.maturity_level as keyof typeof maturityColors] || maturityColors[1];
          return (
            <div key={cap.capability_id} className="flex items-center gap-3">
              <span className="text-xs w-40 truncate">{cap.name}</span>
              <div className="flex gap-1 flex-1">
                {[1, 2, 3, 4].map((level) => (
                  <div
                    key={level}
                    className={`h-5 flex-1 rounded-sm border text-[9px] flex items-center justify-center font-medium ${
                      level <= cap.maturity_level ? colorClass : "bg-muted/30 text-muted-foreground/30 border-transparent"
                    }`}
                  >
                    {level === cap.maturity_level ? cap.maturity_label : ""}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Recommendations Card ────────────────────────────────────────────────

function RecommendationsCard({ recommendations }: { recommendations: MetricsDashboardData["top_recommendations"] }) {
  if (!recommendations || recommendations.length === 0) return null;

  return (
    <div className="border rounded-lg bg-card overflow-hidden col-span-2">
      <div className="flex items-center gap-2 px-4 py-3 border-b bg-muted/30">
        <ArrowUpRight className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold">Top Improvement Recommendations</h3>
      </div>
      <div className="divide-y">
        {recommendations.map((rec, i) => (
          <div key={i} className="px-4 py-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="flex items-center justify-center w-5 h-5 rounded-full bg-primary/10 text-primary text-[10px] font-bold">
                {rec.priority}
              </span>
              <span className="text-xs font-semibold">{rec.area}</span>
            </div>
            <div className="flex items-center gap-2 text-[11px] mb-2">
              <span className="text-muted-foreground">{rec.current_state}</span>
              <ArrowUpRight className="h-3 w-3 text-muted-foreground" />
              <span className="text-primary font-medium">{rec.target_state}</span>
            </div>
            <ul className="space-y-1 ml-7">
              {rec.actions.slice(0, 3).map((action, j) => (
                <li key={j} className="text-[11px] text-muted-foreground flex items-start gap-1.5">
                  <CheckCircle2 className="h-3 w-3 text-muted-foreground/50 mt-0.5 shrink-0" />
                  {action}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Panel ──────────────────────────────────────────────────────────

export function MetricsPanel() {
  const [data, setData] = useState<MetricsDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<string | null>(() => {
    const repos = getSelectedRepos();
    return repos.length > 0 ? repos[0] : null;
  });

  // Sync with repo store changes from other components
  useEffect(() => {
    const unsubscribe = subscribeRepos((repos) => {
      setSelectedRepo(repos.length > 0 ? repos[0] : null);
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (!selectedRepo) {
      setLoading(false);
      setError("Select a repository in the Repositories tab to view engineering metrics.");
      return;
    }

    setLoading(true);
    setError(null);

    fetchMetricsDashboard(selectedRepo)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [selectedRepo]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Collecting engineering metrics...</span>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-sm">
          <AlertTriangle className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">{error || "No data available"}</p>
        </div>
      </div>
    );
  }

  const tierStyle = OVERALL_TIER_STYLES[data.composite.overall_tier as keyof typeof OVERALL_TIER_STYLES] || OVERALL_TIER_STYLES.bronze;

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Header + Composite Score */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold">Engineering Metrics</h2>
          <p className="text-sm text-muted-foreground">
            TruScholar Performance Standards — DORA, SPACE, DX Core 4, AI Capabilities
          </p>
        </div>
        <div className={`flex items-center gap-3 px-4 py-2 rounded-lg border ${tierStyle.bg} ${tierStyle.border}`}>
          <div className="text-right">
            <div className="text-2xl font-bold">{Math.round(data.composite.final_score)}</div>
            <div className="text-[10px] text-muted-foreground">Composite Score</div>
          </div>
          <div className={`px-3 py-1 rounded-full text-xs font-bold ${tierStyle.bg} ${tierStyle.text}`}>
            {tierStyle.label}
          </div>
        </div>
      </div>

      {/* Score Breakdown Bar */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { label: "DORA (40%)", score: data.composite.dora_score, color: "#7C3AED" },
          { label: "SPACE (25%)", score: data.composite.space_score, color: "#06B6D4" },
          { label: "DX Core 4 (20%)", score: data.composite.dx_core4_score, color: "#10B981" },
          { label: "AI Cap (15%)", score: data.composite.ai_capabilities_score, color: "#8B5CF6" },
        ].map((item) => (
          <div key={item.label} className="border rounded-md p-3 bg-card">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] text-muted-foreground font-medium">{item.label}</span>
              <span className="text-sm font-bold">{Math.round(item.score)}</span>
            </div>
            <div className="h-1.5 bg-muted rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-700" style={{ width: `${item.score}%`, backgroundColor: item.color }} />
            </div>
          </div>
        ))}
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <DORACard metrics={data.dora} />
        <SPACECard metrics={data.space} />
        <DXCore4Card scores={data.dx_core4} />
        <AICapabilitiesCard assessment={data.ai_capabilities} />
      </div>

      {/* Recommendations */}
      <div className="grid grid-cols-2 gap-4">
        <RecommendationsCard recommendations={data.top_recommendations} />
      </div>
    </div>
  );
}
