/**
 * Lightweight pub/sub for agent status events across components.
 * ChatPanel publishes events, AgentStatusPanel subscribes.
 */

export type AgentStatus = "idle" | "running" | "done" | "error";

export interface AgentStatusUpdate {
  agent: string;
  status: AgentStatus;
  detail?: string;
  timestamp: number;
}

type Listener = (update: AgentStatusUpdate) => void;

const listeners = new Set<Listener>();
const currentStatus = new Map<string, AgentStatusUpdate>();

export function publishAgentStatus(update: AgentStatusUpdate) {
  currentStatus.set(update.agent, update);
  listeners.forEach((fn) => fn(update));
}

export function subscribeAgentStatus(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAgentStatuses(): Map<string, AgentStatusUpdate> {
  return new Map(currentStatus);
}
