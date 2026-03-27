const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface AgentResponse {
  conversation_id: string;
  message: string;
  agents_used: string[];
  tool_calls: Record<string, unknown>[];
  cost_usd: number;
  status: "idle" | "running" | "completed" | "failed" | "awaiting_approval";
}

export interface StreamEvent {
  event: string;
  agent: string | null;
  data: Record<string, unknown>;
}

function getAuthHeader(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token || "dev_local"}`,
  };
}

export async function sendQuery(
  query: string,
  conversationId?: string,
  context?: Record<string, unknown>,
): Promise<AgentResponse> {
  const res = await fetch(`${API_URL}/agent/query`, {
    method: "POST",
    headers: getAuthHeader(),
    body: JSON.stringify({ query, conversation_id: conversationId, context }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function sendQueryStream(
  query: string,
  onEvent: (event: StreamEvent) => void,
  conversationId?: string,
  context?: Record<string, unknown>,
): Promise<void> {
  const res = await fetch(`${API_URL}/agent/query/stream`, {
    method: "POST",
    headers: getAuthHeader(),
    body: JSON.stringify({ query, conversation_id: conversationId, context }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const data = line.replace(/^data: /, "").trim();
      if (!data || data === "[DONE]") continue;
      try {
        onEvent(JSON.parse(data) as StreamEvent);
      } catch {
        console.error("Failed to parse SSE event:", data);
      }
    }
  }
}

export function connectWebSocket(
  onEvent: (event: StreamEvent) => void,
  onError: (error: Event) => void,
): WebSocket {
  const wsUrl = (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000") + "/api/v1/ws/agent";
  const ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as StreamEvent;
      onEvent(data);
    } catch {
      console.error("Failed to parse WS message");
    }
  };

  ws.onerror = onError;
  return ws;
}

// ─── Plan Mode API ────────────────────────────────────────────────────────

export interface PlanStep {
  id: string;
  order: number;
  title: string;
  description: string;
  agent_name: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  status: "pending" | "approved" | "executing" | "completed" | "failed" | "skipped";
  result?: Record<string, unknown>;
  cost_usd: number;
}

export interface PlanResponse {
  id: string;
  query: string;
  summary: string;
  status: "pending" | "approved" | "executing" | "completed" | "rejected";
  steps: PlanStep[];
  agents_used: string[];
  total_cost_usd: number;
  created_at?: string;
}

export async function generatePlan(
  query: string,
  context?: Record<string, unknown>,
): Promise<PlanResponse> {
  const res = await fetch(`${API_URL}/agent/plan`, {
    method: "POST",
    headers: getAuthHeader(),
    body: JSON.stringify({ query, context }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function approvePlan(
  planId: string,
  action: "approve_all" | "reject" | "approve_step" | "skip_step",
  stepId?: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/agent/plan/approve`, {
    method: "POST",
    headers: getAuthHeader(),
    body: JSON.stringify({ plan_id: planId, action, step_id: stepId }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function executePlanStep(
  planId: string,
  stepId?: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/agent/plan/execute-step`, {
    method: "POST",
    headers: getAuthHeader(),
    body: JSON.stringify({ plan_id: planId, step_id: stepId }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// ─── Live Log Streaming ──────────────────────────────────────────────────

export interface LogEntry {
  event: "log" | "connected" | "info" | "error" | "done";
  timestamp?: string;
  severity?: string;
  message?: string;
  resource_type?: string;
  resource_labels?: Record<string, string>;
  log_name?: string;
  insert_id?: string;
  project_id?: string;
  filter?: string;
}

export function streamLiveLogs(
  params: {
    project_id?: string;
    resource_type?: string;
    service_name?: string;
    severity?: string;
    filter?: string;
    duration?: number;
  },
  onEntry: (entry: LogEntry) => void,
  onError: (error: string) => void,
  onDone: () => void,
): AbortController {
  const controller = new AbortController();

  const searchParams = new URLSearchParams();
  if (params.project_id) searchParams.set("project_id", params.project_id);
  if (params.resource_type) searchParams.set("resource_type", params.resource_type);
  if (params.service_name) searchParams.set("service_name", params.service_name);
  if (params.severity) searchParams.set("severity", params.severity);
  if (params.filter) searchParams.set("filter", params.filter);
  if (params.duration) searchParams.set("duration", String(params.duration));

  const token = typeof window !== "undefined" ? localStorage.getItem("copilot_token") : null;

  fetch(`${API_URL}/agent/logs/stream?${searchParams}`, {
    headers: { Authorization: `Bearer ${token || ""}` },
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}`);
        return;
      }
      if (!res.body) {
        onError("No response body");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const data = line.replace(/^data: /, "").trim();
          if (!data || data === "[DONE]") {
            onDone();
            continue;
          }
          try {
            const entry = JSON.parse(data) as LogEntry;
            if (entry.event === "error") {
              onError(entry.message || "Unknown error");
            } else if (entry.event === "done") {
              onDone();
            } else {
              onEntry(entry);
            }
          } catch {
            // skip malformed
          }
        }
      }
      onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onError(String(err));
      }
    });

  return controller;
}

export async function getGcpStatus(): Promise<{
  connected: boolean;
  project_id?: string;
  email?: string;
}> {
  try {
    const res = await fetch(`${API_URL}/auth/gcp/status`, { headers: getAuthHeader() });
    if (!res.ok) return { connected: false };
    return res.json();
  } catch {
    return { connected: false };
  }
}

export async function getAuditLogs(limit = 50): Promise<Record<string, unknown>[]> {
  const res = await fetch(`${API_URL}/audit/logs?limit=${limit}`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function getStats(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/admin/stats`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) return {};
  return res.json();
}

// ─── Engineering Metrics API ─────────────────────────────────────────────

export interface DORAMetricDetail {
  value: number;
  tier: string;
  label: string;
  industry_percentile?: number;
  trend: string;
}

export interface SPACEDimensionScore {
  dimension: string;
  score: number;
  sub_metrics: Array<{ name: string; current_value: string | number; target: string; tier: string }>;
  data_completeness_pct: number;
}

export interface DXCore4PillarScore {
  pillar: string;
  score: number;
  signal: string;
  components?: Record<string, number>;
}

export interface AICapabilityScore {
  capability_id: number;
  name: string;
  maturity_level: number;
  maturity_label: string;
}

export interface Recommendation {
  priority: number;
  area: string;
  current_state: string;
  target_state: string;
  actions: string[];
  expected_impact: string;
}

export interface MetricsDashboardData {
  composite: {
    dora_score: number;
    space_score: number;
    dx_core4_score: number;
    ai_capabilities_score: number;
    final_score: number;
    overall_tier: string;
  };
  dora: {
    deployment_frequency: DORAMetricDetail;
    lead_time: DORAMetricDetail;
    change_failure_rate: DORAMetricDetail;
    recovery_time: DORAMetricDetail;
    rework_rate: DORAMetricDetail;
    overall_score: number;
    elite_count: number;
  };
  space: {
    satisfaction: SPACEDimensionScore;
    performance: SPACEDimensionScore;
    activity: SPACEDimensionScore;
    communication: SPACEDimensionScore;
    efficiency: SPACEDimensionScore;
    overall_score: number;
  };
  dx_core4: {
    speed: DXCore4PillarScore;
    effectiveness: DXCore4PillarScore;
    quality: DXCore4PillarScore;
    business_impact: DXCore4PillarScore;
    overall_score: number;
  };
  ai_capabilities: {
    capabilities: AICapabilityScore[];
    average_maturity: number;
    normalized_score: number;
    ready_for_ai_coding: boolean;
    ready_for_ai_production: boolean;
  };
  top_recommendations: Recommendation[];
  last_updated: string;
}

export async function fetchMetricsDashboard(repo: string, days = 30): Promise<MetricsDashboardData> {
  const res = await fetch(`${API_URL}/metrics/dashboard?repo=${encodeURIComponent(repo)}&days=${days}`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`Failed to fetch metrics: ${res.status}`);
  return res.json();
}

export async function fetchDORAMetrics(repo: string, days = 30): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/metrics/dora?repo=${encodeURIComponent(repo)}&days=${days}`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`Failed to fetch DORA metrics: ${res.status}`);
  return res.json();
}

export async function fetchSPACEMetrics(repo: string, days = 7): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/metrics/space?repo=${encodeURIComponent(repo)}&days=${days}`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`Failed to fetch SPACE metrics: ${res.status}`);
  return res.json();
}

export async function fetchCompositeScore(repo: string, days = 30): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/metrics/composite?repo=${encodeURIComponent(repo)}&days=${days}`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`Failed to fetch composite score: ${res.status}`);
  return res.json();
}

export async function fetchRecommendations(repo: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/metrics/recommendations?repo=${encodeURIComponent(repo)}`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`Failed to fetch recommendations: ${res.status}`);
  return res.json();
}

export async function fetchCIPipelineHealth(repo: string, days = 30): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/metrics/ci-pipeline?repo=${encodeURIComponent(repo)}&days=${days}`, {
    headers: getAuthHeader(),
  });
  if (!res.ok) throw new Error(`Failed to fetch CI pipeline health: ${res.status}`);
  return res.json();
}
