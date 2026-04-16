"use client";

import { useState, useRef, useEffect } from "react";
import {
  Send,
  Loader2,
  Bot,
  User,
  GitBranch,
  Cloud,
  Shield,
  Wrench,
  CheckCircle2,
  XCircle,
  Brain,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  FileDown,
} from "lucide-react";
import { sendQueryStream, getGcpStatus, generatePlan, type StreamEvent, type PlanResponse } from "@/lib/api";
import { publishAgentStatus } from "@/lib/agent-events";
import {
  getSelectedRepos,
  removeRepo,
  subscribeRepos,
} from "@/lib/repo-store";
import { PlanCard } from "./PlanCard";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface AgentEvent {
  id: string;
  type: string;
  agent: string;
  data: Record<string, unknown>;
  timestamp: number;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  agents?: string[];
  cost?: number;
  status?: string;
  events?: AgentEvent[];
  plan?: PlanResponse;
}

interface GcpInfo {
  connected: boolean;
  project_id?: string;
  email?: string;
}

const AGENT_LABELS: Record<string, string> = {
  supervisor: "Supervisor",
  cloud_debugger: "Cloud Debugger",
  codebase_analyzer: "Codebase Analyzer",
  commit_analyst: "Commit Analyst",
  deployment_doctor: "Deployment Doctor",
  performance: "Performance Agent",
};

function AgentActivityFeed({ events }: { events: AgentEvent[] }) {
  const [expanded, setExpanded] = useState(true);

  if (events.length === 0) return null;

  return (
    <div className="mb-3 border rounded-md bg-muted/30 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-muted/50 transition-colors"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        Agent Activity ({events.length} events)
      </button>

      {expanded && (
        <div className="px-3 pb-2 space-y-1 max-h-64 overflow-y-auto">
          {events.map((evt) => (
            <EventItem key={evt.id} event={evt} />
          ))}
        </div>
      )}
    </div>
  );
}

function EventItem({ event }: { event: AgentEvent }) {
  const agentLabel = AGENT_LABELS[event.agent] || event.agent;

  switch (event.type) {
    case "thinking":
    case "agent_thinking":
      return (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-0.5">
          <Brain className="h-3 w-3 text-purple-400 shrink-0" />
          <span className="font-medium text-purple-400">{agentLabel}</span>
          <span>{String(event.data.message || "Thinking...")}</span>
        </div>
      );

    case "routing":
      return (
        <div className="flex items-start gap-2 text-xs py-0.5">
          <ArrowRight className="h-3 w-3 text-blue-400 mt-0.5 shrink-0" />
          <div>
            <span className="font-medium text-blue-400">Routing</span>
            <span className="text-muted-foreground"> → </span>
            {((event.data.agents as string[]) || []).map((a) => (
              <span
                key={a}
                className="inline-block px-1.5 py-0.5 mr-1 rounded bg-blue-500/10 text-blue-400 text-[10px] font-medium"
              >
                {AGENT_LABELS[a] || a}
              </span>
            ))}
          </div>
        </div>
      );

    case "agent_start":
      return (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-0.5">
          <Loader2 className="h-3 w-3 text-yellow-400 animate-spin shrink-0" />
          <span className="font-medium text-yellow-400">{agentLabel}</span>
          <span>started</span>
        </div>
      );

    case "tool_call":
      return (
        <div className="flex items-start gap-2 text-xs py-0.5">
          <Wrench className="h-3 w-3 text-cyan-400 mt-0.5 shrink-0" />
          <div>
            <span className="font-medium text-cyan-400">{agentLabel}</span>
            <span className="text-muted-foreground"> calling </span>
            <code className="px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-300 text-[10px]">
              {String(event.data.tool)}
            </code>
            {event.data.input ? (
              <span className="text-muted-foreground/60 ml-1 text-[10px]">
                {formatToolInput(event.data.input as Record<string, unknown>)}
              </span>
            ) : null}
          </div>
        </div>
      );

    case "tool_result":
      return (
        <div className="flex items-start gap-2 text-xs py-0.5">
          {event.data.success ? (
            <CheckCircle2 className="h-3 w-3 text-green-400 mt-0.5 shrink-0" />
          ) : (
            <XCircle className="h-3 w-3 text-red-400 mt-0.5 shrink-0" />
          )}
          <div>
            <code className="px-1 py-0.5 rounded bg-secondary text-[10px]">
              {String(event.data.tool)}
            </code>
            <span className={`ml-1 ${event.data.success ? "text-green-400" : "text-red-400"}`}>
              {event.data.success ? "✓ success" : "✗ failed"}
            </span>
            {event.data.preview ? (
              <p className="text-muted-foreground/60 text-[10px] mt-0.5 line-clamp-2">
                {String(event.data.preview).slice(0, 120)}
              </p>
            ) : null}
          </div>
        </div>
      );

    case "agent_done":
      return (
        <div className="flex items-center gap-2 text-xs py-0.5">
          <CheckCircle2 className="h-3 w-3 text-green-400 shrink-0" />
          <span className="font-medium text-green-400">{agentLabel}</span>
          <span className="text-muted-foreground">
            completed
            {event.data.tool_calls_count
              ? ` (${event.data.tool_calls_count} tool calls, $${Number(event.data.cost_usd || 0).toFixed(4)})`
              : ""}
          </span>
        </div>
      );

    case "agent_error":
      return (
        <div className="flex items-center gap-2 text-xs py-0.5">
          <XCircle className="h-3 w-3 text-red-400 shrink-0" />
          <span className="font-medium text-red-400">{agentLabel}</span>
          <span className="text-red-300">{String(event.data.error || "Unknown error").slice(0, 100)}</span>
        </div>
      );

    default:
      return null;
  }
}

function formatToolInput(input: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(input)) {
    if (typeof v === "string") {
      parts.push(`${k}="${v.length > 40 ? v.slice(0, 40) + "..." : v}"`);
    }
  }
  return parts.length > 0 ? `(${parts.join(", ")})` : "";
}

// Live activity indicator shown while streaming
function LiveActivity({ events }: { events: AgentEvent[] }) {
  const lastEvent = events[events.length - 1];
  if (!lastEvent) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        <span>Starting...</span>
      </div>
    );
  }

  const agentLabel = AGENT_LABELS[lastEvent.agent] || lastEvent.agent;

  switch (lastEvent.type) {
    case "thinking":
    case "agent_thinking":
      return (
        <div className="flex items-center gap-2 text-sm">
          <Brain className="h-4 w-4 text-purple-400 animate-pulse" />
          <span className="text-purple-400 font-medium">{agentLabel}</span>
          <span className="text-muted-foreground">{String(lastEvent.data.message)}</span>
        </div>
      );
    case "tool_call":
      return (
        <div className="flex items-center gap-2 text-sm">
          <Wrench className="h-4 w-4 text-cyan-400 animate-pulse" />
          <span className="text-cyan-400 font-medium">{agentLabel}</span>
          <span className="text-muted-foreground">
            calling <code className="text-xs px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-300">{String(lastEvent.data.tool)}</code>
          </span>
        </div>
      );
    case "agent_start":
      return (
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 text-yellow-400 animate-spin" />
          <span className="text-yellow-400 font-medium">{agentLabel}</span>
          <span className="text-muted-foreground">started...</span>
        </div>
      );
    case "routing":
      return (
        <div className="flex items-center gap-2 text-sm">
          <ArrowRight className="h-4 w-4 text-blue-400" />
          <span className="text-muted-foreground">Routing to agents...</span>
        </div>
      );
    default:
      return (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <span>Processing...</span>
        </div>
      );
  }
}

// ─── Report Download ──────────────────────────────────────────────────

function downloadBlob(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function downloadAsMarkdown(msg: Message) {
  const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, "-");
  const header = `# DevOps Co-Pilot Report\n\n**Date:** ${new Date().toLocaleString()}  \n**Agents:** ${(msg.agents || []).join(", ") || "N/A"}  \n**Cost:** $${msg.cost?.toFixed(4) ?? "N/A"}\n\n---\n\n`;
  downloadBlob(header + msg.content, `copilot-report-${timestamp}.md`, "text/markdown");
}

function downloadAsPdf(msg: Message) {
  const timestamp = new Date().toLocaleString();
  const agents = (msg.agents || []).join(", ") || "N/A";

  // Convert markdown to simple HTML for print (handles headings, lists, code, tables, bold, italic, links)
  const htmlBody = markdownToHtml(msg.content);

  const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DevOps Co-Pilot Report</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 40px 24px; color: #1a1a1a; font-size: 14px; line-height: 1.6; }
  .header { border-bottom: 2px solid #e5e7eb; padding-bottom: 16px; margin-bottom: 24px; }
  .header h1 { margin: 0 0 8px; font-size: 22px; color: #111; }
  .meta { font-size: 12px; color: #6b7280; }
  .meta span { margin-right: 16px; }
  h1 { font-size: 20px; margin-top: 28px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
  h2 { font-size: 17px; margin-top: 24px; }
  h3 { font-size: 15px; margin-top: 20px; }
  pre { background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 12px; }
  code { font-family: 'SF Mono', Consolas, monospace; font-size: 12px; }
  :not(pre)>code { background: #f3f4f6; padding: 2px 5px; border-radius: 3px; }
  table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
  th, td { border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; }
  th { background: #f9fafb; font-weight: 600; }
  blockquote { border-left: 3px solid #d1d5db; margin: 12px 0; padding-left: 12px; color: #6b7280; }
  ul, ol { padding-left: 24px; }
  li { margin: 4px 0; }
  a { color: #2563eb; }
  @media print { body { padding: 0; } .no-print { display: none; } }
</style></head><body>
<div class="header">
  <h1>DevOps Co-Pilot Report</h1>
  <div class="meta">
    <span><strong>Date:</strong> ${timestamp}</span>
    <span><strong>Agents:</strong> ${agents}</span>
    <span><strong>Cost:</strong> $${msg.cost?.toFixed(4) ?? "N/A"}</span>
  </div>
</div>
${htmlBody}
<script>window.onload=function(){window.print();}</script>
</body></html>`;

  const win = window.open("", "_blank");
  if (win) {
    win.document.write(html);
    win.document.close();
  }
}

/** Lightweight markdown → HTML converter for the PDF print view. */
function markdownToHtml(md: string): string {
  let html = md;

  // Code blocks (```lang ... ```)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    const escaped = code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<pre><code class="language-${lang}">${escaped}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Tables (GFM)
  html = html.replace(
    /^(\|.+\|)\n(\|[\s:|-]+\|)\n((?:\|.+\|\n?)+)/gm,
    (_m, headerRow: string, _sep: string, bodyRows: string) => {
      const ths = headerRow.split("|").filter(Boolean).map((c: string) => `<th>${c.trim()}</th>`).join("");
      const rows = bodyRows.trim().split("\n").map((row: string) => {
        const tds = row.split("|").filter(Boolean).map((c: string) => `<td>${c.trim()}</td>`).join("");
        return `<tr>${tds}</tr>`;
      }).join("");
      return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
    },
  );

  // Headings
  html = html.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // Bold & italic
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');

  // Blockquotes
  html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");

  // Horizontal rules
  html = html.replace(/^---+$/gm, "<hr>");

  // Unordered lists
  html = html.replace(/^(?:- (.+)\n?)+/gm, (block) => {
    const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^- /, "")}</li>`).join("");
    return `<ul>${items}</ul>`;
  });

  // Ordered lists
  html = html.replace(/^(?:\d+\. (.+)\n?)+/gm, (block) => {
    const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^\d+\. /, "")}</li>`).join("");
    return `<ol>${items}</ol>`;
  });

  // Paragraphs (remaining bare lines)
  html = html.replace(/^(?!<[a-z/])(.+)$/gm, "<p>$1</p>");

  return html;
}

function DownloadButton({ msg }: { msg: Message }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        title="Download report"
      >
        <Download className="h-3.5 w-3.5" />
      </button>

      {open && (
        <div className="absolute right-0 bottom-full mb-1 z-50 w-44 rounded-lg border bg-popover shadow-lg py-1 animate-in fade-in-0 zoom-in-95">
          <button
            onClick={() => { downloadAsMarkdown(msg); setOpen(false); }}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-muted transition-colors text-left"
          >
            <FileText className="h-3.5 w-3.5 text-blue-400" />
            Download as Markdown
          </button>
          <button
            onClick={() => { downloadAsPdf(msg); setOpen(false); }}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-muted transition-colors text-left"
          >
            <FileDown className="h-3.5 w-3.5 text-red-400" />
            Download as PDF
          </button>
        </div>
      )}
    </div>
  );
}

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [planMode, setPlanMode] = useState(false);
  const [liveEvents, setLiveEvents] = useState<AgentEvent[]>([]);
  const [gcpInfo, setGcpInfo] = useState<GcpInfo>({ connected: false });
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, liveEvents]);

  // Load GCP connection status
  useEffect(() => {
    getGcpStatus().then(setGcpInfo);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);
    setLiveEvents([]);

    const collectedEvents: AgentEvent[] = [];

    try {
      const repos = getSelectedRepos();

      // Build context with both GitHub repos and GCP project
      const context: Record<string, unknown> = {};
      if (repos.length > 0) {
        context.repositories = repos;
      }
      if (gcpInfo.connected && gcpInfo.project_id) {
        context.gcp_project_id = gcpInfo.project_id;
      }

      // ─── Plan Mode: generate plan for approval ───
      if (planMode) {
        const plan = await generatePlan(
          userMsg.content,
          Object.keys(context).length > 0 ? context : undefined,
        );
        const planMsg: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "",
          plan,
          agents: plan.agents_used || [],
          cost: plan.total_cost_usd,
          status: "plan",
        };
        setMessages((prev) => [...prev, planMsg]);
        setIsLoading(false);
        return;
      }

      // ─── Direct Mode: stream execution ───
      await sendQueryStream(
        userMsg.content,
        (event: StreamEvent) => {

          const agentEvent: AgentEvent = {
            id: crypto.randomUUID(),
            type: event.event,
            agent: event.agent || "supervisor",
            data: event.data,
            timestamp: Date.now(),
          };

          // Publish status updates for AgentStatusPanel
          if (event.event === "agent_start") {
            publishAgentStatus({ agent: event.agent || "", status: "running", detail: "Started", timestamp: Date.now() });
          } else if (event.event === "tool_call") {
            publishAgentStatus({ agent: event.agent || "", status: "running", detail: `Calling ${event.data.tool}`, timestamp: Date.now() });
          } else if (event.event === "agent_done") {
            publishAgentStatus({ agent: event.agent || "", status: "done", detail: "Completed", timestamp: Date.now() });
          } else if (event.event === "agent_error") {
            publishAgentStatus({ agent: event.agent || "", status: "error", detail: String(event.data.error || "Error"), timestamp: Date.now() });
          }

          if (event.event === "final_response") {
            // Final message — add as assistant message with all events
            const assistantMsg: Message = {
              id: crypto.randomUUID(),
              role: "assistant",
              content: String(event.data.message || ""),
              agents: event.data.agents_used as string[],
              cost: event.data.cost_usd as number,
              status: event.data.status as string,
              events: [...collectedEvents],
            };
            setMessages((prev) => [...prev, assistantMsg]);
            setLiveEvents([]);
            setIsLoading(false);
          } else {
            collectedEvents.push(agentEvent);
            setLiveEvents([...collectedEvents]);
          }
        },
        undefined,
        Object.keys(context).length > 0 ? context : undefined,
      );
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "Failed to get response. Please check if the backend is running.",
          status: "failed",
          events: collectedEvents.length > 0 ? collectedEvents : undefined,
        },
      ]);
      setLiveEvents([]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <Bot className="h-12 w-12 mb-4 opacity-50" />
            <h2 className="text-xl font-semibold mb-2">DevOps Co-Pilot</h2>
            <p className="text-sm text-center max-w-md">
              Ask me about deployment issues, code reviews, performance analysis,
              CI/CD debugging, or infrastructure configuration.
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}
          >
            {msg.role === "assistant" && (
              <div className="shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                <Bot className="h-4 w-4 text-primary" />
              </div>
            )}

            <div
              className={`max-w-[80%] rounded-lg p-4 ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-card border"
              }`}
            >
              {/* Agent activity feed (collapsed by default on completed messages) */}
              {msg.role === "assistant" && msg.events && msg.events.length > 0 && (
                <AgentActivityFeed events={msg.events} />
              )}

              {/* Plan Card */}
              {msg.role === "assistant" && msg.plan ? (
                <PlanCard
                  plan={msg.plan}
                  onUpdate={(updatedPlan) => {
                    setMessages((prev) =>
                      prev.map((m) => (m.id === msg.id ? { ...m, plan: updatedPlan } : m)),
                    );
                  }}
                />
              ) : msg.role === "assistant" ? (
                <MarkdownRenderer content={msg.content} />
              ) : (
                <p className="text-sm">{msg.content}</p>
              )}

              {msg.role === "assistant" && (msg.content || msg.plan) && (
                <div className="mt-2 flex items-center justify-between gap-2">
                  <div className="flex gap-1 flex-wrap">
                    {(msg.agents || []).map((agent) => (
                      <span
                        key={agent}
                        className="px-2 py-0.5 text-xs rounded-full bg-secondary text-secondary-foreground"
                      >
                        {agent}
                      </span>
                    ))}
                    {msg.cost !== undefined && (
                      <span className="px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground">
                        ${msg.cost.toFixed(4)}
                      </span>
                    )}
                  </div>
                  {msg.content && <DownloadButton msg={msg} />}
                </div>
              )}
            </div>

            {msg.role === "user" && (
              <div className="shrink-0 w-8 h-8 rounded-full bg-muted flex items-center justify-center">
                <User className="h-4 w-4" />
              </div>
            )}
          </div>
        ))}

        {/* Live streaming activity */}
        {isLoading && (
          <div className="flex gap-3">
            <div className="shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
              <Bot className="h-4 w-4 text-primary" />
            </div>
            <div className="bg-card border rounded-lg p-4 max-w-[80%] min-w-[300px]">
              <LiveActivity events={liveEvents} />
              {liveEvents.length > 0 && (
                <div className="mt-3 border-t pt-2 space-y-1 max-h-48 overflow-y-auto">
                  {liveEvents.map((evt) => (
                    <EventItem key={evt.id} event={evt} />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="border-t p-4">
        {/* Active context badges */}
        {(getSelectedRepos().length > 0 || (gcpInfo.connected && gcpInfo.project_id)) && (
          <div className="flex items-center gap-2 mb-2 max-w-4xl mx-auto text-xs flex-wrap">
            {getSelectedRepos().map((repo) => (
              <div
                key={repo}
                className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-[#24292f]/10 text-[#24292f] dark:bg-white/10 dark:text-white/80"
              >
                <GitBranch className="h-3 w-3" />
                <span>{repo}</span>
                <button
                  type="button"
                  onClick={() => removeRepo(repo)}
                  className="ml-0.5 hover:text-red-400 transition-colors"
                  title="Remove repo"
                >
                  x
                </button>
              </div>
            ))}
            {gcpInfo.connected && gcpInfo.project_id && (
              <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-blue-500/10 text-blue-500">
                <Cloud className="h-3 w-3" />
                <span>GCP: {gcpInfo.project_id}</span>
              </div>
            )}
          </div>
        )}
        <div className="flex gap-2 max-w-4xl mx-auto">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={planMode ? "Describe what you want to do (plan will be generated for approval)..." : "Describe a DevOps issue or ask a question..."}
            className="flex-1 px-4 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            disabled={isLoading}
          />
          {/* Plan mode toggle */}
          <button
            type="button"
            onClick={() => setPlanMode(!planMode)}
            className={`px-3 py-2 rounded-lg text-xs font-medium border transition-colors flex items-center gap-1.5 ${
              planMode
                ? "bg-amber-500/10 border-amber-500/30 text-amber-500"
                : "bg-background border-border text-muted-foreground hover:text-foreground"
            }`}
            title={planMode ? "Plan mode ON — actions require your approval" : "Click to enable plan mode"}
          >
            <Shield className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{planMode ? "Plan" : "Direct"}</span>
          </button>
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </form>
    </div>
  );
}
