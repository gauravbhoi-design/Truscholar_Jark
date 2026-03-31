import { useState, useEffect, useRef, useCallback, useMemo } from "react";

// ─── CONFIG ──────────────────────────────────────────────────
const API_BASE = window.location.origin.replace(":3000", ":8000").replace(":5173", ":8000");
const WS_URL = API_BASE.replace("http", "ws") + "/ws";

// ─── API CLIENT ──────────────────────────────────────────────
const api = {
  async get(path) {
    try {
      const r = await fetch(`${API_BASE}${path}`);
      return r.ok ? await r.json() : null;
    } catch { return null; }
  },
  async post(path, body) {
    try {
      const r = await fetch(`${API_BASE}${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return r.ok ? await r.json() : null;
    } catch { return null; }
  }
};

// ─── AGENT DEFINITIONS ──────────────────────────────────────
const AGENT_DEFS = {
  code_reviewer: { name: "Code Reviewer", icon: "🔍", color: "#E74C3C", desc: "PRs, bugs, fixes", cat: "Analysis" },
  test_runner: { name: "Test Runner", icon: "🧪", color: "#3498DB", desc: "Clone, build, test", cat: "CI/CD" },
  log_monitor: { name: "Log Monitor", icon: "📊", color: "#F39C12", desc: "Errors, RCA, alerts", cat: "Monitoring" },
  cloud_monitor: { name: "Cloud Monitor", icon: "☁️", color: "#2ECC71", desc: "Metrics, uptime, cost", cat: "Infrastructure" },
};

// ─── STATUS HELPERS ──────────────────────────────────────────
const sevColors = { low: "#2ECC71", medium: "#F39C12", high: "#E74C3C", critical: "#FF1744", warning: "#F39C12", healthy: "#2ECC71", running: "#2ECC71", completed: "#2ECC71", pending: "#F39C12", idle: "#607080", stopped: "#607080", todo: "#6C7A96", failed: "#E74C3C", error: "#E74C3C", unknown: "#607080" };
const sc = s => sevColors[s] || "#607080";

function Badge({ status }) {
  const c = sc(status);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, fontWeight: 700, color: c, background: c + "15", padding: "1px 7px", borderRadius: 3, textTransform: "uppercase", letterSpacing: ".6px", lineHeight: "18px" }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: c, ...(["running", "pending"].includes(status) ? { animation: "blink 2s infinite" } : {}) }} />
      {status}
    </span>
  );
}

// ─── AGENT CARD ──────────────────────────────────────────────
function AgentCard({ agentId, selectedRepo, repos, ws, onAction }) {
  const def = AGENT_DEFS[agentId];
  const [tab, setTab] = useState(0);
  const [report, setReport] = useState(null);
  const [plan, setPlan] = useState(null);
  const [cmd, setCmd] = useState("");
  const [cmdLog, setCmdLog] = useState([]);
  const [loading, setLoading] = useState(false);
  const logEndRef = useRef(null);

  const repo = repos?.find(r => r.id === selectedRepo || r.name === selectedRepo);

  // Fetch report when repo changes
  useEffect(() => {
    if (!selectedRepo) return;
    api.get(`/api/agents/${agentId}/report?repo_id=${selectedRepo}`).then(d => d && setReport(d));
  }, [agentId, selectedRepo]);

  // Fetch plan
  useEffect(() => {
    api.get(`/api/agents/${agentId}/plan?repo_id=${selectedRepo || ""}`).then(d => d && setPlan(d));
  }, [agentId, selectedRepo]);

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [cmdLog]);

  const sendCommand = async () => {
    if (!cmd.trim()) return;
    const input = cmd.trim();
    setCmd("");
    setCmdLog(p => [...p, { role: "user", text: input, time: new Date().toLocaleTimeString() }]);
    setLoading(true);
    onAction?.("pending", agentId, `Executing: ${input}`);

    const result = await api.post("/api/tasks", {
      command: input,
      agent_type: agentId,
      repo_id: selectedRepo,
      context: repo ? { owner: repo.full_name?.split("/")[0], repo: repo.name } : {},
    });

    setLoading(false);
    if (result) {
      setCmdLog(p => [...p, { role: "system", text: `Task ${result.id?.slice(0, 8)} created. Agent working...`, time: new Date().toLocaleTimeString() }]);
      onAction?.("completed", agentId, `Task started: ${input.slice(0, 40)}`);
    } else {
      setCmdLog(p => [...p, { role: "error", text: "Failed to create task. Check backend connection.", time: new Date().toLocaleTimeString() }]);
    }
  };

  const genPlan = async () => {
    if (!cmd.trim()) return;
    const result = await api.post(`/api/agents/${agentId}/plan`, { command: cmd, repo_id: selectedRepo });
    if (result) setPlan(result);
  };

  const tabs = ["Report", "Plan", "Command"];
  const tabIcons = ["📋", "📝", "⌨️"];

  return (
    <div style={{ background: "#0d0d16", border: `1px solid ${def.color}18`, borderRadius: 10, overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 330, transition: "border-color .2s" }} onMouseEnter={e => e.currentTarget.style.borderColor = def.color + "40"} onMouseLeave={e => e.currentTarget.style.borderColor = def.color + "18"}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: `2px solid ${def.color}20`, background: `${def.color}06` }}>
        <span style={{ fontSize: 22, filter: "drop-shadow(0 0 6px " + def.color + "40)" }}>{def.icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, fontSize: 14, color: def.color, letterSpacing: "-.3px" }}>{def.name}</div>
          <div style={{ fontSize: 10, color: "#607080", marginTop: 1 }}>{def.desc}</div>
        </div>
        <span style={{ fontSize: 9, color: "#4a5060", background: "#161622", padding: "2px 8px", borderRadius: 4, fontFamily: "var(--mono)", fontWeight: 600 }}>{def.cat}</span>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #161622" }}>
        {tabs.map((t, i) => (
          <button key={t} onClick={() => setTab(i)} style={{ flex: 1, padding: "7px 0", fontSize: 11, fontWeight: 700, background: tab === i ? "#12121e" : "transparent", color: tab === i ? def.color : "#4a5060", border: "none", borderBottom: tab === i ? `2px solid ${def.color}` : "2px solid transparent", cursor: "pointer", fontFamily: "var(--body)", transition: "all .15s" }}>
            {tabIcons[i]} {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: "auto", padding: 10, fontSize: 12 }}>
        {/* REPORT TAB */}
        {tab === 0 && (
          <div>
            <div style={{ fontSize: 11, color: "#607080", marginBottom: 8, lineHeight: 1.4 }}>
              {report?.summary || (repo ? `Analyzing ${repo.name}...` : "Select a repo to see report")}
            </div>
            {report?.items?.map((item, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 8px", borderRadius: 5, marginBottom: 3, background: sc(item.severity) + "08", borderLeft: `3px solid ${sc(item.severity)}30` }}>
                <span style={{ color: "#b0b8c8" }}>{item.label}</span>
                <span style={{ fontWeight: 700, fontFamily: "var(--mono)", color: sc(item.severity) }}>{item.value}</span>
              </div>
            ))}
            {report?.findings?.length > 0 && (
              <div style={{ marginTop: 8, borderTop: "1px solid #161622", paddingTop: 6 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#4a5060", marginBottom: 4 }}>FINDINGS</div>
                {report.findings.map((f, i) => (
                  <div key={i} style={{ fontSize: 11, color: "#8890a0", padding: "3px 0", lineHeight: 1.4 }}>• {typeof f === "string" ? f : f.text}</div>
                ))}
              </div>
            )}
            {!report?.items?.length && <div style={{ color: "#3a4050", textAlign: "center", padding: 20, fontSize: 11 }}>No data yet — connect GitHub or run an analysis</div>}
          </div>
        )}

        {/* PLAN TAB */}
        {tab === 1 && (
          <div>
            <div style={{ fontSize: 10, color: "#4a5060", marginBottom: 8 }}>Execution plan {repo ? `for ${repo.name}` : ""}</div>
            {plan?.steps?.map((step, i) => (
              <div key={step.id || i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "7px 0", borderBottom: "1px solid #161622" }}>
                <div style={{ width: 20, height: 20, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800, flexShrink: 0, marginTop: 1, background: step.status === "done" ? "#2ECC7118" : step.status === "in_progress" || step.status === "in-progress" ? "#F39C1218" : "#161622", color: step.status === "done" ? "#2ECC71" : step.status === "in_progress" || step.status === "in-progress" ? "#F39C12" : "#607080", border: `1.5px solid ${step.status === "done" ? "#2ECC7140" : step.status === "in_progress" || step.status === "in-progress" ? "#F39C1240" : "#252530"}` }}>
                  {step.status === "done" ? "✓" : i + 1}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ color: step.status === "done" ? "#607080" : "#c8d0e0", textDecoration: step.status === "done" ? "line-through" : "none", lineHeight: 1.4 }}>{step.text}</div>
                  {step.output && <div style={{ fontSize: 10, color: "#4a5060", marginTop: 2, fontFamily: "var(--mono)" }}>{step.output.slice(0, 80)}</div>}
                </div>
              </div>
            ))}
            {(!plan?.steps || plan.steps.length === 0) && (
              <div style={{ color: "#3a4050", textAlign: "center", padding: 20 }}>
                <div style={{ fontSize: 11, marginBottom: 8 }}>No plan yet</div>
                <div style={{ fontSize: 10, color: "#4a5060" }}>Type a command in the Command tab to generate a plan</div>
              </div>
            )}
          </div>
        )}

        {/* COMMAND TAB */}
        {tab === 2 && (
          <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
            <div style={{ flex: 1, overflow: "auto", marginBottom: 8, fontFamily: "var(--mono)", fontSize: 11 }}>
              {cmdLog.length === 0 && (
                <div style={{ color: "#3a4050", padding: 16, textAlign: "center", lineHeight: 1.6 }}>
                  Tell {def.name} what to do.<br />
                  <span style={{ fontSize: 10, color: "#2a3040" }}>e.g. "Review all open PRs" or "Run tests and report coverage"</span>
                </div>
              )}
              {cmdLog.map((c, i) => (
                <div key={i} style={{ marginBottom: 6, animation: "fadeSlide .3s ease" }}>
                  {c.role === "user" && <div style={{ color: def.color }}>❯ {c.text} <span style={{ color: "#3a4050", fontSize: 10 }}>{c.time}</span></div>}
                  {c.role === "system" && <div style={{ color: "#8890a0", padding: "2px 0" }}>{c.text}</div>}
                  {c.role === "error" && <div style={{ color: "#E74C3C", padding: "2px 0" }}>✗ {c.text}</div>}
                </div>
              ))}
              {loading && <div style={{ color: "#F39C12", animation: "blink 1.5s infinite" }}>⏳ Agent reasoning...</div>}
              <div ref={logEndRef} />
            </div>
            <div style={{ display: "flex", gap: 5 }}>
              <input value={cmd} onChange={e => setCmd(e.target.value)} onKeyDown={e => e.key === "Enter" && sendCommand()} placeholder={`Command ${def.name}...`} style={{ flex: 1, padding: "7px 10px", background: "#08080e", border: "1px solid #1e1e2a", borderRadius: 6, color: "#e0e8f0", fontSize: 11, fontFamily: "var(--mono)", outline: "none" }} />
              <button onClick={sendCommand} disabled={loading} style={{ padding: "7px 12px", background: def.color, border: "none", borderRadius: 6, color: "#fff", cursor: loading ? "wait" : "pointer", fontWeight: 700, fontSize: 11, fontFamily: "var(--body)", opacity: loading ? .6 : 1 }}>Run</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── CENTRAL MANAGER ─────────────────────────────────────────
function CentralManager({ actions, onApprove, onComplete }) {
  const [filter, setFilter] = useState("all");
  const filtered = filter === "all" ? actions : actions.filter(a => (a.type || a.status) === filter);
  const counts = { all: actions.length, completed: actions.filter(a => a.type === "completed").length, pending: actions.filter(a => a.type === "pending" || a.type === "running").length, todo: actions.filter(a => a.type === "todo").length };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "10px 12px", borderBottom: "1px solid #161622", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 16 }}>🎯</span>
        <span style={{ fontWeight: 800, fontSize: 14, color: "#e0e8f0", letterSpacing: "-.3px" }}>Central Manager</span>
        <span style={{ marginLeft: "auto", fontSize: 10, color: "#4a5060", fontFamily: "var(--mono)" }}>{actions.length}</span>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 3, padding: "6px 8px", borderBottom: "1px solid #161622" }}>
        {Object.entries(counts).map(([k, v]) => (
          <button key={k} onClick={() => setFilter(k)} style={{ flex: 1, padding: "4px", fontSize: 9, fontWeight: 700, background: filter === k ? "#1a1a28" : "transparent", color: filter === k ? "#00d4aa" : "#3a4050", border: filter === k ? "1px solid #252530" : "1px solid transparent", borderRadius: 4, cursor: "pointer", textTransform: "uppercase", letterSpacing: ".5px", fontFamily: "var(--body)" }}>
            {k} {v > 0 ? `(${v})` : ""}
          </button>
        ))}
      </div>

      {/* Actions List */}
      <div style={{ flex: 1, overflow: "auto", padding: 6 }}>
        {filtered.length === 0 && <div style={{ color: "#3a4050", textAlign: "center", padding: 20, fontSize: 11 }}>No actions</div>}
        {filtered.map((a, i) => {
          const icon = { completed: "✅", pending: "⏳", running: "⚡", todo: "📌", failed: "❌", cancelled: "🚫" }[a.type] || "❓";
          const agentDef = AGENT_DEFS[a.agent_type] || {};
          return (
            <div key={a.id || i} style={{ display: "flex", gap: 7, padding: "7px 6px", marginBottom: 3, borderRadius: 6, background: "#0a0a14", border: "1px solid #161622", fontSize: 11, alignItems: "flex-start", animation: "fadeSlide .3s ease" }}>
              <span style={{ fontSize: 13, flexShrink: 0 }}>{icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: "#b0b8c8", lineHeight: 1.4, wordBreak: "break-word" }}>{a.description}</div>
                <div style={{ display: "flex", gap: 6, marginTop: 3, fontSize: 9, color: "#4a5060", flexWrap: "wrap" }}>
                  {agentDef.name && <span style={{ color: agentDef.color }}>{agentDef.name}</span>}
                  <span>{a.created_at ? new Date(a.created_at).toLocaleTimeString() : ""}</span>
                  {a.severity && <Badge status={a.severity === "high" ? "critical" : a.severity === "medium" ? "warning" : "healthy"} />}
                </div>
              </div>
              {(a.type === "pending" || a.type === "running") && (
                <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
                  <button onClick={() => onApprove?.(a.id)} style={{ width: 22, height: 22, borderRadius: 4, border: "1px solid #2ECC7130", background: "#2ECC710A", color: "#2ECC71", cursor: "pointer", fontSize: 10, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--body)" }} title="Approve">✓</button>
                  <button onClick={() => onComplete?.(a.id)} style={{ width: 22, height: 22, borderRadius: 4, border: "1px solid #E74C3C30", background: "#E74C3C0A", color: "#E74C3C", cursor: "pointer", fontSize: 10, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--body)" }} title="Cancel">✗</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── MEMORY PANEL ────────────────────────────────────────────
function MemoryPanel({ memoryState }) {
  const [expanded, setExpanded] = useState(null);
  if (!memoryState) return <div style={{ color: "#3a4050", textAlign: "center", padding: 20 }}>Loading memory...</div>;

  const sections = [
    { key: "repos", title: "Repository State", icon: "📦", data: memoryState.repos || {} },
    { key: "services", title: "Services", icon: "🖥️", data: memoryState.services || {} },
    { key: "infra", title: "Infrastructure", icon: "☁️", data: memoryState.infra || {} },
    { key: "credentials", title: "Connections", icon: "🔑", data: memoryState.credentials || {} },
    { key: "agent_states", title: "Agent States", icon: "🤖", data: memoryState.agent_states || {} },
    { key: "stats", title: "Statistics", icon: "📈", data: memoryState.stats || {} },
  ];

  const findings = memoryState.recent_findings || [];
  const logs = memoryState.activity_log || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "10px 12px", borderBottom: "1px solid #161622", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 16, filter: "drop-shadow(0 0 8px #00d4aa40)" }}>🧠</span>
        <span style={{ fontWeight: 800, fontSize: 14, color: "#e0e8f0", letterSpacing: "-.3px" }}>System Memory</span>
        <span style={{ marginLeft: "auto", fontSize: 8, color: "#3a4050", fontFamily: "var(--mono)" }}>
          {memoryState.last_updated ? new Date(memoryState.last_updated).toLocaleTimeString() : "—"}
        </span>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 6 }}>
        {/* Memory Sections */}
        {sections.map(s => {
          const isExp = expanded === s.key;
          const data = s.data;
          const isEmpty = !data || (typeof data === "object" && Object.keys(data).length === 0);
          return (
            <div key={s.key} style={{ marginBottom: 4 }}>
              <button onClick={() => setExpanded(isExp ? null : s.key)} style={{ width: "100%", display: "flex", alignItems: "center", gap: 6, padding: "6px 8px", background: "#0a0a14", border: "1px solid #161622", borderRadius: 6, color: "#b0b8c8", fontSize: 11, cursor: "pointer", fontFamily: "var(--body)", fontWeight: 600 }}>
                <span>{s.icon}</span>
                <span style={{ flex: 1, textAlign: "left" }}>{s.title}</span>
                {!isEmpty && <span style={{ fontSize: 9, color: "#4a5060", fontFamily: "var(--mono)" }}>{Object.keys(data).length}</span>}
                <span style={{ fontSize: 9, color: "#3a4050", transform: isExp ? "rotate(90deg)" : "", transition: "transform .15s" }}>▶</span>
              </button>
              {isExp && !isEmpty && (
                <div style={{ padding: "4px 8px 4px 28px", fontSize: 10, fontFamily: "var(--mono)" }}>
                  {Object.entries(data).map(([k, v]) => {
                    const val = typeof v === "object" && v !== null ? (v.value !== undefined ? v.value : v) : v;
                    const display = typeof val === "object" ? JSON.stringify(val).slice(0, 50) : String(val);
                    const isGood = ["connected", "passing", "healthy", "running", "idle"].includes(display);
                    const isBad = ["disconnected", "failing", "critical", "error"].includes(display);
                    return (
                      <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid #10101a" }}>
                        <span style={{ color: "#607080" }}>{k.replace("repo:", "").replace("service:", "").replace("agent:", "")}</span>
                        <span style={{ color: isGood ? "#2ECC71" : isBad ? "#E74C3C" : "#8890a0", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{display}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {/* Findings */}
        {findings.length > 0 && (
          <div style={{ marginTop: 8, borderTop: "1px solid #161622", paddingTop: 6 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#4a5060", marginBottom: 4, display: "flex", gap: 4, alignItems: "center" }}>🔎 RECENT FINDINGS</div>
            {findings.slice(0, 8).map((f, i) => (
              <div key={i} style={{ fontSize: 10, color: "#607080", padding: "3px 0", borderBottom: "1px solid #10101a08", lineHeight: 1.4 }}>
                {typeof f === "string" ? `• ${f}` : (
                  <><span style={{ color: sc(f.severity || "medium") }}>[{f.severity}]</span> {f.text}</>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Activity Log */}
        <div style={{ marginTop: 8, borderTop: "1px solid #161622", paddingTop: 6 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#4a5060", marginBottom: 4, display: "flex", gap: 4, alignItems: "center" }}>📜 ACTIVITY LOG</div>
          <div style={{ maxHeight: 200, overflow: "auto" }}>
            {logs.length === 0 && <div style={{ fontSize: 10, color: "#2a3040", padding: 8 }}>No activity yet</div>}
            {logs.slice(0, 20).map((entry, i) => (
              <div key={i} style={{ fontSize: 9, color: "#4a5060", padding: "2px 0", borderBottom: "1px solid #10101a08", fontFamily: "var(--mono)", lineHeight: 1.5 }}>
                <span style={{ color: "#F39C12" }}>{entry.time ? new Date(entry.time).toLocaleTimeString() : ""}</span>{" "}
                {entry.agent && entry.agent !== "system" && <span style={{ color: AGENT_DEFS[entry.agent]?.color || "#607080" }}>[{AGENT_DEFS[entry.agent]?.name || entry.agent}]</span>}{" "}
                {entry.text}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── TASK DETAIL MODAL ───────────────────────────────────────
function TaskModal({ task, onClose, onApprove }) {
  if (!task) return null;
  return (
    <div style={{ position: "fixed", inset: 0, background: "#000000c0", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", backdropFilter: "blur(4px)" }} onClick={onClose}>
      <div style={{ background: "#0d0d16", border: "1px solid #252530", borderRadius: 12, width: "90%", maxWidth: 700, maxHeight: "80vh", overflow: "auto", padding: 24 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, fontWeight: 800, color: "#e0e8f0", margin: 0 }}>Task: {task.command?.slice(0, 60)}</h3>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#607080", fontSize: 18, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <Badge status={task.status} />
          <span style={{ fontSize: 11, color: "#607080" }}>Agent: {AGENT_DEFS[task.agent_type]?.name || task.agent_type}</span>
          <span style={{ fontSize: 11, color: "#4a5060" }}>Steps: {task.steps?.length || 0}</span>
        </div>

        {/* Steps */}
        {task.steps?.map((step, i) => (
          <div key={step.id || i} style={{ padding: "10px 12px", marginBottom: 6, borderRadius: 6, background: "#08080e", border: "1px solid #161622" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <Badge status={step.status} />
              <span style={{ fontSize: 12, fontWeight: 600, color: "#c8d0e0" }}>{step.description}</span>
            </div>
            {step.command && <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "#607080", padding: "4px 8px", background: "#06060a", borderRadius: 4, marginTop: 4 }}>$ {step.command}</div>}
            {step.output && <pre style={{ fontSize: 10, fontFamily: "var(--mono)", color: "#4a5060", padding: "4px 8px", maxHeight: 120, overflow: "auto", whiteSpace: "pre-wrap", margin: "4px 0 0" }}>{step.output.slice(0, 500)}</pre>}
            {step.error && <div style={{ fontSize: 10, color: "#E74C3C", marginTop: 4 }}>Error: {step.error.slice(0, 200)}</div>}
            {step.status === "awaiting_approval" && (
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <button onClick={() => onApprove?.(task.id, step.id, true)} style={{ padding: "5px 14px", background: "#2ECC71", border: "none", borderRadius: 5, color: "#fff", fontWeight: 700, fontSize: 11, cursor: "pointer", fontFamily: "var(--body)" }}>Approve</button>
                <button onClick={() => onApprove?.(task.id, step.id, false)} style={{ padding: "5px 14px", background: "#E74C3C", border: "none", borderRadius: 5, color: "#fff", fontWeight: 700, fontSize: 11, cursor: "pointer", fontFamily: "var(--body)" }}>Reject</button>
              </div>
            )}
          </div>
        ))}

        {/* Report */}
        {task.report && (
          <div style={{ marginTop: 12, padding: 12, background: "#08080e", borderRadius: 6, border: "1px solid #161622" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#e0e8f0", marginBottom: 6 }}>📄 Report</div>
            <pre style={{ fontSize: 11, fontFamily: "var(--mono)", color: "#8890a0", whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto", lineHeight: 1.5 }}>{task.report.slice(0, 3000)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// ─── MAIN APP ────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════

export default function AIDevOpsPlatform() {
  const [repos, setRepos] = useState([]);
  const [services, setServices] = useState([]);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [sidebarTab, setSidebarTab] = useState("repos");
  const [rightPanel, setRightPanel] = useState("manager");
  const [actions, setActions] = useState([]);
  const [memoryState, setMemoryState] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [stats, setStats] = useState({});
  const [globalCmd, setGlobalCmd] = useState("");
  const [selectedTask, setSelectedTask] = useState(null);
  const [connected, setConnected] = useState(false);
  const [wsEvents, setWsEvents] = useState([]);
  const wsRef = useRef(null);
  const pollRef = useRef(null);

  // WebSocket connection
  useEffect(() => {
    let ws;
    let retryTimeout;
    const connect = () => {
      try {
        ws = new WebSocket(WS_URL);
        ws.onopen = () => { setConnected(true); wsRef.current = ws; };
        ws.onclose = () => { setConnected(false); retryTimeout = setTimeout(connect, 3000); };
        ws.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data);
            setWsEvents(p => [event, ...p].slice(0, 50));

            // Auto-refresh tasks when events come in
            if (["task_completed", "task_failed", "step_completed", "step_failed", "approval_needed"].includes(event.event_type)) {
              refreshTasks();
              refreshActions();
            }
          } catch {}
        };
      } catch { retryTimeout = setTimeout(connect, 3000); }
    };
    connect();
    return () => { ws?.close(); clearTimeout(retryTimeout); };
  }, []);

  // Initial data load
  useEffect(() => { refreshAll(); }, []);

  // Polling for updates
  useEffect(() => {
    pollRef.current = setInterval(refreshAll, 15000);
    return () => clearInterval(pollRef.current);
  }, []);

  const refreshAll = async () => {
    const dash = await api.get("/api/dashboard");
    if (dash) {
      setRepos(dash.repos || []);
      setServices(dash.services || []);
      setActions(dash.actions || []);
      setMemoryState(dash.memory || null);
      setTasks(dash.tasks || []);
      setStats(dash.stats || {});
      if (!selectedRepo && dash.repos?.length) setSelectedRepo(dash.repos[0].id || dash.repos[0].name);
    }
  };

  const refreshTasks = () => api.get("/api/tasks?limit=20").then(d => d && setTasks(d));
  const refreshActions = () => api.get("/api/actions?limit=50").then(d => d && setActions(d));

  const handleGlobalCmd = async () => {
    if (!globalCmd.trim()) return;
    const result = await api.post("/api/tasks", {
      command: globalCmd, context: {}, repo_id: selectedRepo,
    });
    setGlobalCmd("");
    if (result) refreshTasks();
  };

  const handleApproveAction = async (actionId) => {
    await api.post(`/api/actions/${actionId}/complete`);
    refreshActions();
  };
  const handleCancelAction = async (actionId) => {
    await api.post(`/api/actions/${actionId}/cancel`);
    refreshActions();
  };
  const handleTaskApprove = async (taskId, stepId, approved) => {
    await api.post(`/api/tasks/${taskId}/approve`, { step_id: stepId, approved, comment: "" });
    const t = await api.get(`/api/tasks/${taskId}`);
    if (t) setSelectedTask(t);
    refreshTasks();
  };

  const addLocalAction = (type, agent, desc) => {
    setActions(p => [{ id: `local-${Date.now()}`, type, agent_type: agent, description: desc, severity: "medium", created_at: new Date().toISOString() }, ...p]);
  };

  // Stats
  const activeCount = tasks.filter(t => ["running", "awaiting_approval", "parsing"].includes(t.status)).length;
  const completedCount = tasks.filter(t => t.status === "completed").length;
  const pendingActions = actions.filter(a => a.type === "pending" || a.type === "running").length;

  return (
    <div style={{ fontFamily: "var(--body)", background: "#06060c", color: "#e0e8f0", height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Azeret+Mono:wght@400;500;600;700&family=Outfit:wght@400;500;600;700;800;900&display=swap');
        :root { --body: 'Outfit', sans-serif; --mono: 'Azeret Mono', monospace; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }
        @keyframes fadeSlide { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
        @keyframes glow { 0%,100%{box-shadow:0 0 8px #00d4aa20} 50%{box-shadow:0 0 16px #00d4aa40} }
        * { margin:0; padding:0; box-sizing:border-box; }
        ::-webkit-scrollbar { width:4px; height:4px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:#1e1e2a; border-radius:4px; }
        ::-webkit-scrollbar-thumb:hover { background:#2a2a38; }
        input:focus, button:focus { outline:none; }
        button { transition: all .15s; }
        button:hover { filter: brightness(1.15); }
      `}</style>

      {/* ═══ HEADER ═══ */}
      <header style={{ display: "flex", alignItems: "center", padding: "8px 16px", borderBottom: "1px solid #121220", background: "linear-gradient(180deg, #0a0a14, #08080e)", gap: 14, flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 34, height: 34, borderRadius: 8, background: "linear-gradient(135deg, #00d4aa, #0077ff)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: 13, color: "#000", fontFamily: "var(--mono)", letterSpacing: "-1px", animation: "glow 3s infinite" }}>AI</div>
          <div>
            <div style={{ fontWeight: 900, fontSize: 15, letterSpacing: "-.5px", lineHeight: 1.1 }}>AI DevOps Platform</div>
            <div style={{ fontSize: 9, color: "#3a4050", fontWeight: 600, letterSpacing: ".5px" }}>AUTONOMOUS AGENT ORCHESTRATION</div>
          </div>
        </div>

        {/* Global command */}
        <div style={{ flex: 1, maxWidth: 520, display: "flex", gap: 5, marginLeft: 16 }}>
          <div style={{ flex: 1, position: "relative" }}>
            <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#3a4050", fontSize: 12 }}>⌘</span>
            <input value={globalCmd} onChange={e => setGlobalCmd(e.target.value)} onKeyDown={e => e.key === "Enter" && handleGlobalCmd()} placeholder="Give a command to the orchestrator..." style={{ width: "100%", padding: "7px 12px 7px 28px", background: "#0d0d16", border: "1px solid #1e1e2a", borderRadius: 7, color: "#e0e8f0", fontSize: 12, fontFamily: "var(--mono)" }} />
          </div>
          <button onClick={handleGlobalCmd} style={{ padding: "7px 16px", background: "linear-gradient(135deg, #00d4aa, #00b894)", border: "none", borderRadius: 7, color: "#000", fontWeight: 800, fontSize: 11, cursor: "pointer", fontFamily: "var(--body)", letterSpacing: "-.3px" }}>Execute</button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginLeft: "auto" }}>
          <Badge status={connected ? "running" : "error"} />
          <div style={{ fontSize: 10, color: "#3a4050", fontFamily: "var(--mono)" }}>
            {Object.keys(AGENT_DEFS).length} agents
          </div>
        </div>
      </header>

      {/* ═══ MAIN LAYOUT ═══ */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "220px 1fr 280px", overflow: "hidden" }}>

        {/* ═══ LEFT SIDEBAR ═══ */}
        <aside style={{ borderRight: "1px solid #121220", background: "#08080e", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ display: "flex", borderBottom: "1px solid #121220" }}>
            {[["repos", "Repos"], ["services", "Services"]].map(([k, l]) => (
              <button key={k} onClick={() => setSidebarTab(k)} style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 5, padding: "9px 0", fontSize: 11, fontWeight: 700, background: sidebarTab === k ? "#0d0d16" : "transparent", color: sidebarTab === k ? "#00d4aa" : "#3a4050", border: "none", borderBottom: sidebarTab === k ? "2px solid #00d4aa" : "2px solid transparent", cursor: "pointer", fontFamily: "var(--body)" }}>
                {k === "repos" ? "📦" : "🖥️"} {l}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, overflow: "auto", padding: 6 }}>
            {sidebarTab === "repos" && repos.map(repo => (
              <button key={repo.id || repo.name} onClick={() => setSelectedRepo(repo.id || repo.name)} style={{ width: "100%", textAlign: "left", padding: "9px 8px", marginBottom: 3, borderRadius: 7, background: selectedRepo === (repo.id || repo.name) ? "#12121e" : "transparent", border: selectedRepo === (repo.id || repo.name) ? "1px solid #1e1e2a" : "1px solid transparent", cursor: "pointer", color: "#e0e8f0", fontFamily: "var(--body)", transition: "all .15s" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: "-.2px" }}>{repo.name}</span>
                  <Badge status={repo.status || "unknown"} />
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 5, fontSize: 9, color: "#4a5060" }}>
                  {repo.language && <span style={{ color: "#F39C12" }}>{repo.language}</span>}
                  <span>⚡{repo.open_issues || 0}</span>
                  <span>↑{repo.open_prs || 0}</span>
                </div>
                <div style={{ fontSize: 9, color: "#2a3040", marginTop: 2 }}>{repo.default_branch} · {repo.last_commit || "—"}</div>
              </button>
            ))}

            {sidebarTab === "repos" && repos.length === 0 && (
              <div style={{ color: "#3a4050", textAlign: "center", padding: 24, fontSize: 11, lineHeight: 1.6 }}>
                No repos found.<br />
                <span style={{ fontSize: 10 }}>Set GITHUB_TOKEN in .env</span>
              </div>
            )}

            {sidebarTab === "services" && services.map(svc => (
              <div key={svc.name} style={{ padding: "9px 8px", marginBottom: 3, borderRadius: 7, background: "#0d0d16", border: "1px solid #161622" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 700, fontSize: 11 }}>{svc.name}</span>
                  <Badge status={svc.status || "unknown"} />
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 4, fontSize: 9, color: "#4a5060" }}>
                  <span>{svc.service_type}</span>
                  <span>{svc.region}</span>
                </div>
              </div>
            ))}

            {sidebarTab === "services" && services.length === 0 && (
              <div style={{ color: "#3a4050", textAlign: "center", padding: 24, fontSize: 11, lineHeight: 1.6 }}>
                No services found.<br />
                <span style={{ fontSize: 10 }}>Set GCP_PROJECT_ID in .env</span>
              </div>
            )}
          </div>

          {/* Tasks List */}
          <div style={{ borderTop: "1px solid #121220", maxHeight: 200, overflow: "auto" }}>
            <div style={{ padding: "6px 10px", fontSize: 10, fontWeight: 700, color: "#3a4050", letterSpacing: ".5px", background: "#0a0a12" }}>RECENT TASKS</div>
            {tasks.slice(0, 8).map(task => (
              <button key={task.id} onClick={() => setSelectedTask(task)} style={{ width: "100%", textAlign: "left", padding: "6px 10px", borderBottom: "1px solid #10101a", cursor: "pointer", background: "transparent", border: "none", color: "#e0e8f0", fontFamily: "var(--body)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Badge status={task.status} />
                  <span style={{ fontSize: 10, color: "#8890a0", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.command?.slice(0, 30)}</span>
                </div>
              </button>
            ))}
          </div>

          {/* Connection Status */}
          <div style={{ borderTop: "1px solid #121220", padding: 8 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#3a4050", marginBottom: 4, letterSpacing: ".5px" }}>CONNECTIONS</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
              {[
                ["GitHub", memoryState?.credentials?.github === "connected"],
                ["GCP", memoryState?.credentials?.gcp === "connected"],
                ["Claude", memoryState?.credentials?.anthropic === "connected"],
                ["Docker", memoryState?.credentials?.docker === "connected"],
              ].map(([name, ok]) => (
                <span key={name} style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: ok ? "#2ECC710A" : "#E74C3C0A", color: ok ? "#2ECC71" : "#607080", border: `1px solid ${ok ? "#2ECC7120" : "#1e1e2a"}`, fontWeight: 600 }}>{ok ? "●" : "○"} {name}</span>
              ))}
            </div>
          </div>
        </aside>

        {/* ═══ CENTER — Agent Cards ═══ */}
        <main style={{ overflow: "auto", padding: 12, background: "#08080e" }}>
          {/* Stats Bar */}
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            {[
              { label: "Active Tasks", value: activeCount, color: "#F39C12" },
              { label: "Completed", value: completedCount, color: "#2ECC71" },
              { label: "Pending Actions", value: pendingActions, color: "#E74C3C" },
              { label: "Success Rate", value: stats.success_rate || "—", color: "#00d4aa" },
            ].map((s, i) => (
              <div key={i} style={{ flex: 1, padding: "8px 12px", background: "#0d0d16", borderRadius: 8, border: "1px solid #161622" }}>
                <div style={{ fontSize: 9, color: "#3a4050", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".5px" }}>{s.label}</div>
                <div style={{ fontSize: 20, fontWeight: 900, color: s.color, fontFamily: "var(--mono)", marginTop: 1, letterSpacing: "-1px" }}>{s.value}</div>
              </div>
            ))}
          </div>

          {/* Selected Repo Bar */}
          {selectedRepo && (() => {
            const repo = repos.find(r => (r.id || r.name) === selectedRepo);
            return repo ? (
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 12px", marginBottom: 10, background: "#0d0d16", borderRadius: 7, border: "1px solid #161622" }}>
                <span style={{ fontSize: 13 }}>📦</span>
                <span style={{ fontWeight: 800, fontSize: 13, letterSpacing: "-.3px" }}>{repo.name}</span>
                {repo.language && <span style={{ fontSize: 10, color: "#F39C12", fontWeight: 600 }}>{repo.language}</span>}
                <span style={{ fontSize: 10, color: "#4a5060" }}>{repo.default_branch}</span>
                <Badge status={repo.status || "unknown"} />
                <span style={{ marginLeft: "auto", fontSize: 10, color: "#3a4050", fontFamily: "var(--mono)" }}>
                  {repo.open_issues || 0} issues · {repo.open_prs || 0} PRs
                </span>
              </div>
            ) : null;
          })()}

          {/* Agent Cards 2×2 Grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {Object.keys(AGENT_DEFS).map(id => (
              <AgentCard key={id} agentId={id} selectedRepo={selectedRepo} repos={repos} ws={wsRef.current} onAction={addLocalAction} />
            ))}
          </div>

          {/* Orchestrator Bar */}
          <div style={{ marginTop: 10, padding: "10px 14px", background: "#0d0d16", borderRadius: 8, border: "1px solid #161622" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 15 }}>⚙️</span>
              <span style={{ fontWeight: 800, fontSize: 13, letterSpacing: "-.3px" }}>Agent Orchestrator</span>
              <span style={{ marginLeft: "auto", fontSize: 9, color: "#3a4050" }}>Task queue · Routing · State · Reporting</span>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {[
                { label: "Queue", value: activeCount },
                { label: "Total Tasks", value: stats.total_tasks || 0 },
                { label: "Success", value: stats.success_rate || "—" },
                { label: "Agents", value: Object.keys(AGENT_DEFS).length },
              ].map((m, i) => (
                <div key={i} style={{ flex: 1, padding: "5px 8px", background: "#08080e", borderRadius: 5, border: "1px solid #121220" }}>
                  <div style={{ fontSize: 8, color: "#3a4050", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".5px" }}>{m.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 800, color: "#00d4aa", fontFamily: "var(--mono)", letterSpacing: "-.5px" }}>{m.value}</div>
                </div>
              ))}
            </div>

            {/* Live Events Feed */}
            {wsEvents.length > 0 && (
              <div style={{ marginTop: 8, borderTop: "1px solid #121220", paddingTop: 6 }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#3a4050", marginBottom: 3 }}>LIVE EVENTS</div>
                <div style={{ maxHeight: 60, overflow: "auto" }}>
                  {wsEvents.slice(0, 5).map((ev, i) => (
                    <div key={i} style={{ fontSize: 9, fontFamily: "var(--mono)", color: "#4a5060", padding: "1px 0" }}>
                      <span style={{ color: AGENT_DEFS[ev.agent_type]?.color || "#607080" }}>[{AGENT_DEFS[ev.agent_type]?.name || ev.agent_type}]</span>{" "}
                      <span style={{ color: "#F39C12" }}>{ev.event_type}</span>{" "}
                      {ev.data?.message || ev.data?.description || ""}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </main>

        {/* ═══ RIGHT PANEL ═══ */}
        <aside style={{ borderLeft: "1px solid #121220", background: "#08080e", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ display: "flex", borderBottom: "1px solid #121220" }}>
            {[["manager", "🎯 Manager"], ["memory", "🧠 Memory"]].map(([k, l]) => (
              <button key={k} onClick={() => setRightPanel(k)} style={{ flex: 1, padding: "9px 0", fontSize: 11, fontWeight: 700, background: rightPanel === k ? "#0d0d16" : "transparent", color: rightPanel === k ? "#00d4aa" : "#3a4050", border: "none", borderBottom: rightPanel === k ? "2px solid #00d4aa" : "2px solid transparent", cursor: "pointer", fontFamily: "var(--body)" }}>
                {l}
              </button>
            ))}
          </div>
          <div style={{ flex: 1, overflow: "hidden" }}>
            {rightPanel === "manager" ? (
              <CentralManager actions={actions} onApprove={handleApproveAction} onComplete={handleCancelAction} />
            ) : (
              <MemoryPanel memoryState={memoryState} />
            )}
          </div>
        </aside>
      </div>

      {/* Task Modal */}
      <TaskModal task={selectedTask} onClose={() => setSelectedTask(null)} onApprove={handleTaskApprove} />
    </div>
  );
}
