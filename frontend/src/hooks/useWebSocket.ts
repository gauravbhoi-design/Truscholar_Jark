"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { type StreamEvent } from "@/lib/api";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  const connect = useCallback(() => {
    const wsUrl =
      (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000") + "/api/v1/ws/agent";
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as StreamEvent;
        if (data.event === "done") {
          setIsStreaming(false);
        } else {
          setEvents((prev) => [...prev, data]);
        }
      } catch {
        // ignore parse errors
      }
    };

    wsRef.current = ws;
  }, []);

  const sendQuery = useCallback(
    (query: string, conversationId?: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        connect();
      }

      setIsStreaming(true);
      setEvents([]);

      // Wait for connection then send
      const trySend = () => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(
            JSON.stringify({ query, conversation_id: conversationId }),
          );
        } else {
          setTimeout(trySend, 100);
        }
      };
      trySend();
    },
    [connect],
  );

  return { connected, events, isStreaming, sendQuery, connect };
}
