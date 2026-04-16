"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Shield,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Target,
  Upload,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Loader2,
  ScanLine,
  Activity,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getAuthHeader(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token || "dev_local"}`,
  };
}

interface SecuritySummary {
  total_findings: number;
  open_findings: number;
  resolved_findings: number;
  severity: { critical: number; high: number; medium: number; low: number };
  health_score: number;
  mttr_days: number;
  targets_scanned: number;
  latest_scan: { tool: string; target: string; scanned_at: string } | null;
}

interface Finding {
  id: string;
  title: string;
  severity: string;
  cvss_score: number;
  tool: string;
  target: string;
  affected_asset: string;
  status: string;
  discovered_at: string;
  remediation_notes?: string;
  details?: Record<string, unknown>;
}

interface ToolBreakdown {
  tool: string;
  total: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

// ─── Health Score Gauge ───────────────────────────────────────────────

function HealthGauge({ score }: { score: number }) {
  const color =
    score >= 80 ? "text-green-400" : score >= 60 ? "text-yellow-400" : score >= 40 ? "text-orange-400" : "text-red-400";
  const bgColor =
    score >= 80
      ? "from-green-500/20 to-green-500/5"
      : score >= 60
        ? "from-yellow-500/20 to-yellow-500/5"
        : score >= 40
          ? "from-orange-500/20 to-orange-500/5"
          : "from-red-500/20 to-red-500/5";

  return (
    <div className={`rounded-xl border p-6 bg-gradient-to-br ${bgColor}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Security Health Score</p>
          <p className={`text-4xl font-bold mt-1 ${color}`}>{score.toFixed(0)}</p>
          <p className="text-xs text-muted-foreground mt-1">out of 100</p>
        </div>
        <Shield className={`h-12 w-12 ${color} opacity-50`} />
      </div>
    </div>
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  icon: Icon,
  color = "text-foreground",
}: {
  label: string;
  value: string | number;
  icon: typeof Shield;
  color?: string;
}) {
  return (
    <div className="rounded-xl border p-4 bg-card">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">{label}</p>
          <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
        </div>
        <Icon className={`h-8 w-8 opacity-30 ${color}`} />
      </div>
    </div>
  );
}

// ─── Severity Badge ───────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const styles: Record<string, string> = {
    CRITICAL: "bg-red-500/10 text-red-400 border-red-500/30",
    HIGH: "bg-orange-500/10 text-orange-400 border-orange-500/30",
    MEDIUM: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
    LOW: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  };
  return (
    <span className={`px-2 py-0.5 text-[10px] font-semibold rounded-full border ${styles[severity] || styles.LOW}`}>
      {severity}
    </span>
  );
}

// ─── Findings Table ───────────────────────────────────────────────────

function FindingsTable({ findings }: { findings: Finding[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (findings.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground text-sm">
        No findings yet. Run a security scan from the AI Chat to get started.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="pb-2 pr-2 w-6"></th>
            <th className="pb-2 pr-4">Severity</th>
            <th className="pb-2 pr-4">Finding</th>
            <th className="pb-2 pr-4">Tool</th>
            <th className="pb-2 pr-4">Target</th>
            <th className="pb-2 pr-4">CVSS</th>
            <th className="pb-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((f) => (
            <>
              <tr
                key={f.id}
                className="border-b border-border/50 hover:bg-muted/30 cursor-pointer transition-colors"
                onClick={() => setExpandedId(expandedId === f.id ? null : f.id)}
              >
                <td className="py-2 pr-2">
                  {expandedId === f.id ? (
                    <ChevronDown className="h-3 w-3 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-3 w-3 text-muted-foreground" />
                  )}
                </td>
                <td className="py-2 pr-4">
                  <SeverityBadge severity={f.severity} />
                </td>
                <td className="py-2 pr-4 max-w-[300px] truncate font-medium">{f.title}</td>
                <td className="py-2 pr-4 text-muted-foreground">{f.tool}</td>
                <td className="py-2 pr-4 text-muted-foreground font-mono text-[10px]">{f.affected_asset}</td>
                <td className="py-2 pr-4">
                  <span className={f.cvss_score >= 7 ? "text-red-400 font-bold" : "text-muted-foreground"}>
                    {f.cvss_score.toFixed(1)}
                  </span>
                </td>
                <td className="py-2">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] ${
                      f.status === "open"
                        ? "bg-red-500/10 text-red-400"
                        : f.status === "resolved"
                          ? "bg-green-500/10 text-green-400"
                          : "bg-yellow-500/10 text-yellow-400"
                    }`}
                  >
                    {f.status}
                  </span>
                </td>
              </tr>
              {expandedId === f.id && (
                <tr key={`${f.id}-detail`}>
                  <td colSpan={7} className="px-4 py-3 bg-muted/20">
                    <div className="space-y-2 text-xs">
                      {f.remediation_notes && (
                        <div>
                          <span className="font-semibold text-foreground">Remediation: </span>
                          <span className="text-muted-foreground">{f.remediation_notes}</span>
                        </div>
                      )}
                      {f.details && (
                        <div>
                          <span className="font-semibold text-foreground">Details: </span>
                          <pre className="mt-1 p-2 rounded bg-muted text-[10px] overflow-x-auto">
                            {JSON.stringify(f.details, null, 2)}
                          </pre>
                        </div>
                      )}
                      <div className="text-muted-foreground/60">
                        Discovered: {new Date(f.discovered_at).toLocaleString()}
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Tool Breakdown Table ─────────────────────────────────────────────

function ToolBreakdownTable({ data }: { data: ToolBreakdown[] }) {
  if (data.length === 0) return null;
  return (
    <div className="rounded-xl border bg-card p-4">
      <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <ScanLine className="h-4 w-4 text-primary" />
        Findings by Scanner
      </h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="pb-2">Tool</th>
            <th className="pb-2 text-center">Critical</th>
            <th className="pb-2 text-center">High</th>
            <th className="pb-2 text-center">Medium</th>
            <th className="pb-2 text-center">Low</th>
            <th className="pb-2 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {data.map((t) => (
            <tr key={t.tool} className="border-b border-border/50">
              <td className="py-2 font-medium">{t.tool}</td>
              <td className="py-2 text-center text-red-400 font-bold">{t.critical || "-"}</td>
              <td className="py-2 text-center text-orange-400">{t.high || "-"}</td>
              <td className="py-2 text-center text-yellow-400">{t.medium || "-"}</td>
              <td className="py-2 text-center text-blue-400">{t.low || "-"}</td>
              <td className="py-2 text-right font-semibold">{t.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Severity Bar ─────────────────────────────────────────────────────

function SeverityBar({ severity }: { severity: SecuritySummary["severity"] }) {
  const total = severity.critical + severity.high + severity.medium + severity.low;
  if (total === 0) return <div className="text-xs text-muted-foreground">No findings</div>;

  const pct = (n: number) => `${((n / total) * 100).toFixed(0)}%`;

  return (
    <div className="space-y-2">
      <div className="flex h-3 rounded-full overflow-hidden bg-muted">
        {severity.critical > 0 && (
          <div className="bg-red-500 transition-all" style={{ width: pct(severity.critical) }} />
        )}
        {severity.high > 0 && (
          <div className="bg-orange-500 transition-all" style={{ width: pct(severity.high) }} />
        )}
        {severity.medium > 0 && (
          <div className="bg-yellow-500 transition-all" style={{ width: pct(severity.medium) }} />
        )}
        {severity.low > 0 && (
          <div className="bg-blue-500 transition-all" style={{ width: pct(severity.low) }} />
        )}
      </div>
      <div className="flex gap-4 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-red-500" />
          Critical: {severity.critical}
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-orange-500" />
          High: {severity.high}
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-yellow-500" />
          Medium: {severity.medium}
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-blue-500" />
          Low: {severity.low}
        </span>
      </div>
    </div>
  );
}

// ─── Upload Modal ─────────────────────────────────────────────────────

function UploadModal({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("project", "default");
      form.append("scan_type", "web");

      const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
      const res = await fetch(`${API_URL}/security/pentest/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token || "dev_local"}` },
        body: form,
      });
      const data = await res.json();
      setResult(`Uploaded: ${data.finding_count} findings ingested`);
      onUploaded();
    } catch {
      setResult("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-card border rounded-xl p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold">Upload Pentest Report</h3>
        <p className="text-xs text-muted-foreground">
          Upload a JSON or CSV file containing security findings.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".json,.csv"
          className="w-full text-xs file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-primary file:text-primary-foreground file:cursor-pointer"
        />
        {result && <p className="text-xs text-green-400">{result}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 text-xs rounded-md border hover:bg-muted">
            Cancel
          </button>
          <button
            onClick={handleUpload}
            disabled={uploading}
            className="px-3 py-1.5 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 flex items-center gap-1.5"
          >
            {uploading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
            Upload
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Panel ───────────────────────────────────────────────────────

export function SecurityPanel() {
  const [summary, setSummary] = useState<SecuritySummary | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [toolBreakdown, setToolBreakdown] = useState<ToolBreakdown[]>([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [filter, setFilter] = useState<string>("all");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const headers = getAuthHeader();

      const [sumRes, findRes, toolRes] = await Promise.all([
        fetch(`${API_URL}/security/summary`, { headers }),
        fetch(`${API_URL}/security/findings?limit=50${filter !== "all" ? `&severity=${filter}` : ""}`, { headers }),
        fetch(`${API_URL}/security/tools`, { headers }),
      ]);

      if (sumRes.ok) setSummary(await sumRes.json());
      if (findRes.ok) setFindings(await findRes.json());
      if (toolRes.ok) setToolBreakdown(await toolRes.json());
    } catch (e) {
      console.error("Failed to fetch security data", e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading && !summary) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            Security & Compliance
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Penetration testing findings powered by Kali Linux
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowUpload(true)}
            className="px-3 py-1.5 text-xs rounded-md border hover:bg-muted flex items-center gap-1.5 transition-colors"
          >
            <Upload className="h-3 w-3" />
            Upload Report
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="px-3 py-1.5 text-xs rounded-md border hover:bg-muted flex items-center gap-1.5 transition-colors"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <HealthGauge score={summary?.health_score ?? 100} />
        <KpiCard
          label="Critical Findings"
          value={summary?.severity.critical ?? 0}
          icon={AlertTriangle}
          color={summary?.severity.critical ? "text-red-400" : "text-muted-foreground"}
        />
        <KpiCard
          label="Open Findings"
          value={summary?.open_findings ?? 0}
          icon={Target}
          color="text-orange-400"
        />
        <KpiCard
          label="MTTR (days)"
          value={summary?.mttr_days ?? 0}
          icon={Clock}
          color="text-yellow-400"
        />
        <KpiCard
          label="Targets Scanned"
          value={summary?.targets_scanned ?? 0}
          icon={ScanLine}
          color="text-blue-400"
        />
      </div>

      {/* Severity Distribution */}
      <div className="rounded-xl border bg-card p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          Severity Distribution
        </h3>
        <SeverityBar severity={summary?.severity ?? { critical: 0, high: 0, medium: 0, low: 0 }} />
      </div>

      {/* Tool Breakdown + Latest Scan */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ToolBreakdownTable data={toolBreakdown} />
        {summary?.latest_scan && (
          <div className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-400" />
              Latest Scan
            </h3>
            <div className="space-y-2 text-xs">
              <div>
                <span className="text-muted-foreground">Tool: </span>
                <span className="font-medium">{summary.latest_scan.tool}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Target: </span>
                <span className="font-mono">{summary.latest_scan.target}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Date: </span>
                <span>{new Date(summary.latest_scan.scanned_at).toLocaleString()}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Findings Table */}
      <div className="rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-orange-400" />
            Findings ({findings.length})
          </h3>
          <div className="flex gap-1">
            {["all", "CRITICAL", "HIGH", "MEDIUM", "LOW"].map((sev) => (
              <button
                key={sev}
                onClick={() => setFilter(sev)}
                className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
                  filter === sev
                    ? "bg-primary/10 border-primary/30 text-primary"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
              >
                {sev === "all" ? "All" : sev}
              </button>
            ))}
          </div>
        </div>
        <FindingsTable findings={findings} />
      </div>

      {/* Upload Modal */}
      {showUpload && <UploadModal onClose={() => setShowUpload(false)} onUploaded={fetchData} />}
    </div>
  );
}
