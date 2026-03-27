"use client";

import { useEffect, useState } from "react";
import { Github, ArrowRight, Shield, Bot, Activity, Cloud } from "lucide-react";
import { getGitHubLoginUrl, getGoogleLoginUrl, getToken, fetchCurrentUser, type AuthUser } from "@/lib/auth";
import Dashboard from "@/components/dashboard/Dashboard";

export default function Home() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [loginUrl, setLoginUrl] = useState<string>("");
  const [googleLoginUrl, setGoogleLoginUrl] = useState<string>("");

  useEffect(() => {
    // Check for token in URL (from OAuth callback redirect)
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("token");
    if (urlToken) {
      localStorage.setItem("copilot_token", urlToken);
      window.history.replaceState({}, "", "/");
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
    getGoogleLoginUrl()
      .then(setGoogleLoginUrl)
      .catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (user) {
    return <Dashboard user={user} />;
  }

  return <LoginPage loginUrl={loginUrl} googleLoginUrl={googleLoginUrl} />;
}

function LoginPage({ loginUrl, googleLoginUrl }: { loginUrl: string; googleLoginUrl: string }) {
  const handleGitHubLogin = () => {
    if (loginUrl) window.location.href = loginUrl;
  };

  const handleGoogleLogin = () => {
    if (googleLoginUrl) window.location.href = googleLoginUrl;
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
              onClick={handleGoogleLogin}
              disabled={!googleLoginUrl}
              className="w-72 inline-flex items-center justify-center gap-3 px-6 py-3 rounded-lg bg-white hover:bg-gray-50 text-gray-700 font-medium border border-gray-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg className="h-5 w-5" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              Sign in with Google
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>

          <p className="text-xs text-muted-foreground mt-4">
            <strong>GitHub:</strong> Access your repositories for code analysis.
            <br />
            <strong>Google:</strong> Access your GCP project for cloud debugging.
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
