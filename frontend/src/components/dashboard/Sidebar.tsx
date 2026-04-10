"use client";

import {
  MessageSquare,
  Bot,
  Shield,
  Settings,
  Activity,
  GitBranch,
  Radio,
  LayoutDashboard,
  BarChart3,
  Gauge,
  ShieldCheck,
} from "lucide-react";

export type TabId =
  | "overview"
  | "chat"
  | "repos"
  | "metrics"
  | "agents"
  | "sprints"
  | "logs"
  | "audit"
  | "admin"
  | "settings";

interface SidebarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  isAdmin?: boolean;
}

const baseNavItems = [
  { id: "overview" as const, label: "Dashboard", icon: LayoutDashboard },
  { id: "chat" as const, label: "AI Chat", icon: MessageSquare },
  { id: "repos" as const, label: "Repositories", icon: GitBranch },
  { id: "metrics" as const, label: "Eng Metrics", icon: Gauge },
  { id: "sprints" as const, label: "Sprints", icon: BarChart3 },
  { id: "agents" as const, label: "Agents", icon: Bot },
  { id: "logs" as const, label: "Live Logs", icon: Radio },
  { id: "audit" as const, label: "Audit Log", icon: Shield },
];

const adminNavItem = { id: "admin" as const, label: "Admin", icon: ShieldCheck };

export function Sidebar({ activeTab, onTabChange, isAdmin = false }: SidebarProps) {
  const navItems = isAdmin ? [...baseNavItems, adminNavItem] : baseNavItems;
  return (
    <aside className="w-16 md:w-56 border-r flex flex-col bg-card shrink-0">
      {/* Logo */}
      <div className="h-14 border-b flex items-center justify-center md:justify-start md:px-4">
        <Activity className="h-6 w-6 text-primary" />
        <span className="hidden md:inline ml-2 font-bold text-sm">Co-Pilot</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 space-y-1 px-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="hidden md:inline">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Footer — Settings button */}
      <div className="border-t p-2">
        <button
          onClick={() => onTabChange("settings")}
          className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
            activeTab === "settings"
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          }`}
        >
          <Settings className="h-4 w-4 shrink-0" />
          <span className="hidden md:inline">Settings</span>
        </button>
      </div>
    </aside>
  );
}
