"use client";

import { useState, useEffect } from "react";
import {
  Activity,
  GitBranch,
  Cloud,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Loader2,
  TrendingUp,
  Clock,
  Zap,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getAuthHeader(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
  return { Authorization: `Bearer ${token || ""}`, "Content-Type": "application/json" };
}

interface ServiceStatus {
  name: string;
  status: "healthy" | "degraded" | "down" | "unknown";
  type: string;
  region?: string;
}

interface RecentAnalysis {
  id: string;
  title: string;
  category: string;
  created_at: string;
}

function MetricCard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  color = "text-primary",
}: {
  title: string;
  value: string;
  subtitle: string;
  icon: typeof Activity;
  trend?: "up" | "down" | "neutral";
  color?: string;
}) {
  return (
    <div className="border rounded-lg p-4 bg-card">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-muted-foreground font-medium">{title}</span>
        <Icon className={`h-4 w-4 ${color}`} />
      </div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-bold">{value}</span>
        {trend && (
          <span className={`flex items-center text-xs ${trend === "up" ? "text-green-500" : trend === "down" ? "text-red-500" : "text-muted-foreground"}`}>
            {trend === "up" ? <ArrowUpRight className="h-3 w-3" /> : trend === "down" ? <ArrowDownRight className="h-3 w-3" /> : null}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
    </div>
  );
}

function ConnectionBadge({ name, connected, icon: Icon }: { name: string; connected: boolean; icon: typeof Cloud }) {
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs ${connected ? "bg-green-500/10 text-green-500" : "bg-muted text-muted-foreground"}`}>
      <Icon className="h-3.5 w-3.5" />
      {name}
      {connected ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
    </div>
  );
}

export function OverviewPanel() {
  const [gcpStatus, setGcpStatus] = useState<{ connected: boolean; project_id?: string }>({ connected: false });
  const [githubStatus, setGithubStatus] = useState<{ connected: boolean; login?: string }>({ connected: false });
  const [zohoStatus, setZohoStatus] = useState<{ connected: boolean; email?: string }>({ connected: false });
  const [recentAnalyses, setRecentAnalyses] = useState<RecentAnalysis[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_URL}/auth/gcp/status`, { headers: getAuthHeader() }).then((r) => r.ok ? r.json() : { connected: false }),
      fetch(`${API_URL}/auth/github/status`, { headers: getAuthHeader() }).then((r) => r.ok ? r.json() : { connected: false }),
      fetch(`${API_URL}/auth/zoho/status`, { headers: getAuthHeader() }).then((r) => r.ok ? r.json() : { connected: false }),
      fetch(`${API_URL}/memory/analyses?limit=5`, { headers: getAuthHeader() }).then((r) => r.ok ? r.json() : []),
    ])
      .then(([gcp, github, zoho, analyses]) => {
        setGcpStatus(gcp);
        setGithubStatus(github);
        setZohoStatus(zoho);
        setRecentAnalyses(analyses);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const connectedCount = [gcpStatus.connected, githubStatus.connected, zohoStatus.connected].filter(Boolean).length;

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold">Dashboard</h2>
          <p className="text-sm text-muted-foreground">Your DevOps operations at a glance</p>
        </div>
        <div className="flex items-center gap-2">
          <ConnectionBadge name="GitHub" connected={githubStatus.connected} icon={GitBranch} />
          <ConnectionBadge name="GCP" connected={gcpStatus.connected} icon={Cloud} />
          <ConnectionBadge name="Zoho" connected={zohoStatus.connected} icon={BarChart3} />
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <MetricCard
          title="Connected Services"
          value={`${connectedCount}/3`}
          subtitle="GitHub, GCP, Zoho"
          icon={Zap}
          color={connectedCount === 3 ? "text-green-500" : "text-yellow-500"}
        />
        <MetricCard
          title="GCP Project"
          value={gcpStatus.project_id || "—"}
          subtitle={gcpStatus.connected ? "Active" : "Not connected"}
          icon={Cloud}
          color={gcpStatus.connected ? "text-blue-500" : "text-muted-foreground"}
        />
        <MetricCard
          title="GitHub Repos"
          value={githubStatus.connected ? (githubStatus.login || "Connected") : "—"}
          subtitle={githubStatus.connected ? "Linked" : "Not connected"}
          icon={GitBranch}
          color={githubStatus.connected ? "text-purple-500" : "text-muted-foreground"}
        />
        <MetricCard
          title="AI Analyses"
          value={String(recentAnalyses.length)}
          subtitle="In memory"
          icon={Activity}
          color="text-primary"
        />
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Recent Analyses */}
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b bg-muted/30">
            <Activity className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-medium">Recent AI Analyses</h3>
          </div>
          <div className="divide-y">
            {recentAnalyses.length === 0 ? (
              <div className="p-6 text-center text-xs text-muted-foreground">
                No analyses yet. Ask a question in Chat to get started.
              </div>
            ) : (
              recentAnalyses.map((a) => (
                <div key={a.id} className="px-4 py-3 flex items-start gap-3">
                  <span className={`mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                    a.category === "error" ? "bg-red-500/10 text-red-500"
                    : a.category === "fix" ? "bg-green-500/10 text-green-500"
                    : "bg-primary/10 text-primary"
                  }`}>
                    {a.category}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate">{a.title}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {new Date(a.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b bg-muted/30">
            <Zap className="h-4 w-4 text-yellow-500" />
            <h3 className="text-sm font-medium">Quick Actions</h3>
          </div>
          <div className="p-4 space-y-2">
            {[
              { label: "Check GCP error logs", icon: AlertCircle, color: "text-red-400", query: "check my GCP project logs for errors" },
              { label: "Analyze CI/CD pipelines", icon: GitBranch, color: "text-purple-400", query: "analyze my CI/CD pipelines" },
              { label: "List active GCP services", icon: Cloud, color: "text-blue-400", query: "list active services in my GCP project" },
              { label: "Review code security", icon: CheckCircle2, color: "text-green-400", query: "review my code for security vulnerabilities" },
              { label: "Check deployment status", icon: TrendingUp, color: "text-cyan-400", query: "check recent deployment status" },
            ].map((action) => (
              <button
                key={action.label}
                onClick={() => {
                  // Navigate to chat with pre-filled query
                  if (typeof window !== "undefined") {
                    localStorage.setItem("prefill_query", action.query);
                    // Dispatch event for tab switch
                    window.dispatchEvent(new CustomEvent("navigate-tab", { detail: "chat" }));
                  }
                }}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-left hover:bg-muted/50 transition-colors group"
              >
                <action.icon className={`h-4 w-4 ${action.color} shrink-0`} />
                <span className="text-muted-foreground group-hover:text-foreground transition-colors">{action.label}</span>
                <ArrowUpRight className="h-3 w-3 ml-auto text-muted-foreground/30 group-hover:text-muted-foreground transition-colors" />
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
