"use client";

import { useState, useEffect } from "react";
import {
  Settings,
  Cloud,
  Github,
  Shield,
  CheckCircle2,
  XCircle,
  Loader2,
  ExternalLink,
  Unplug,
  Lock,
  Eye,
  EyeOff,
  GitBranch,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function getAuthHeader(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token || ""}`,
  };
}

interface GCPStatus {
  connected: boolean;
  email?: string;
  project_id?: string;
  scopes?: string;
  connected_at?: string;
  last_used_at?: string;
}

interface GCPProject {
  id: string;
  name: string;
  number?: string;
}

function GCPConnectionCard() {
  const [status, setStatus] = useState<GCPStatus | null>(null);
  const [projects, setProjects] = useState<GCPProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [selectingProject, setSelectingProject] = useState(false);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_URL}/auth/gcp/status`, { headers: getAuthHeader() });
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        // If connected, also fetch projects
        if (data.connected) {
          fetchProjects();
        }
      }
    } catch {
      // Backend may not be running
    } finally {
      setLoading(false);
    }
  };

  const fetchProjects = async () => {
    setLoadingProjects(true);
    try {
      const res = await fetch(`${API_URL}/auth/gcp/projects`, { headers: getAuthHeader() });
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects || []);
      }
    } catch {
      // ignore
    } finally {
      setLoadingProjects(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const res = await fetch(`${API_URL}/auth/gcp/login`, { headers: getAuthHeader() });
      if (res.ok) {
        const data = await res.json();
        window.location.href = data.authorize_url;
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to start GCP connection");
      }
    } catch {
      alert("Backend not available. Please start the backend first.");
    } finally {
      setConnecting(false);
    }
  };

  const handleSelectProject = async (projectId: string) => {
    setSelectingProject(true);
    try {
      const res = await fetch(`${API_URL}/auth/gcp/select-project?project_id=${encodeURIComponent(projectId)}`, {
        method: "POST",
        headers: getAuthHeader(),
      });
      if (res.ok) {
        setStatus((prev) => prev ? { ...prev, project_id: projectId } : prev);
      }
    } catch {
      alert("Failed to update project");
    } finally {
      setSelectingProject(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("This will revoke access to your GCP project and delete all stored credentials. Continue?")) {
      return;
    }
    setDisconnecting(true);
    try {
      const res = await fetch(`${API_URL}/auth/gcp/disconnect`, {
        method: "POST",
        headers: getAuthHeader(),
      });
      if (res.ok) {
        setStatus({ connected: false });
        setProjects([]);
      }
    } catch {
      alert("Failed to disconnect");
    } finally {
      setDisconnecting(false);
    }
  };

  if (loading) {
    return (
      <div className="border rounded-lg p-6 bg-card flex items-center justify-center h-48">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b bg-muted/30">
        <Cloud className="h-5 w-5 text-blue-400" />
        <div>
          <h3 className="font-medium text-sm">Google Cloud Platform</h3>
          <p className="text-xs text-muted-foreground">Connect your GCP project for log analysis and monitoring</p>
        </div>
        {status?.connected ? (
          <span className="ml-auto flex items-center gap-1 text-xs text-green-500 bg-green-500/10 px-2 py-1 rounded-full">
            <CheckCircle2 className="h-3 w-3" /> Connected
          </span>
        ) : (
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground bg-muted px-2 py-1 rounded-full">
            <XCircle className="h-3 w-3" /> Not connected
          </span>
        )}
      </div>

      {/* Body */}
      <div className="p-4">
        {status?.connected ? (
          <div className="space-y-4">
            {/* Account info */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Google Account</p>
                <p className="font-medium">{status.email}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Active Project</p>
                <p className="font-mono text-xs bg-primary/10 text-primary px-2 py-1 rounded font-medium">
                  {status.project_id || "None selected"}
                </p>
              </div>
              {status.connected_at && (
                <div>
                  <p className="text-xs text-muted-foreground">Connected</p>
                  <p className="text-xs">{new Date(status.connected_at).toLocaleDateString()}</p>
                </div>
              )}
              {status.last_used_at && (
                <div>
                  <p className="text-xs text-muted-foreground">Last Used</p>
                  <p className="text-xs">{new Date(status.last_used_at).toLocaleDateString()}</p>
                </div>
              )}
            </div>

            {/* Project list */}
            <div className="border rounded-md overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 bg-muted/30 border-b">
                <p className="text-xs font-medium">Your GCP Projects</p>
                <button
                  onClick={fetchProjects}
                  disabled={loadingProjects}
                  className="text-[10px] text-primary hover:underline disabled:opacity-50"
                >
                  {loadingProjects ? "Loading..." : "Refresh"}
                </button>
              </div>

              {loadingProjects && projects.length === 0 ? (
                <div className="p-4 flex items-center justify-center">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              ) : projects.length === 0 ? (
                <div className="p-4 text-xs text-muted-foreground text-center">
                  No projects found. Make sure the Resource Manager API is enabled.
                </div>
              ) : (
                <div className="max-h-48 overflow-y-auto divide-y">
                  {projects.map((project) => {
                    const isSelected = status.project_id === project.id;
                    return (
                      <div
                        key={project.id}
                        className={`flex items-center justify-between px-3 py-2.5 text-sm hover:bg-muted/30 transition-colors ${
                          isSelected ? "bg-primary/5" : ""
                        }`}
                      >
                        <div className="min-w-0">
                          <p className={`font-medium text-xs truncate ${isSelected ? "text-primary" : ""}`}>
                            {project.name}
                          </p>
                          <p className="text-[10px] text-muted-foreground font-mono">{project.id}</p>
                        </div>
                        {isSelected ? (
                          <span className="shrink-0 flex items-center gap-1 text-[10px] text-green-500 bg-green-500/10 px-2 py-0.5 rounded-full">
                            <CheckCircle2 className="h-3 w-3" /> Active
                          </span>
                        ) : (
                          <button
                            onClick={() => handleSelectProject(project.id)}
                            disabled={selectingProject}
                            className="shrink-0 text-[10px] px-2 py-0.5 rounded border text-muted-foreground hover:text-primary hover:border-primary transition-colors disabled:opacity-50"
                          >
                            Select
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 disabled:opacity-50"
              >
                {disconnecting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Unplug className="h-3 w-3" />}
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Security info */}
            <div className="space-y-2">
              <div className="flex items-start gap-2 text-xs text-muted-foreground">
                <Shield className="h-3.5 w-3.5 text-green-500 mt-0.5 shrink-0" />
                <span><strong>Read-only access</strong> — we cannot modify or delete anything in your project</span>
              </div>
              <div className="flex items-start gap-2 text-xs text-muted-foreground">
                <Lock className="h-3.5 w-3.5 text-green-500 mt-0.5 shrink-0" />
                <span><strong>Encrypted storage</strong> — your tokens are encrypted with AES-256 at rest</span>
              </div>
              <div className="flex items-start gap-2 text-xs text-muted-foreground">
                <Unplug className="h-3.5 w-3.5 text-green-500 mt-0.5 shrink-0" />
                <span><strong>Disconnect anytime</strong> — one click removes all stored credentials</span>
              </div>
            </div>

            {/* Permissions */}
            <div className="border rounded-md p-3 bg-muted/20">
              <p className="text-xs font-medium mb-2">Permissions we request:</p>
              <div className="space-y-1 text-xs text-muted-foreground">
                <p>Read Cloud Logging (find errors and crashes)</p>
                <p>Read Cloud Monitoring (performance metrics)</p>
                <p>Read Compute Engine (VM/instance health)</p>
                <p>Read GKE (cluster and pod status)</p>
              </div>
            </div>

            <button
              onClick={handleConnect}
              disabled={connecting}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {connecting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Cloud className="h-4 w-4" />
              )}
              Connect with Google Cloud
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

interface GitHubStatus {
  connected: boolean;
  login?: string;
  email?: string;
  source?: string;
}

function GitHubConnectionCard() {
  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [showPat, setShowPat] = useState(false);
  const [pat, setPat] = useState("");
  const [savingPat, setSavingPat] = useState(false);
  const [patError, setPatError] = useState("");
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/auth/github/status`, { headers: getAuthHeader() })
      .then((r) => (r.ok ? r.json() : { connected: false }))
      .then(setStatus)
      .catch(() => setStatus({ connected: false }))
      .finally(() => setLoading(false));
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const res = await fetch(`${API_URL}/auth/github/connect`, { headers: getAuthHeader() });
      if (res.ok) {
        const data = await res.json();
        window.location.href = data.authorize_url;
      }
    } catch {
      alert("Backend not available");
    } finally {
      setConnecting(false);
    }
  };

  const handleSavePat = async () => {
    if (!pat.trim()) return;
    setSavingPat(true);
    setPatError("");
    try {
      const res = await fetch(`${API_URL}/auth/github/pat`, {
        method: "POST",
        headers: getAuthHeader(),
        body: JSON.stringify({ token: btoa(pat.trim()) }),
      });
      if (res.ok) {
        const data = await res.json();
        setStatus({
          connected: true,
          login: data.login,
          email: data.email,
          source: "pat",
        });
        setPat("");
        setShowPat(false);
      } else {
        const err = await res.json();
        setPatError(err.detail || "Failed to save token");
      }
    } catch {
      setPatError("Backend not available");
    } finally {
      setSavingPat(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("Disconnect GitHub? You won't be able to analyze repos until you reconnect.")) return;
    setDisconnecting(true);
    try {
      await fetch(`${API_URL}/auth/github/disconnect`, { method: "POST", headers: getAuthHeader() });
      setStatus({ connected: false });
    } finally {
      setDisconnecting(false);
    }
  };

  if (loading) {
    return (
      <div className="border rounded-lg p-6 bg-card flex items-center justify-center h-32">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const sourceLabel = status?.source === "jwt"
    ? "Signed in with GitHub"
    : status?.source === "pat"
    ? "Personal Access Token"
    : "Linked via OAuth";

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center gap-3 p-4 border-b bg-muted/30">
        <Github className="h-5 w-5" />
        <div>
          <h3 className="font-medium text-sm">GitHub</h3>
          <p className="text-xs text-muted-foreground">Connect GitHub for repo analysis, code review, and CI/CD</p>
        </div>
        {status?.connected ? (
          <span className="ml-auto flex items-center gap-1 text-xs text-green-500 bg-green-500/10 px-2 py-1 rounded-full">
            <CheckCircle2 className="h-3 w-3" /> Connected
          </span>
        ) : (
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground bg-muted px-2 py-1 rounded-full">
            <XCircle className="h-3 w-3" /> Not connected
          </span>
        )}
      </div>

      <div className="p-4">
        {status?.connected ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">GitHub Account</p>
                <p className="font-medium flex items-center gap-1.5">
                  <GitBranch className="h-3.5 w-3.5" />
                  {status.login}
                </p>
              </div>
              {status.email && (
                <div>
                  <p className="text-xs text-muted-foreground">Email</p>
                  <p className="text-xs">{status.email}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-muted-foreground">Auth Method</p>
                <p className="text-xs">{sourceLabel}</p>
              </div>
            </div>
            {status.source === "jwt" ? (
              <p className="text-xs text-muted-foreground">
                GitHub is your primary sign-in method. Use <strong>Sign Out</strong> to disconnect.
              </p>
            ) : (
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 disabled:opacity-50"
              >
                {disconnecting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Unplug className="h-3 w-3" />}
                Disconnect
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">
              Connect your GitHub account to enable repository analysis, CI/CD pipeline debugging, and code reviews.
            </p>

            {/* OAuth connect */}
            <button
              onClick={handleConnect}
              disabled={connecting}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-[#24292f] text-white text-sm font-medium hover:bg-[#32383f] disabled:opacity-50 transition-colors"
            >
              {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Github className="h-4 w-4" />}
              Connect with GitHub OAuth
            </button>

            {/* Divider */}
            <div className="flex items-center gap-3">
              <div className="flex-1 border-t" />
              <span className="text-[10px] text-muted-foreground uppercase">or</span>
              <div className="flex-1 border-t" />
            </div>

            {/* PAT input */}
            {!showPat ? (
              <button
                onClick={() => setShowPat(true)}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border text-sm font-medium text-muted-foreground hover:text-foreground hover:border-foreground/20 transition-colors"
              >
                <Lock className="h-4 w-4" />
                Use Personal Access Token
              </button>
            ) : (
              <div className="space-y-2 border rounded-lg p-3 bg-muted/20">
                <p className="text-[10px] text-muted-foreground">
                  Create a token at{" "}
                  <a
                    href="https://github.com/settings/tokens/new?scopes=repo,read:org,workflow,read:user,user:email&description=DevOps+Co-Pilot"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                  >
                    GitHub Settings
                  </a>
                  {" "}with scopes: <code className="text-[10px] bg-muted px-1 rounded">repo, read:org, workflow</code>
                </p>
                <div className="flex gap-2">
                  <div className="flex-1 relative">
                    <input
                      type={showToken ? "text" : "password"}
                      value={pat}
                      onChange={(e) => { setPat(e.target.value); setPatError(""); }}
                      placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                      className="w-full text-xs px-3 py-2 pr-8 rounded border bg-background font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                    <button
                      type="button"
                      onClick={() => setShowToken(!showToken)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showToken ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                  <button
                    onClick={handleSavePat}
                    disabled={!pat.trim() || savingPat}
                    className="px-3 py-2 rounded bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 disabled:opacity-50"
                  >
                    {savingPat ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                  </button>
                </div>
                {patError && (
                  <p className="text-xs text-destructive">{patError}</p>
                )}
                <div className="flex items-start gap-1.5 text-[10px] text-muted-foreground">
                  <Shield className="h-3 w-3 text-green-500 mt-0.5 shrink-0" />
                  <span>Your token is encrypted with AES-256-GCM before storage. It is never exposed in the UI.</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ZohoConnectionCard() {
  const [status, setStatus] = useState<{ connected: boolean; email?: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/auth/zoho/status`, { headers: getAuthHeader() })
      .then((r) => r.ok ? r.json() : { connected: false })
      .then(setStatus)
      .catch(() => setStatus({ connected: false }))
      .finally(() => setLoading(false));
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const res = await fetch(`${API_URL}/auth/zoho/login`, { headers: getAuthHeader() });
      if (res.ok) {
        const data = await res.json();
        window.location.href = data.authorize_url;
      } else {
        const err = await res.json();
        alert(err.detail || "Zoho OAuth not configured");
      }
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("Disconnect Zoho Sprints?")) return;
    await fetch(`${API_URL}/auth/zoho/disconnect`, { method: "POST", headers: getAuthHeader() });
    setStatus({ connected: false });
  };

  if (loading) {
    return (
      <div className="border rounded-lg p-6 bg-card flex items-center justify-center h-32">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center gap-3 p-4 border-b bg-muted/30">
        <svg className="h-5 w-5 text-orange-500" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" fill="none" />
        </svg>
        <div>
          <h3 className="font-medium text-sm">Zoho Sprints</h3>
          <p className="text-xs text-muted-foreground">Connect for sprint boards, task tracking, and team management</p>
        </div>
        {status?.connected ? (
          <span className="ml-auto flex items-center gap-1 text-xs text-green-500 bg-green-500/10 px-2 py-1 rounded-full">
            <CheckCircle2 className="h-3 w-3" /> Connected
          </span>
        ) : (
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground bg-muted px-2 py-1 rounded-full">
            <XCircle className="h-3 w-3" /> Not connected
          </span>
        )}
      </div>
      <div className="p-4">
        {status?.connected ? (
          <div className="space-y-3">
            {status.email && (
              <div>
                <p className="text-xs text-muted-foreground">Zoho Account</p>
                <p className="text-sm font-medium">{status.email}</p>
              </div>
            )}
            <button
              onClick={handleDisconnect}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10"
            >
              <Unplug className="h-3 w-3" /> Disconnect
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Connect Zoho Sprints to see sprint boards, tasks, and team progress in the dashboard.
            </p>
            <button
              onClick={handleConnect}
              disabled={connecting}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-orange-600 text-white text-sm font-medium hover:bg-orange-700 disabled:opacity-50 transition-colors"
            >
              {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Connect Zoho Sprints
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function SettingsPanel() {
  return (
    <div className="p-6 overflow-y-auto h-full max-w-3xl mx-auto">
      <div className="flex items-center gap-2 mb-6">
        <Settings className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">Settings</h2>
      </div>

      <div className="space-y-6">
        {/* Service Connections */}
        <section>
          <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">
            Connected Services
          </h3>
          <div className="space-y-4">
            <GitHubConnectionCard />
            <GCPConnectionCard />
            <ZohoConnectionCard />
          </div>
        </section>

        {/* Security Info */}
        <section>
          <h3 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wider">
            Security
          </h3>
          <div className="border rounded-lg p-4 bg-card space-y-3">
            <div className="flex items-start gap-3">
              <Shield className="h-5 w-5 text-green-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium">Data Protection</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Cloud credentials are encrypted with AES-256-GCM before storage. Access tokens are
                  short-lived (1 hour) and refreshed on-demand. We never store your raw cloud data —
                  logs and metrics are fetched, analyzed, and discarded.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Lock className="h-5 w-5 text-green-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium">Revocation</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  You can disconnect at any time from this page. You can also revoke access directly
                  from your{" "}
                  <a
                    href="https://myaccount.google.com/permissions"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline inline-flex items-center gap-0.5"
                  >
                    Google Account settings <ExternalLink className="h-3 w-3" />
                  </a>
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
