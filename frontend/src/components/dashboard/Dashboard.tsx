"use client";

import { useState, useEffect } from "react";
import { type AuthUser, logout } from "@/lib/auth";
import { Sidebar, type TabId } from "./Sidebar";
import { OverviewPanel } from "./OverviewPanel";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AgentStatusPanel } from "./AgentStatusPanel";
import { AuditLogPanel } from "./AuditLogPanel";
import { RepoSelector } from "./RepoSelector";
import { SprintPanel } from "./SprintPanel";
import { LiveLogViewer } from "./LiveLogViewer";
import { SettingsPanel } from "./SettingsPanel";
import { MetricsPanel } from "./MetricsPanel";
import { AdminPanel } from "./AdminPanel";
import { LogOut } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";

interface Props {
  user: AuthUser;
}

export default function Dashboard({ user }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  // Tabs the user has visited at least once. ChatPanel below is kept
  // mounted (and hidden via CSS) once visited so its messages, input
  // draft, and live event stream survive a tab switch.
  const [visited, setVisited] = useState<Set<TabId>>(new Set(["overview"]));

  // Listen for navigation events from other components (e.g., Quick Actions)
  useEffect(() => {
    const handler = (e: CustomEvent<TabId>) => {
      setActiveTab(e.detail);
    };
    window.addEventListener("navigate-tab", handler as EventListener);
    return () => window.removeEventListener("navigate-tab", handler as EventListener);
  }, []);

  // Track visits so the chat panel mounts on first click and stays mounted.
  useEffect(() => {
    setVisited((prev) => {
      if (prev.has(activeTab)) return prev;
      const next = new Set(prev);
      next.add(activeTab);
      return next;
    });
  }, [activeTab]);

  const isAdmin = user.role === "admin";

  return (
    <div className="flex h-screen">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} isAdmin={isAdmin} />

      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="h-14 border-b flex items-center px-6 shrink-0 justify-between">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">DevOps Co-Pilot</h1>
            <span className="px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary">
              AI-Powered
            </span>
          </div>

          <div className="flex items-center gap-3">
            {user.avatar_url && (
              <img
                src={user.avatar_url}
                alt={user.login}
                className="w-7 h-7 rounded-full"
              />
            )}
            <span className="text-sm font-medium">{user.name}</span>
            <span className="text-xs text-muted-foreground">@{user.login}</span>
            <ThemeToggle />
            <button
              onClick={logout}
              className="p-1.5 rounded-md hover:bg-muted text-muted-foreground"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-hidden">
          {activeTab === "overview" && <OverviewPanel />}

          {/* Chat panel stays mounted across tab switches so the user's
              typed query, message history, and live event stream are not
              wiped when they hop over to another tab. Lazy-mounted on
              first visit. */}
          {visited.has("chat") && (
            <div className={activeTab === "chat" ? "h-full" : "hidden"}>
              <ChatPanel />
            </div>
          )}

          {activeTab === "agents" && <AgentStatusPanel />}
          {activeTab === "audit" && <AuditLogPanel />}
          {activeTab === "repos" && <RepoSelector />}
          {activeTab === "metrics" && <MetricsPanel />}
          {activeTab === "sprints" && <SprintPanel />}
          {activeTab === "logs" && <LiveLogViewer />}
          {activeTab === "admin" && isAdmin && <AdminPanel />}
          {activeTab === "settings" && <SettingsPanel />}
        </div>
      </main>
    </div>
  );
}
