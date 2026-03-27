"use client";

import { useState, useEffect } from "react";
import {
  BarChart3,
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  AlertCircle,
  User,
  Zap,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getAuthHeader(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
  return { Authorization: `Bearer ${token || ""}`, "Content-Type": "application/json" };
}

interface SprintItem {
  id: string;
  title: string;
  type: string;
  status: string;
  priority: string;
  assignee: string;
  points: number;
}

interface Sprint {
  id: string;
  name: string;
  status: string;
  start_date: string;
  end_date: string;
  completed_points: number;
  total_points: number;
}

const STATUS_CONFIG: Record<string, { icon: typeof Circle; color: string; bg: string }> = {
  "To Do": { icon: Circle, color: "text-muted-foreground", bg: "bg-muted" },
  "In Progress": { icon: Clock, color: "text-blue-500", bg: "bg-blue-500/10" },
  "In Review": { icon: Zap, color: "text-yellow-500", bg: "bg-yellow-500/10" },
  "Done": { icon: CheckCircle2, color: "text-green-500", bg: "bg-green-500/10" },
  "Blocked": { icon: AlertCircle, color: "text-red-500", bg: "bg-red-500/10" },
};

const PRIORITY_COLORS: Record<string, string> = {
  Critical: "text-red-500 bg-red-500/10",
  High: "text-orange-500 bg-orange-500/10",
  Medium: "text-yellow-500 bg-yellow-500/10",
  Low: "text-green-500 bg-green-500/10",
  None: "text-muted-foreground bg-muted",
};

export function SprintPanel() {
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sprint, setSprint] = useState<Sprint | null>(null);
  const [items, setItems] = useState<SprintItem[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    // Check Zoho status
    fetch(`${API_URL}/auth/zoho/status`, { headers: getAuthHeader() })
      .then((r) => r.ok ? r.json() : { connected: false })
      .then((data) => {
        setConnected(data.connected);
        if (data.connected) {
          loadSprint();
        } else {
          setLoading(false);
        }
      })
      .catch(() => setLoading(false));
  }, []);

  const loadSprint = async () => {
    try {
      const res = await fetch(`${API_URL}/auth/zoho/sprints/active`, { headers: getAuthHeader() });
      if (res.ok) {
        const data = await res.json();
        setSprint(data.sprint || null);
        setItems(data.items || []);
        setSummary(data.summary || {});
      } else {
        const err = await res.json();
        setError(err.detail || "Failed to load sprint");
      }
    } catch (e) {
      setError("Failed to connect to Zoho Sprints");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!connected) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-4 p-6">
        <BarChart3 className="h-12 w-12 opacity-30" />
        <h2 className="text-lg font-semibold">Zoho Sprints</h2>
        <p className="text-sm text-center max-w-md">
          Connect your Zoho Sprints account in Settings to see sprint boards, tasks, and progress here.
        </p>
      </div>
    );
  }

  const totalItems = items.length;
  const doneItems = items.filter((i) => i.status === "Done").length;
  const progressPercent = totalItems > 0 ? Math.round((doneItems / totalItems) * 100) : 0;

  // Group items by status
  const columns: Record<string, SprintItem[]> = {};
  for (const item of items) {
    const status = item.status || "Unknown";
    if (!columns[status]) columns[status] = [];
    columns[status].push(item);
  }

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Sprint header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-primary" />
            {sprint?.name || "Sprint Board"}
          </h2>
          {sprint && (
            <p className="text-sm text-muted-foreground mt-1">
              {sprint.start_date} — {sprint.end_date}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-2xl font-bold">{progressPercent}%</p>
            <p className="text-xs text-muted-foreground">{doneItems}/{totalItems} items done</p>
          </div>
          <div className="w-24 h-24 relative">
            <svg className="w-24 h-24 -rotate-90" viewBox="0 0 36 36">
              <path
                className="text-muted"
                stroke="currentColor"
                strokeWidth="3"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              <path
                className="text-primary"
                stroke="currentColor"
                strokeWidth="3"
                fill="none"
                strokeDasharray={`${progressPercent}, 100`}
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
            </svg>
          </div>
        </div>
      </div>

      {/* Status summary bar */}
      <div className="flex gap-3 mb-6">
        {Object.entries(summary).map(([status, count]) => {
          const cfg = STATUS_CONFIG[status] || STATUS_CONFIG["To Do"];
          const StatusIcon = cfg.icon;
          return (
            <div key={status} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs ${cfg.bg} ${cfg.color}`}>
              <StatusIcon className="h-3 w-3" />
              {status}: {count}
            </div>
          );
        })}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 text-red-400 text-xs rounded-lg flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* Kanban-style columns */}
      <div className="flex gap-4 overflow-x-auto pb-4">
        {Object.entries(columns).map(([status, statusItems]) => {
          const cfg = STATUS_CONFIG[status] || STATUS_CONFIG["To Do"];
          const StatusIcon = cfg.icon;
          return (
            <div key={status} className="min-w-[280px] flex-1">
              <div className={`flex items-center gap-2 px-3 py-2 rounded-t-lg border border-b-0 ${cfg.bg}`}>
                <StatusIcon className={`h-3.5 w-3.5 ${cfg.color}`} />
                <span className={`text-xs font-medium ${cfg.color}`}>{status}</span>
                <span className="text-xs text-muted-foreground ml-auto">{statusItems.length}</span>
              </div>
              <div className="border rounded-b-lg p-2 space-y-2 min-h-[200px] bg-muted/10">
                {statusItems.map((item) => (
                  <div key={item.id} className="border rounded-md p-3 bg-card hover:border-primary/30 transition-colors">
                    <p className="text-xs font-medium mb-2">{item.title}</p>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${PRIORITY_COLORS[item.priority] || PRIORITY_COLORS.None}`}>
                          {item.priority}
                        </span>
                        {item.points > 0 && (
                          <span className="text-[10px] text-muted-foreground">{item.points}pt</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                        <User className="h-3 w-3" />
                        {item.assignee}
                      </div>
                    </div>
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
