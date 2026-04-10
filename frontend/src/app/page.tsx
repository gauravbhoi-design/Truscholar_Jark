"use client";

import { useEffect, useState } from "react";
import { Github, ArrowRight, Shield, Bot, Activity, Cloud, Package } from "lucide-react";
import { getGitHubLoginUrl, getGcpLoginUrl, getToken, fetchCurrentUser, fetchGcpProjects, selectGcpProject, type AuthUser } from "@/lib/auth";
import Dashboard from "@/components/dashboard/Dashboard";

export default function Home() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [loginUrl, setLoginUrl] = useState<string>("");
  const [gcpLoginUrl, setGcpLoginUrl] = useState<string>("");
  const [showProjectSelector, setShowProjectSelector] = useState(false);

  useEffect(() => {
    // Check for token in URL (from OAuth callback redirect)
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("token");
    const isGcpSignin = params.get("gcp_signin") === "true";

    if (urlToken) {
      localStorage.setItem("copilot_token", urlToken);
      window.history.replaceState({}, "", "/");

      // If this was a GCP sign-in, show project selector before dashboard
      if (isGcpSignin) {
        fetchCurrentUser(urlToken)
          .then((u) => {
            setUser(u);
            setShowProjectSelector(true);
          })
          .catch(() => localStorage.removeItem("copilot_token"))
          .finally(() => setLoading(false));
        return;
      }
    }

    // Clean up connect callback params (github=connected, gcp=connected)
    if (params.get("github") || params.get("gcp")) {
      window.history.replaceState({}, "", "/");
    }

    // Check for existing token
    const token = getToken();
    if (token) {
      fetchCurrentUser(token)
        .then(setUser)
        .catch(() => {
          localStorage.removeItem("copilot_token");
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }

    // Pre-fetch login URLs
    getGitHubLoginUrl()
      .then(setLoginUrl)
      .catch(() => {});
    getGcpLoginUrl()
      .then(setGcpLoginUrl)
      .catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (user && showProjectSelector) {
    return <GcpProjectSelector onDone={() => setShowProjectSelector(false)} />;
  }

  if (user) {
    return <Dashboard user={user} />;
  }

  return <LoginPage loginUrl={loginUrl} gcpLoginUrl={gcpLoginUrl} />;
}

function GcpProjectSelector({ onDone }: { onDone: () => void }) {
  const [projects, setProjects] = useState<{ id: string; name: string; number: string }[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [selecting, setSelecting] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetchGcpProjects(token)
      .then(setProjects)
      .catch(() => {})
      .finally(() => setLoadingProjects(false));
  }, []);

  const handleSelect = async (projectId: string) => {
    const token = getToken();
    if (!token) return;
    setSelecting(projectId);
    await selectGcpProject(token, projectId);
    onDone();
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center">
          <Activity className="h-6 w-6 text-primary mr-2" />
          <span className="font-bold text-lg">DevOps Co-Pilot</span>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-6">
        <div className="max-w-lg w-full">
          <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center mx-auto mb-4">
            <Cloud className="h-6 w-6 text-blue-500" />
          </div>
          <h2 className="text-2xl font-bold text-center mb-2">Select a GCP Project</h2>
          <p className="text-muted-foreground text-center mb-6 text-sm">
            Choose which project to monitor and debug
          </p>

          {loadingProjects ? (
            <div className="text-center text-muted-foreground animate-pulse py-8">
              Loading your GCP projects...
            </div>
          ) : projects.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-muted-foreground mb-4">No GCP projects found for your account.</p>
              <button
                onClick={onDone}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
              >
                Continue to Dashboard
              </button>
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleSelect(p.id)}
                  disabled={selecting !== null}
                  className="w-full flex items-center justify-between px-4 py-3 rounded-lg border bg-card hover:bg-accent transition-colors text-left disabled:opacity-50"
                >
                  <div>
                    <p className="font-medium text-sm">{p.name}</p>
                    <p className="text-xs text-muted-foreground">{p.id}</p>
                  </div>
                  {selecting === p.id ? (
                    <div className="animate-spin h-4 w-4 border-2 border-primary border-t-transparent rounded-full" />
                  ) : (
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                  )}
                </button>
              ))}
            </div>
          )}

          {projects.length > 0 && (
            <button
              onClick={onDone}
              className="w-full mt-4 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              Skip — choose later in Settings
            </button>
          )}
        </div>
      </main>
    </div>
  );
}

function LoginPage({ loginUrl, gcpLoginUrl }: { loginUrl: string; gcpLoginUrl: string }) {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

  const handleGitHubLogin = () => {
    if (loginUrl) window.location.href = loginUrl;
  };

  const handleGcpLogin = () => {
    if (gcpLoginUrl) window.location.href = gcpLoginUrl;
  };

  const handleInstallApp = async () => {
    // Installation must be linked to a TruJark account, so the user has to
    // sign in first. After login they can install from Settings.
    const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
    if (!token) {
      alert("Please sign in with GitHub first, then install the app from Settings.");
      if (loginUrl) window.location.href = loginUrl;
      return;
    }
    try {
      const res = await fetch(`${API_URL}/github-app/install`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        window.location.href = data.install_url;
      } else {
        alert("GitHub App not configured on the server");
      }
    } catch {
      alert("Backend not available");
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center">
          <Activity className="h-6 w-6 text-primary mr-2" />
          <span className="font-bold text-lg">DevOps Co-Pilot</span>
        </div>
      </header>

      {/* Hero */}
      <main className="flex-1 flex items-center justify-center px-6">
        <div className="max-w-lg text-center">
          <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-6">
            <Bot className="h-8 w-8 text-primary" />
          </div>

          <h1 className="text-3xl font-bold mb-3">AI-Powered DevOps Assistant</h1>

          <p className="text-muted-foreground mb-8 text-lg">
            Debug deployments, review code, analyze commits, and monitor
            performance — all powered by Claude Opus 4.6.
          </p>

          {/* Sign-in buttons */}
          <div className="flex flex-col gap-3 items-center">
            <button
              onClick={handleGitHubLogin}
              disabled={!loginUrl}
              className="w-72 inline-flex items-center justify-center gap-3 px-6 py-3 rounded-lg bg-[#24292f] hover:bg-[#32383f] text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Github className="h-5 w-5" />
              Sign in with GitHub
              <ArrowRight className="h-4 w-4" />
            </button>

            <button
              onClick={handleGcpLogin}
              disabled={!gcpLoginUrl}
              className="w-72 inline-flex items-center justify-center gap-3 px-6 py-3 rounded-lg bg-[#1a73e8] hover:bg-[#1765cc] text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Cloud className="h-5 w-5" />
              Sign in with GCP
              <ArrowRight className="h-4 w-4" />
            </button>

            {/* Divider */}
            <div className="w-72 flex items-center gap-3 my-1">
              <div className="flex-1 border-t" />
              <span className="text-[10px] text-muted-foreground uppercase">or</span>
              <div className="flex-1 border-t" />
            </div>

            <button
              onClick={handleInstallApp}
              className="w-72 inline-flex items-center justify-center gap-3 px-6 py-3 rounded-lg bg-purple-600 hover:bg-purple-700 text-white font-medium transition-colors"
            >
              <Package className="h-5 w-5" />
              Install GitHub App
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>

          <p className="text-xs text-muted-foreground mt-4">
            <strong>GitHub:</strong> Access your repositories for code analysis.
            <br />
            <strong>GCP:</strong> Access your cloud projects for monitoring & debugging.
            <br />
            <strong>GitHub App:</strong> Install on your org for webhooks & fine-grained access.
          </p>

          {/* Features */}
          <div className="grid grid-cols-3 gap-4 mt-12 text-left">
            {[
              { icon: Shield, title: "Secure", desc: "OAuth 2.0 with read-only access" },
              { icon: Bot, title: "6 AI Agents", desc: "Cloud, code, commits, deploy, perf" },
              { icon: Activity, title: "Real-time", desc: "Live streaming analysis results" },
            ].map((f) => (
              <div key={f.title} className="p-3 rounded-lg border bg-card">
                <f.icon className="h-5 w-5 text-primary mb-2" />
                <p className="font-medium text-sm">{f.title}</p>
                <p className="text-xs text-muted-foreground">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
