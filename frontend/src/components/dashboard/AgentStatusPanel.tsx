"use client";

import { useState, useEffect } from "react";
import { Activity, AlertCircle, Clock, Zap, CheckCircle } from "lucide-react";
import {
  subscribeAgentStatus,
  getAgentStatuses,
  type AgentStatus,
  type AgentStatusUpdate,
} from "@/lib/agent-events";

interface AgentInfo {
  name: string;
  displayName: string;
  description: string;
  status: AgentStatus;
  tools: string[];
  detail: string | null;
  lastRun: number | null;
}

const DEFAULT_AGENTS: AgentInfo[] = [
  {
    name: "supervisor",
    displayName: "Supervisor Agent",
    description: "Routes queries to specialized agents, synthesizes results",
    status: "idle",
    tools: ["All agent outputs", "Memory MCP", "Priority ranking"],
    detail: null,
    lastRun: null,
  },
  {
    name: "cloud_debugger",
    displayName: "Cloud Debugger",
    description: "Analyzes AWS/GCP/Azure logs, resources, and deployment failures",
    status: "idle",
    tools: ["CloudWatch", "GCP Logging", "Azure Monitor"],
    detail: null,
    lastRun: null,
  },
  {
    name: "codebase_analyzer",
    displayName: "Codebase Analyzer",
    description: "Static analysis, vulnerability scanning, code quality",
    status: "idle",
    tools: ["GitHub MCP", "Semgrep MCP", "Filesystem MCP"],
    detail: null,
    lastRun: null,
  },
  {
    name: "commit_analyst",
    displayName: "Commit Analyst",
    description: "Analyzes git history, diffs, identifies regressions",
    status: "idle",
    tools: ["Git MCP", "GitHub MCP", "PyDriller"],
    detail: null,
    lastRun: null,
  },
  {
    name: "deployment_doctor",
    displayName: "Deployment Doctor",
    description: "Validates Docker, K8s, Terraform configs, CI/CD pipelines",
    status: "idle",
    tools: ["Docker MCP", "kubectl", "GitHub Actions API"],
    detail: null,
    lastRun: null,
  },
  {
    name: "performance",
    displayName: "Performance Agent",
    description: "Monitors metrics, identifies bottlenecks, optimization",
    status: "idle",
    tools: ["Prometheus", "Grafana", "Datadog MCP"],
    detail: null,
    lastRun: null,
  },
];

const statusConfig = {
  idle: { icon: Clock, color: "text-muted-foreground", bg: "bg-muted", label: "Idle", pulse: false },
  running: { icon: Zap, color: "text-yellow-500", bg: "bg-yellow-500/10", label: "Running", pulse: true },
  done: { icon: CheckCircle, color: "text-green-500", bg: "bg-green-500/10", label: "Done", pulse: false },
  error: { icon: AlertCircle, color: "text-destructive", bg: "bg-destructive/10", label: "Error", pulse: false },
};

function formatTimestamp(ts: number | null): string {
  if (!ts) return "";
  const seconds = Math.floor((Date.now() - ts) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}

export function AgentStatusPanel() {
  const [agents, setAgents] = useState<AgentInfo[]>(DEFAULT_AGENTS);
  const [, setTick] = useState(0);

  // Subscribe to live agent status events
  useEffect(() => {
    const unsubscribe = subscribeAgentStatus((update: AgentStatusUpdate) => {
      setAgents((prev) =>
        prev.map((agent) =>
          agent.name === update.agent
            ? {
                ...agent,
                status: update.status,
                detail: update.detail || null,
                lastRun: update.timestamp,
              }
            : agent,
        ),
      );
    });

    // Hydrate from current statuses on mount
    const current = getAgentStatuses();
    if (current.size > 0) {
      setAgents((prev) =>
        prev.map((agent) => {
          const update = current.get(agent.name);
          return update
            ? { ...agent, status: update.status, detail: update.detail || null, lastRun: update.timestamp }
            : agent;
        }),
      );
    }

    return unsubscribe;
  }, []);

  // Refresh "X ago" timestamps every 5 seconds
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className="flex items-center gap-2 mb-6">
        <Activity className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">Agent Status</h2>
        {agents.some((a) => a.status === "running") && (
          <span className="ml-auto flex items-center gap-1.5 text-xs text-yellow-500">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-yellow-500" />
            </span>
            Agents active
          </span>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {agents.map((agent) => {
          const cfg = statusConfig[agent.status];
          const StatusIcon = cfg.icon;

          return (
            <div
              key={agent.name}
              className={`border rounded-lg p-4 bg-card transition-all duration-300 ${
                agent.status === "running" ? "ring-1 ring-yellow-500/30" : ""
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <h3 className="font-medium text-sm">{agent.displayName}</h3>
                <span
                  className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.color}`}
                >
                  <StatusIcon className={`h-3 w-3 ${cfg.pulse ? "animate-pulse" : ""}`} />
                  {cfg.label}
                </span>
              </div>

              <p className="text-xs text-muted-foreground mb-2">{agent.description}</p>

              {/* Live detail */}
              {agent.detail && agent.status === "running" && (
                <p className="text-xs text-yellow-400 mb-2 truncate">{agent.detail}</p>
              )}

              {/* Last run timestamp */}
              {agent.lastRun && agent.status !== "running" && (
                <p className="text-[10px] text-muted-foreground/60 mb-2">
                  Last run: {formatTimestamp(agent.lastRun)}
                </p>
              )}

              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">MCP Tools:</p>
                <div className="flex flex-wrap gap-1">
                  {agent.tools.map((tool) => (
                    <span
                      key={tool}
                      className="px-1.5 py-0.5 text-[10px] rounded bg-secondary text-secondary-foreground"
                    >
                      {tool}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
