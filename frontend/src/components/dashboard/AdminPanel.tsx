"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Users,
  DollarSign,
  MessageSquare,
  Loader2,
  AlertCircle,
  Search,
  Shield,
  RefreshCw,
  Activity,
  X,
  Terminal,
  Cloud,
  Github,
  Wrench,
  TrendingUp,
  Database,
  ChevronRight,
  ChevronDown,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getAuthHeader(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
  return { Authorization: `Bearer ${token || ""}`, "Content-Type": "application/json" };
}

// ─── Types ─────────────────────────────────────────────────────────────────

interface AdminUser {
  id: string;
  email: string;
  name: string;
  login: string | null;
  avatar_url: string | null;
  role: string;
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
  last_active_at: string | null;
  login_count: number;
  primary_agent: string | null;
  conversation_count: number;
  message_count: number;
  plan_count: number;
  installation_count: number;
  total_cost_usd: number;
}

interface AdminUsersResponse {
  total_users: number;
  total_cost_usd: number;
  users: AdminUser[];
}

interface PlatformActivity {
  dau: number;
  wau: number;
  mau: number;
  total_users: number;
  new_users_30d: number;
  top_agents: { agent: string; calls: number; cost_usd: number }[];
  top_tools: { tool: string; calls: number; kind: "cli" | "mcp" }[];
  cost_trend_7d: { date: string; cost_usd: number; message_count: number }[];
}

interface UserDetail {
  user: AdminUser & { auth0_sub: string | null };
  totals: {
    conversation_count: number;
    plan_count: number;
    conversation_cost_usd: number;
    plan_cost_usd: number;
    total_cost_usd: number;
    tool_calls_total: number;
    tool_calls_cli: number;
    tool_calls_mcp: number;
  };
  per_agent: { agent: string; message_count: number; cost_usd: number }[];
  per_tool: { tool: string; agent: string; call_count: number; avg_duration_ms: number; kind: "cli" | "mcp" }[];
  services: { provider: string; email: string | null; project_id: string | null; is_active: boolean; connected_at: string | null; last_used_at: string | null }[];
  github_app_installations: { installation_id: number; account_login: string; account_type: string; is_active: boolean; installed_at: string | null }[];
  recent_conversations: { id: string; title: string; message_count: number; cost_usd: number; created_at: string | null; updated_at: string | null }[];
  recent_audit_log: { id: string; agent: string; tool: string; duration_ms: number; approved: boolean; created_at: string | null; tool_input_preview: string | null }[];
  cost_trend_30d: { date: string; cost_usd: number; message_count: number }[];
}

interface DbColumn {
  name: string;
  type: string;
}
interface DbTableSummary {
  table: string;
  row_count?: number;
  columns?: DbColumn[];
  error?: string;
}
interface DbInspectSummary {
  database: string | null;
  total_tables: number;
  total_rows: number;
  tables: DbTableSummary[];
}
interface DbInspectDetail {
  table: string;
  total_rows: number;
  returned: number;
  ordered_by: string;
  rows: Record<string, unknown>[];
}

interface BillingWindow {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  message_count: number;
}

interface BillingData {
  totals: {
    today: BillingWindow;
    last_7d: BillingWindow;
    last_30d: BillingWindow;
    mtd: BillingWindow;
    all_time: BillingWindow;
  };
  projected_monthly_usd: number;
  daily_trend_30d: { date: string; cost_usd: number; input_tokens: number; output_tokens: number; message_count: number }[];
  per_agent: { agent: string; calls: number; cost_usd: number; input_tokens: number; output_tokens: number; avg_cost_usd: number }[];
  per_model: { model: string; calls: number; cost_usd: number; input_tokens: number; output_tokens: number }[];
  top_users: { id: string; email: string; name: string; login: string | null; avatar_url: string | null; message_count: number; cost_usd: number; input_tokens: number; output_tokens: number }[];
}

const ROLES = ["admin", "engineer", "viewer"] as const;
type AdminTab = "users" | "billing";

// ─── Formatters ────────────────────────────────────────────────────────────

function formatUsd(n: number): string {
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  if (n > 0) return `$${n.toFixed(6)}`;
  return "$0.00";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const now = Date.now();
  const diff = now - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

// ─── Reusable bits ─────────────────────────────────────────────────────────

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  color = "text-primary",
}: {
  title: string;
  value: string;
  subtitle?: string;
  icon: typeof Users;
  color?: string;
}) {
  return (
    <div className="border rounded-lg p-4 bg-card">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-muted-foreground font-medium">{title}</span>
        <Icon className={`h-4 w-4 ${color}`} />
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {subtitle && <div className="text-xs text-muted-foreground mt-1">{subtitle}</div>}
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length === 0) return <div className="h-8 text-xs text-muted-foreground">no data</div>;
  const max = Math.max(...points, 0.0001);
  const w = 120;
  const h = 32;
  const step = points.length > 1 ? w / (points.length - 1) : 0;
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${i * step},${h - (p / max) * h}`)
    .join(" ");
  return (
    <svg width={w} height={h} className="text-primary">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

// ─── Activity header ───────────────────────────────────────────────────────

function PlatformActivityCard({ activity }: { activity: PlatformActivity | null }) {
  if (!activity) return null;
  const sparklinePoints = activity.cost_trend_7d.map((d) => d.cost_usd);
  const trend7Total = activity.cost_trend_7d.reduce((s, d) => s + d.cost_usd, 0);

  return (
    <div className="border rounded-lg bg-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          Platform Activity
        </h3>
        <span className="text-xs text-muted-foreground">
          {activity.new_users_30d} new users in last 30 days
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <div className="text-xs text-muted-foreground">DAU</div>
          <div className="text-xl font-bold">{activity.dau}</div>
          <div className="text-xs text-muted-foreground">last 24h</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">WAU</div>
          <div className="text-xl font-bold">{activity.wau}</div>
          <div className="text-xs text-muted-foreground">last 7d</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">MAU</div>
          <div className="text-xl font-bold">{activity.mau}</div>
          <div className="text-xs text-muted-foreground">last 30d</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Cost (7d)</div>
          <div className="text-xl font-bold">{formatUsd(trend7Total)}</div>
          <Sparkline points={sparklinePoints} />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t">
        <div>
          <div className="text-xs uppercase text-muted-foreground font-medium mb-2">Top Agents</div>
          {activity.top_agents.length === 0 && (
            <div className="text-xs text-muted-foreground">No agent activity yet</div>
          )}
          {activity.top_agents.map((a) => (
            <div key={a.agent} className="flex items-center justify-between text-xs py-1">
              <span className="font-medium">{a.agent}</span>
              <span className="text-muted-foreground tabular-nums">
                {a.calls.toLocaleString()} calls · {formatUsd(a.cost_usd)}
              </span>
            </div>
          ))}
        </div>

        <div>
          <div className="text-xs uppercase text-muted-foreground font-medium mb-2">Top Tools</div>
          {activity.top_tools.length === 0 && (
            <div className="text-xs text-muted-foreground">No tool calls yet</div>
          )}
          {activity.top_tools.map((t) => (
            <div key={t.tool} className="flex items-center justify-between text-xs py-1">
              <span className="font-medium flex items-center gap-1.5">
                {t.kind === "cli" ? (
                  <Terminal className="h-3 w-3 text-orange-500" />
                ) : (
                  <Wrench className="h-3 w-3 text-blue-500" />
                )}
                {t.tool}
              </span>
              <span className="text-muted-foreground tabular-nums">
                {t.calls.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── User drill-down modal ─────────────────────────────────────────────────

function UserDetailModal({
  userId,
  onClose,
}: {
  userId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/admin/users/${userId}`, { headers: getAuthHeader() });
        if (!res.ok) {
          setError(`Failed to load user (HTTP ${res.status})`);
          return;
        }
        const json = (await res.json()) as UserDetail;
        if (!cancelled) setDetail(json);
      } catch {
        if (!cancelled) setError("Backend not available");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-card border rounded-lg w-full max-w-4xl max-h-[90vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-card border-b px-6 py-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">User Details</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-accent">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {loading && (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}
          {error && (
            <div className="text-sm text-destructive flex items-center gap-2">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          )}
          {detail && <UserDetailContent detail={detail} />}
        </div>
      </div>
    </div>
  );
}

function UserDetailContent({ detail }: { detail: UserDetail }) {
  const u = detail.user;
  const t = detail.totals;
  const trendPoints = detail.cost_trend_30d.map((d) => d.cost_usd);

  return (
    <>
      {/* Header */}
      <div className="flex items-start gap-4">
        {u.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={u.avatar_url}
            alt={u.login || u.name}
            className="h-16 w-16 rounded-full"
          />
        ) : (
          <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center text-2xl font-bold">
            {(u.name || u.email || "?").slice(0, 1).toUpperCase()}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="text-xl font-bold">{u.name || u.login || "—"}</div>
          <div className="text-sm text-muted-foreground">{u.email}</div>
          {u.login && <div className="text-xs text-muted-foreground">@{u.login}</div>}
          <div className="text-xs text-muted-foreground mt-1">
            {u.role} · joined {formatDate(u.created_at)} · {u.login_count} logins
          </div>
        </div>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="border rounded p-3">
          <div className="text-xs text-muted-foreground">Total spent</div>
          <div className="text-lg font-bold">{formatUsd(t.total_cost_usd)}</div>
        </div>
        <div className="border rounded p-3">
          <div className="text-xs text-muted-foreground">Tool calls</div>
          <div className="text-lg font-bold">{t.tool_calls_total.toLocaleString()}</div>
          <div className="text-xs text-muted-foreground">
            {t.tool_calls_mcp} MCP · {t.tool_calls_cli} CLI
          </div>
        </div>
        <div className="border rounded p-3">
          <div className="text-xs text-muted-foreground">Plans</div>
          <div className="text-lg font-bold">{t.plan_count}</div>
        </div>
        <div className="border rounded p-3">
          <div className="text-xs text-muted-foreground">Last active</div>
          <div className="text-lg font-bold">{formatDate(u.last_active_at)}</div>
        </div>
      </div>

      {/* 30-day cost trend */}
      <div>
        <div className="text-xs uppercase text-muted-foreground font-medium mb-2 flex items-center gap-2">
          <TrendingUp className="h-3 w-3" />
          Cost (last 30 days)
        </div>
        {trendPoints.length === 0 ? (
          <div className="text-xs text-muted-foreground">No activity in last 30 days</div>
        ) : (
          <Sparkline points={trendPoints} />
        )}
      </div>

      {/* Per-agent breakdown */}
      <div>
        <div className="text-xs uppercase text-muted-foreground font-medium mb-2">
          Agent Usage
        </div>
        {detail.per_agent.length === 0 ? (
          <div className="text-xs text-muted-foreground">No agent activity yet</div>
        ) : (
          <div className="space-y-1">
            {detail.per_agent.map((a) => (
              <div key={a.agent} className="flex items-center justify-between text-sm py-1 border-b last:border-0">
                <span className="font-medium">{a.agent}</span>
                <span className="text-muted-foreground tabular-nums text-xs">
                  {a.message_count} messages · {formatUsd(a.cost_usd)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Per-tool breakdown */}
      <div>
        <div className="text-xs uppercase text-muted-foreground font-medium mb-2">
          Tool Usage
        </div>
        {detail.per_tool.length === 0 ? (
          <div className="text-xs text-muted-foreground">No tool calls yet</div>
        ) : (
          <div className="space-y-1 max-h-48 overflow-auto">
            {detail.per_tool.map((tt, i) => (
              <div key={`${tt.tool}-${i}`} className="flex items-center justify-between text-xs py-1 border-b last:border-0">
                <span className="font-medium flex items-center gap-2">
                  {tt.kind === "cli" ? (
                    <Terminal className="h-3 w-3 text-orange-500" />
                  ) : (
                    <Wrench className="h-3 w-3 text-blue-500" />
                  )}
                  {tt.tool}
                  <span className="text-muted-foreground">via {tt.agent}</span>
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {tt.call_count}× · {tt.avg_duration_ms}ms avg
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Connected services */}
      <div>
        <div className="text-xs uppercase text-muted-foreground font-medium mb-2">
          Connected Services
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {detail.services.length === 0 && detail.github_app_installations.length === 0 && (
            <div className="text-xs text-muted-foreground col-span-2">No services connected</div>
          )}
          {detail.services.map((s, i) => (
            <div key={`${s.provider}-${i}`} className="border rounded p-2 text-xs">
              <div className="font-medium flex items-center gap-1.5">
                {s.provider === "gcp" ? (
                  <Cloud className="h-3 w-3 text-blue-500" />
                ) : s.provider === "github" ? (
                  <Github className="h-3 w-3" />
                ) : (
                  <Wrench className="h-3 w-3" />
                )}
                {s.provider.toUpperCase()}
                {s.is_active ? (
                  <span className="text-green-500">●</span>
                ) : (
                  <span className="text-muted-foreground">○</span>
                )}
              </div>
              {s.email && <div className="text-muted-foreground truncate">{s.email}</div>}
              {s.project_id && <div className="text-muted-foreground truncate">{s.project_id}</div>}
              <div className="text-muted-foreground">connected {formatDate(s.connected_at)}</div>
            </div>
          ))}
          {detail.github_app_installations.map((i) => (
            <div key={i.installation_id} className="border rounded p-2 text-xs">
              <div className="font-medium flex items-center gap-1.5">
                <Github className="h-3 w-3" />
                GitHub App
                {i.is_active ? (
                  <span className="text-green-500">●</span>
                ) : (
                  <span className="text-muted-foreground">○</span>
                )}
              </div>
              <div className="text-muted-foreground truncate">
                {i.account_type}: {i.account_login}
              </div>
              <div className="text-muted-foreground">installed {formatDate(i.installed_at)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent conversations */}
      <div>
        <div className="text-xs uppercase text-muted-foreground font-medium mb-2">
          Recent Conversations
        </div>
        {detail.recent_conversations.length === 0 ? (
          <div className="text-xs text-muted-foreground">No conversations yet</div>
        ) : (
          <div className="space-y-1 max-h-48 overflow-auto">
            {detail.recent_conversations.map((c) => (
              <div key={c.id} className="flex items-center justify-between text-xs py-1 border-b last:border-0">
                <span className="truncate flex-1 min-w-0">{c.title || "Untitled"}</span>
                <span className="text-muted-foreground tabular-nums ml-2 shrink-0">
                  {c.message_count}m · {formatUsd(c.cost_usd)} · {formatDate(c.updated_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent audit log */}
      <div>
        <div className="text-xs uppercase text-muted-foreground font-medium mb-2">
          Recent Tool Calls
        </div>
        {detail.recent_audit_log.length === 0 ? (
          <div className="text-xs text-muted-foreground">No tool calls yet</div>
        ) : (
          <div className="space-y-1 max-h-64 overflow-auto">
            {detail.recent_audit_log.map((a) => (
              <div key={a.id} className="text-xs py-1.5 border-b last:border-0">
                <div className="flex items-center justify-between">
                  <span className="font-medium">
                    {a.agent} → {a.tool}
                  </span>
                  <span className="text-muted-foreground">
                    {a.duration_ms}ms · {formatDate(a.created_at)}
                  </span>
                </div>
                {a.tool_input_preview && (
                  <div className="text-muted-foreground truncate font-mono text-[10px] mt-0.5">
                    {a.tool_input_preview}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

// ─── Billing dashboard ─────────────────────────────────────────────────────

function BillingDashboard() {
  const [data, setData] = useState<BillingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/admin/billing`, { headers: getAuthHeader() });
      if (!res.ok) {
        setError(`Failed to load billing data (HTTP ${res.status})`);
        return;
      }
      setData((await res.json()) as BillingData);
    } catch {
      setError("Backend not available");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="border rounded-lg p-6 bg-card flex items-start gap-3">
        <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
        <div>
          <div className="font-medium">Unable to load billing data</div>
          <div className="text-sm text-muted-foreground mt-1">{error || "Empty response"}</div>
        </div>
      </div>
    );
  }

  const t = data.totals;
  const trendMax = Math.max(...data.daily_trend_30d.map((d) => d.cost_usd), 0.0001);

  return (
    <div className="space-y-6">
      {/* Header with refresh */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <DollarSign className="h-5 w-5 text-green-500" />
            Cost & Billing
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Spend across every user, agent, and model — driven live from the messages table
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-accent"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Hero cards — spend windows */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard
          title="Today"
          value={formatUsd(t.today.cost_usd)}
          subtitle={`${t.today.message_count} msgs`}
          icon={DollarSign}
          color="text-green-500"
        />
        <StatCard
          title="Last 7 Days"
          value={formatUsd(t.last_7d.cost_usd)}
          subtitle={`${t.last_7d.message_count} msgs`}
          icon={DollarSign}
          color="text-green-500"
        />
        <StatCard
          title="Last 30 Days"
          value={formatUsd(t.last_30d.cost_usd)}
          subtitle={`${t.last_30d.message_count} msgs`}
          icon={DollarSign}
          color="text-green-500"
        />
        <StatCard
          title="Month-to-Date"
          value={formatUsd(t.mtd.cost_usd)}
          subtitle={`proj. ${formatUsd(data.projected_monthly_usd)} this month`}
          icon={TrendingUp}
          color="text-yellow-500"
        />
        <StatCard
          title="All Time"
          value={formatUsd(t.all_time.cost_usd)}
          subtitle={`${t.all_time.message_count.toLocaleString()} msgs total`}
          icon={DollarSign}
          color="text-primary"
        />
      </div>

      {/* Token totals */}
      <div className="border rounded-lg bg-card p-4">
        <div className="text-xs uppercase text-muted-foreground font-medium mb-2">
          Token Usage (all time)
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-muted-foreground">Input tokens</div>
            <div className="text-lg font-bold">
              {t.all_time.input_tokens.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Output tokens</div>
            <div className="text-lg font-bold">
              {t.all_time.output_tokens.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Total tokens</div>
            <div className="text-lg font-bold">
              {(t.all_time.input_tokens + t.all_time.output_tokens).toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Avg cost / msg</div>
            <div className="text-lg font-bold">
              {formatUsd(
                t.all_time.message_count > 0
                  ? t.all_time.cost_usd / t.all_time.message_count
                  : 0,
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Daily trend — bar chart */}
      <div className="border rounded-lg bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs uppercase text-muted-foreground font-medium">
            Daily Spend — Last 30 Days
          </div>
          <div className="text-xs text-muted-foreground">
            peak {formatUsd(trendMax)}
          </div>
        </div>
        {data.daily_trend_30d.length === 0 ? (
          <div className="text-xs text-muted-foreground py-6 text-center">
            No activity in the last 30 days
          </div>
        ) : (
          <div className="flex items-end gap-1 h-32">
            {data.daily_trend_30d.map((d) => {
              const h = (d.cost_usd / trendMax) * 100;
              return (
                <div
                  key={d.date}
                  className="flex-1 bg-primary/70 hover:bg-primary transition-colors rounded-t"
                  style={{ height: `${Math.max(h, 2)}%` }}
                  title={`${d.date}: ${formatUsd(d.cost_usd)} · ${d.message_count} msgs`}
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Per-agent breakdown */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b">
          <div className="text-xs uppercase text-muted-foreground font-medium">
            Spend by Agent
          </div>
        </div>
        {data.per_agent.length === 0 ? (
          <div className="text-xs text-muted-foreground p-4 text-center">No agent activity yet</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Agent</th>
                <th className="text-right px-4 py-2 font-medium">Calls</th>
                <th className="text-right px-4 py-2 font-medium">Input tok</th>
                <th className="text-right px-4 py-2 font-medium">Output tok</th>
                <th className="text-right px-4 py-2 font-medium">Avg / call</th>
                <th className="text-right px-4 py-2 font-medium">Total cost</th>
              </tr>
            </thead>
            <tbody>
              {data.per_agent.map((a) => (
                <tr key={a.agent} className="border-t">
                  <td className="px-4 py-2 font-medium">{a.agent}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{a.calls}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                    {a.input_tokens.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                    {a.output_tokens.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                    {formatUsd(a.avg_cost_usd)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums font-medium">
                    {formatUsd(a.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Per-model breakdown */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b">
          <div className="text-xs uppercase text-muted-foreground font-medium">Spend by Model</div>
        </div>
        {data.per_model.length === 0 ? (
          <div className="text-xs text-muted-foreground p-4 text-center">No model activity yet</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Model</th>
                <th className="text-right px-4 py-2 font-medium">Calls</th>
                <th className="text-right px-4 py-2 font-medium">Input tok</th>
                <th className="text-right px-4 py-2 font-medium">Output tok</th>
                <th className="text-right px-4 py-2 font-medium">Total cost</th>
              </tr>
            </thead>
            <tbody>
              {data.per_model.map((m) => (
                <tr key={m.model} className="border-t">
                  <td className="px-4 py-2 font-mono text-xs">{m.model}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{m.calls}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                    {m.input_tokens.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                    {m.output_tokens.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums font-medium">
                    {formatUsd(m.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Top users by spend */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b">
          <div className="text-xs uppercase text-muted-foreground font-medium">
            Top 10 Users by Spend
          </div>
        </div>
        {data.top_users.length === 0 ? (
          <div className="text-xs text-muted-foreground p-4 text-center">
            No user spend recorded yet
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-medium">User</th>
                <th className="text-right px-4 py-2 font-medium">Messages</th>
                <th className="text-right px-4 py-2 font-medium">Tokens</th>
                <th className="text-right px-4 py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.top_users.map((u, idx) => (
                <tr key={u.id} className="border-t">
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-muted-foreground text-xs w-4">#{idx + 1}</span>
                      {u.avatar_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={u.avatar_url} alt={u.name} className="h-6 w-6 rounded-full" />
                      ) : (
                        <div className="h-6 w-6 rounded-full bg-muted flex items-center justify-center text-[10px] font-medium">
                          {(u.name || u.email || "?").slice(0, 1).toUpperCase()}
                        </div>
                      )}
                      <div className="min-w-0">
                        <div className="font-medium truncate">{u.name || u.login || "—"}</div>
                        <div className="text-xs text-muted-foreground truncate">{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{u.message_count}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                    {(u.input_tokens + u.output_tokens).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums font-medium">
                    {formatUsd(u.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}


// ─── DB inspector ──────────────────────────────────────────────────────────

function DbInspector() {
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState<DbInspectSummary | null>(null);
  const [detail, setDetail] = useState<DbInspectDetail | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadSummary = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/admin/db/inspect`, { headers: getAuthHeader() });
      if (!res.ok) {
        setError(`Failed to load DB summary (HTTP ${res.status})`);
        return;
      }
      setSummary((await res.json()) as DbInspectSummary);
    } catch {
      setError("Backend not available");
    } finally {
      setLoading(false);
    }
  };

  const loadTable = async (table: string) => {
    setSelectedTable(table);
    setLoading(true);
    setError("");
    setDetail(null);
    try {
      const res = await fetch(
        `${API_URL}/admin/db/inspect?table=${encodeURIComponent(table)}&limit=20`,
        { headers: getAuthHeader() },
      );
      if (!res.ok) {
        setError(`Failed to load ${table} (HTTP ${res.status})`);
        return;
      }
      setDetail((await res.json()) as DbInspectDetail);
    } catch {
      setError("Backend not available");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && !summary) {
      loadSummary();
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="border rounded-lg bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-accent/30"
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
          <Database className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">Database Inspector</span>
          {summary && (
            <span className="text-xs text-muted-foreground">
              · {summary.total_tables} tables · {summary.total_rows.toLocaleString()} rows
            </span>
          )}
        </div>
        <span className="text-xs text-muted-foreground">
          {open ? "Click table to inspect" : "Click to expand"}
        </span>
      </button>

      {open && (
        <div className="border-t p-4 space-y-4">
          {loading && !detail && (
            <div className="flex justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
          {error && (
            <div className="text-xs text-destructive flex items-center gap-2">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          )}

          {summary && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              {summary.tables.map((t) => (
                <button
                  key={t.table}
                  onClick={() => loadTable(t.table)}
                  className={`text-left border rounded px-3 py-2 text-xs hover:bg-accent ${
                    selectedTable === t.table ? "border-primary bg-primary/5" : ""
                  }`}
                >
                  <div className="font-medium font-mono">{t.table}</div>
                  <div className="text-muted-foreground mt-0.5">
                    {t.error ? (
                      <span className="text-destructive">{t.error}</span>
                    ) : (
                      <>
                        {t.row_count?.toLocaleString() ?? 0} rows · {t.columns?.length ?? 0} cols
                      </>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}

          {detail && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold font-mono">{detail.table}</div>
                <div className="text-xs text-muted-foreground">
                  showing {detail.returned} of {detail.total_rows.toLocaleString()} rows · ordered by {detail.ordered_by}
                </div>
              </div>
              {detail.rows.length === 0 ? (
                <div className="text-xs text-muted-foreground">Table is empty.</div>
              ) : (
                <div className="overflow-auto max-h-96 border rounded">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 sticky top-0">
                      <tr>
                        {Object.keys(detail.rows[0]).map((col) => (
                          <th key={col} className="text-left px-2 py-1 font-medium font-mono">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {detail.rows.map((row, i) => (
                        <tr key={i} className="border-t hover:bg-accent/20">
                          {Object.values(row).map((v, j) => (
                            <td
                              key={j}
                              className="px-2 py-1 font-mono align-top max-w-xs truncate"
                              title={String(v ?? "")}
                            >
                              {v === null
                                ? <span className="text-muted-foreground italic">null</span>
                                : typeof v === "boolean"
                                ? String(v)
                                : String(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// ─── Main panel ────────────────────────────────────────────────────────────

export function AdminPanel() {
  const [data, setData] = useState<AdminUsersResponse | null>(null);
  const [activity, setActivity] = useState<PlatformActivity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AdminTab>("users");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [usersRes, activityRes] = await Promise.all([
        fetch(`${API_URL}/admin/users`, { headers: getAuthHeader() }),
        fetch(`${API_URL}/admin/activity`, { headers: getAuthHeader() }),
      ]);
      if (usersRes.status === 403) {
        setError("You don't have admin permissions to view this page.");
        return;
      }
      if (!usersRes.ok) {
        setError(`Failed to load users (HTTP ${usersRes.status})`);
        return;
      }
      setData((await usersRes.json()) as AdminUsersResponse);
      if (activityRes.ok) {
        setActivity((await activityRes.json()) as PlatformActivity);
      }
    } catch {
      setError("Backend not available");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleRoleChange = async (userId: string, newRole: string) => {
    setUpdatingId(userId);
    try {
      const res = await fetch(`${API_URL}/admin/users/${userId}/role`, {
        method: "PATCH",
        headers: getAuthHeader(),
        body: JSON.stringify({ role: newRole }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "Failed to update role");
        return;
      }
      await load();
    } finally {
      setUpdatingId(null);
    }
  };

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return data.users;
    return data.users.filter(
      (u) =>
        u.email?.toLowerCase().includes(q) ||
        u.name?.toLowerCase().includes(q) ||
        u.login?.toLowerCase().includes(q),
    );
  }, [data, search]);

  const activeCount = useMemo(
    () => (data ? data.users.filter((u) => u.last_active_at).length : 0),
    [data],
  );
  const totalMessages = useMemo(
    () => (data ? data.users.reduce((s, u) => s + u.message_count, 0) : 0),
    [data],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="border rounded-lg p-6 bg-card flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
          <div>
            <div className="font-medium">Unable to load admin panel</div>
            <div className="text-sm text-muted-foreground mt-1">{error}</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold flex items-center gap-2">
              <Shield className="h-6 w-6 text-primary" />
              Admin Panel
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              Monitor every user, their activity, and AI costs
            </p>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-accent"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 border-b">
          <button
            onClick={() => setActiveTab("users")}
            className={`px-4 py-2 text-sm font-medium transition-colors relative ${
              activeTab === "users"
                ? "text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <span className="flex items-center gap-2">
              <Users className="h-4 w-4" />
              Users & Activity
            </span>
            {activeTab === "users" && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("billing")}
            className={`px-4 py-2 text-sm font-medium transition-colors relative ${
              activeTab === "billing"
                ? "text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <span className="flex items-center gap-2">
              <DollarSign className="h-4 w-4" />
              Cost & Billing
            </span>
            {activeTab === "billing" && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />
            )}
          </button>
        </div>

        {activeTab === "billing" && <BillingDashboard />}

        {activeTab === "users" && (
          <>
        {/* Platform activity */}
        <PlatformActivityCard activity={activity} />

        {/* Summary cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            title="Total Users"
            value={String(data?.total_users ?? 0)}
            subtitle={`${activeCount} have activity`}
            icon={Users}
          />
          <StatCard
            title="Total Cost"
            value={formatUsd(data?.total_cost_usd ?? 0)}
            subtitle="Across all users"
            icon={DollarSign}
            color="text-green-500"
          />
          <StatCard
            title="Total Messages"
            value={totalMessages.toLocaleString()}
            subtitle="LLM exchanges"
            icon={MessageSquare}
            color="text-blue-500"
          />
          <StatCard
            title="Avg Cost / User"
            value={formatUsd(
              data && data.total_users > 0 ? data.total_cost_usd / data.total_users : 0,
            )}
            icon={DollarSign}
            color="text-yellow-500"
          />
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search by name, email, or GitHub login…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 border rounded-md bg-background text-sm"
          />
        </div>

        {/* Users table — click any row to drill in */}
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">User</th>
                  <th className="text-left px-4 py-3 font-medium">Role</th>
                  <th className="text-left px-4 py-3 font-medium">Primary Agent</th>
                  <th className="text-right px-4 py-3 font-medium">Logins</th>
                  <th className="text-right px-4 py-3 font-medium">Convos</th>
                  <th className="text-right px-4 py-3 font-medium">Messages</th>
                  <th className="text-right px-4 py-3 font-medium">Total Cost</th>
                  <th className="text-left px-4 py-3 font-medium">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-center py-8 text-muted-foreground">
                      No users match your search
                    </td>
                  </tr>
                )}
                {filtered.map((u) => (
                  <tr
                    key={u.id}
                    className="border-t hover:bg-accent/30 cursor-pointer"
                    onClick={() => setSelectedUserId(u.id)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        {u.avatar_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={u.avatar_url}
                            alt={u.login || u.name}
                            className="h-8 w-8 rounded-full"
                          />
                        ) : (
                          <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center text-xs font-medium">
                            {(u.name || u.email || "?").slice(0, 1).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0">
                          <div className="font-medium truncate">{u.name || u.login || "—"}</div>
                          <div className="text-xs text-muted-foreground truncate">
                            {u.login ? `@${u.login}` : u.email}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <select
                        value={u.role}
                        disabled={updatingId === u.id}
                        onChange={(e) => handleRoleChange(u.id, e.target.value)}
                        className="text-xs border rounded px-2 py-1 bg-background disabled:opacity-50"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {u.primary_agent || "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{u.login_count}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{u.conversation_count}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{u.message_count}</td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium">
                      {formatUsd(u.total_cost_usd)}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {formatDate(u.last_active_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2 text-xs text-muted-foreground border-t">
            Click any row for full activity drill-down
          </div>
        </div>

        {/* DB inspector — collapsed by default, browse Cloud SQL data */}
        <DbInspector />
          </>
        )}
      </div>

      {selectedUserId && (
        <UserDetailModal userId={selectedUserId} onClose={() => setSelectedUserId(null)} />
      )}
    </div>
  );
}
