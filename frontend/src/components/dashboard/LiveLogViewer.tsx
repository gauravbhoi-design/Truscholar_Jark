"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Play,
  Square,
  Pause,
  Trash2,
  Filter,
  Radio,
  ChevronDown,
  AlertCircle,
  AlertTriangle,
  Info,
  Bug,
  Cloud,
  Loader2,
  X,
} from "lucide-react";
import { streamLiveLogs, getGcpStatus, type LogEntry } from "@/lib/api";

const SEVERITY_CONFIG: Record<string, { icon: typeof Info; color: string; bg: string }> = {
  DEFAULT: { icon: Info, color: "text-muted-foreground", bg: "" },
  DEBUG: { icon: Bug, color: "text-muted-foreground", bg: "" },
  INFO: { icon: Info, color: "text-blue-400", bg: "" },
  NOTICE: { icon: Info, color: "text-cyan-400", bg: "" },
  WARNING: { icon: AlertTriangle, color: "text-yellow-400", bg: "bg-yellow-500/5" },
  ERROR: { icon: AlertCircle, color: "text-red-400", bg: "bg-red-500/5" },
  CRITICAL: { icon: AlertCircle, color: "text-red-500", bg: "bg-red-500/10" },
  ALERT: { icon: AlertCircle, color: "text-red-600", bg: "bg-red-500/15" },
  EMERGENCY: { icon: AlertCircle, color: "text-red-600 font-bold", bg: "bg-red-500/20" },
};

function formatTimestamp(ts: string): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-US", { hour12: false, fractionalSecondDigits: 1 });
  } catch {
    return ts.split("T")[1]?.split(".")[0] || ts;
  }
}

function LogLine({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const sev = entry.severity || "DEFAULT";
  const cfg = SEVERITY_CONFIG[sev] || SEVERITY_CONFIG.DEFAULT;
  const SevIcon = cfg.icon;

  return (
    <div
      className={`flex items-start gap-2 px-3 py-1 font-mono text-xs hover:bg-muted/30 cursor-pointer transition-colors ${cfg.bg}`}
      onClick={() => setExpanded(!expanded)}
    >
      <span className="text-muted-foreground/50 w-20 shrink-0 select-none">
        {formatTimestamp(entry.timestamp || "")}
      </span>
      <span className={`w-16 shrink-0 flex items-center gap-1 ${cfg.color}`}>
        <SevIcon className="h-3 w-3" />
        <span className="text-[10px]">{sev}</span>
      </span>
      <span className="text-muted-foreground/60 w-28 shrink-0 truncate text-[10px]">
        {entry.resource_type || ""}
      </span>
      <span className="flex-1 text-foreground break-all whitespace-pre-wrap">
        {expanded ? entry.message : (entry.message || "").slice(0, 200)}
        {!expanded && (entry.message || "").length > 200 && (
          <span className="text-muted-foreground"> ...</span>
        )}
      </span>
    </div>
  );
}

export function LiveLogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [gcpProject, setGcpProject] = useState<string>("");

  // Filters
  const [severity, setSeverity] = useState("DEFAULT");
  const [resourceType, setResourceType] = useState("");
  const [serviceName, setServiceName] = useState("");
  const [customFilter, setCustomFilter] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const controllerRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(false);

  // Keep pausedRef in sync
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, paused]);

  // Load GCP status
  useEffect(() => {
    getGcpStatus().then((status) => {
      setConnected(status.connected);
      setGcpProject(status.project_id || "");
    });
  }, []);

  const startStreaming = useCallback(() => {
    setError(null);
    setStreaming(true);
    setPaused(false);

    const controller = streamLiveLogs(
      {
        project_id: gcpProject || undefined,
        resource_type: resourceType || undefined,
        service_name: serviceName || undefined,
        severity: severity !== "DEFAULT" ? severity : undefined,
        filter: customFilter || undefined,
        duration: 120,
      },
      (entry) => {
        if (!pausedRef.current) {
          setLogs((prev) => {
            const next = [...prev, entry];
            // Keep max 500 entries to prevent memory issues
            return next.length > 500 ? next.slice(-500) : next;
          });
        }
      },
      (err) => {
        setError(err);
        setStreaming(false);
      },
      () => {
        setStreaming(false);
      },
    );

    controllerRef.current = controller;
  }, [gcpProject, severity, resourceType, serviceName, customFilter]);

  const stopStreaming = () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setStreaming(false);
  };

  const clearLogs = () => {
    setLogs([]);
  };

  const logCounts = {
    total: logs.filter((l) => l.event === "log").length,
    errors: logs.filter((l) => l.event === "log" && (l.severity === "ERROR" || l.severity === "CRITICAL")).length,
    warnings: logs.filter((l) => l.event === "log" && l.severity === "WARNING").length,
  };

  if (!connected) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-4 p-6">
        <Cloud className="h-12 w-12 opacity-30" />
        <h2 className="text-lg font-semibold">Live Log Streaming</h2>
        <p className="text-sm text-center max-w-md">
          Connect your GCP project in Settings to stream live logs from Cloud Logging.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="border-b px-4 py-2 flex items-center gap-2 shrink-0">
        {/* Stream controls */}
        {!streaming ? (
          <button
            onClick={startStreaming}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-green-600 text-white hover:bg-green-700 transition-colors"
          >
            <Play className="h-3 w-3" />
            Start
          </button>
        ) : (
          <>
            <button
              onClick={() => setPaused(!paused)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors ${
                paused
                  ? "bg-yellow-500/10 text-yellow-500 border border-yellow-500/30"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              {paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
              {paused ? "Resume" : "Pause"}
            </button>
            <button
              onClick={stopStreaming}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-red-500/10 text-red-500 border border-red-500/30 hover:bg-red-500/20 transition-colors"
            >
              <Square className="h-3 w-3" />
              Stop
            </button>
          </>
        )}

        <button
          onClick={clearLogs}
          className="flex items-center gap-1.5 px-2 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <Trash2 className="h-3 w-3" />
        </button>

        <div className="w-px h-5 bg-border mx-1" />

        {/* Filter toggle */}
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 px-2 py-1.5 rounded-md text-xs transition-colors ${
            showFilters ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Filter className="h-3 w-3" />
          Filters
          <ChevronDown className={`h-3 w-3 transition-transform ${showFilters ? "rotate-180" : ""}`} />
        </button>

        {/* Status */}
        <div className="ml-auto flex items-center gap-3 text-xs">
          {streaming && (
            <span className="flex items-center gap-1.5 text-green-500">
              <Radio className="h-3 w-3 animate-pulse" />
              LIVE
            </span>
          )}
          <span className="text-muted-foreground">{logCounts.total} logs</span>
          {logCounts.errors > 0 && (
            <span className="text-red-400">{logCounts.errors} errors</span>
          )}
          {logCounts.warnings > 0 && (
            <span className="text-yellow-400">{logCounts.warnings} warnings</span>
          )}
          <span className="text-muted-foreground/50 font-mono text-[10px]">{gcpProject}</span>
        </div>
      </div>

      {/* Filters panel */}
      {showFilters && (
        <div className="border-b px-4 py-3 bg-muted/20 flex flex-wrap gap-3 shrink-0">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-muted-foreground font-medium">Severity</label>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="text-xs px-2 py-1 rounded border bg-background"
            >
              <option value="DEFAULT">All</option>
              <option value="DEBUG">DEBUG+</option>
              <option value="INFO">INFO+</option>
              <option value="WARNING">WARNING+</option>
              <option value="ERROR">ERROR+</option>
              <option value="CRITICAL">CRITICAL+</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-muted-foreground font-medium">Resource Type</label>
            <select
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className="text-xs px-2 py-1 rounded border bg-background"
            >
              <option value="">All</option>
              <option value="cloud_run_revision">Cloud Run</option>
              <option value="gke_cluster">GKE Cluster</option>
              <option value="cloud_function">Cloud Function</option>
              <option value="gce_instance">Compute Engine</option>
              <option value="gae_app">App Engine</option>
              <option value="cloud_build">Cloud Build</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-muted-foreground font-medium">Service Name</label>
            <input
              type="text"
              value={serviceName}
              onChange={(e) => setServiceName(e.target.value)}
              placeholder="e.g. api-service"
              className="text-xs px-2 py-1 rounded border bg-background w-32"
            />
          </div>
          <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
            <label className="text-[10px] text-muted-foreground font-medium">Custom Filter</label>
            <input
              type="text"
              value={customFilter}
              onChange={(e) => setCustomFilter(e.target.value)}
              placeholder='e.g. textPayload:"timeout"'
              className="text-xs px-2 py-1 rounded border bg-background"
            />
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-red-500/10 text-red-400 text-xs border-b shrink-0">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)}>
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* Log entries */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto bg-background font-mono">
        {logs.length === 0 && !streaming && (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-3">
            <Radio className="h-8 w-8 opacity-30" />
            <p className="text-sm">Click Start to stream live logs</p>
            <p className="text-xs text-muted-foreground/50">
              Logs from <span className="font-semibold">{gcpProject}</span> will appear here in real-time
            </p>
          </div>
        )}

        {logs.length === 0 && streaming && (
          <div className="flex items-center justify-center h-full text-muted-foreground gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Waiting for log entries...</span>
          </div>
        )}

        {logs
          .filter((l) => l.event === "log" || l.event === "connected" || l.event === "info")
          .map((entry, i) => {
            if (entry.event === "connected") {
              return (
                <div key={i} className="px-3 py-1 text-xs text-green-500/60 border-b border-border/30">
                  Connected to {entry.project_id} {entry.filter ? `(filter: ${entry.filter})` : ""}
                </div>
              );
            }
            if (entry.event === "info") {
              return (
                <div key={i} className="px-3 py-1 text-xs text-blue-400/60 border-b border-border/30">
                  {entry.message}
                </div>
              );
            }
            return <LogLine key={entry.insert_id || i} entry={entry} />;
          })}

        {paused && (
          <div className="sticky bottom-0 flex items-center justify-center py-2 bg-yellow-500/10 text-yellow-500 text-xs">
            <Pause className="h-3 w-3 mr-1.5" />
            Paused — new logs are being buffered
          </div>
        )}
      </div>
    </div>
  );
}
