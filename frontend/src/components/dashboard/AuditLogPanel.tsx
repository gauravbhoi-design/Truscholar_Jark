"use client";

import { useState, useEffect } from "react";
import { Shield, CheckCircle, XCircle, Clock } from "lucide-react";
import { getAuditLogs } from "@/lib/api";

interface AuditEntry {
  id: string;
  agent_name: string;
  tool_name: string;
  approved: boolean;
  duration_ms: number;
  created_at: string;
}

export function AuditLogPanel() {
  const [logs, setLogs] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchLogs() {
      try {
        const data = await getAuditLogs(50);
        setLogs(data as unknown as AuditEntry[]);
      } catch {
        // API may not be running
      } finally {
        setLoading(false);
      }
    }
    fetchLogs();
  }, []);

  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className="flex items-center gap-2 mb-6">
        <Shield className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">Audit Log</h2>
        <span className="text-xs text-muted-foreground ml-auto">
          All agent actions are logged for compliance
        </span>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Clock className="h-4 w-4 animate-pulse" />
          <span className="text-sm">Loading audit logs...</span>
        </div>
      ) : logs.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <Shield className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No audit logs yet. Agent actions will appear here.</p>
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50">
                <th className="text-left px-4 py-2 font-medium">Status</th>
                <th className="text-left px-4 py-2 font-medium">Agent</th>
                <th className="text-left px-4 py-2 font-medium">Tool</th>
                <th className="text-left px-4 py-2 font-medium">Duration</th>
                <th className="text-left px-4 py-2 font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-t hover:bg-muted/30">
                  <td className="px-4 py-2">
                    {log.approved ? (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    ) : (
                      <XCircle className="h-4 w-4 text-destructive" />
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <span className="px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary">
                      {log.agent_name}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">{log.tool_name}</td>
                  <td className="px-4 py-2 text-muted-foreground">{log.duration_ms}ms</td>
                  <td className="px-4 py-2 text-muted-foreground text-xs">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
