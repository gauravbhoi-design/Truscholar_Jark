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
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getAuthHeader(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
  return { Authorization: `Bearer ${token || ""}`, "Content-Type": "application/json" };
}

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

const ROLES = ["admin", "engineer", "viewer"] as const;

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

export function AdminPanel() {
  const [data, setData] = useState<AdminUsersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/admin/users`, { headers: getAuthHeader() });
      if (res.status === 403) {
        setError("You don't have admin permissions to view this page.");
        return;
      }
      if (!res.ok) {
        setError(`Failed to load users (HTTP ${res.status})`);
        return;
      }
      const json = (await res.json()) as AdminUsersResponse;
      setData(json);
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

        {/* Summary cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            title="Total Users"
            value={String(data?.total_users ?? 0)}
            subtitle={`${activeCount} active`}
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

        {/* Users table */}
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">User</th>
                  <th className="text-left px-4 py-3 font-medium">Role</th>
                  <th className="text-right px-4 py-3 font-medium">Conversations</th>
                  <th className="text-right px-4 py-3 font-medium">Messages</th>
                  <th className="text-right px-4 py-3 font-medium">Plans</th>
                  <th className="text-right px-4 py-3 font-medium">Installs</th>
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
                  <tr key={u.id} className="border-t hover:bg-accent/30">
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
                    <td className="px-4 py-3">
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
                    <td className="px-4 py-3 text-right tabular-nums">{u.conversation_count}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{u.message_count}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{u.plan_count}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{u.installation_count}</td>
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
        </div>
      </div>
    </div>
  );
}
