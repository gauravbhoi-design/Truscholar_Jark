"""Datadog MCP Client — Metrics, APM traces, and alerts."""

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()


class DatadogMCPClient:
    """MCP-compatible client for Datadog monitoring."""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.datadog_api_key
        self.base_url = "https://api.datadoghq.com/api/v1"
        self.headers = {
            "DD-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    async def query_metrics(
        self, metric: str, service: str | None = None, duration: str = "1h"
    ) -> dict:
        """Query Datadog metrics."""
        import time

        duration_map = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}
        seconds = duration_map.get(duration, 3600)
        now = int(time.time())

        query = metric
        if service:
            query = f"{metric}{{service:{service}}}"

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/query",
                    headers=self.headers,
                    params={"from": now - seconds, "to": now, "query": query},
                )
                resp.raise_for_status()
                data = resp.json()

                series = data.get("series", [])
                return {
                    "metric": metric,
                    "series_count": len(series),
                    "series": [
                        {
                            "scope": s.get("scope"),
                            "pointlist_length": len(s.get("pointlist", [])),
                            "avg": s.get("avg"),
                            "max": s.get("max"),
                        }
                        for s in series[:10]
                    ],
                }
            except Exception as e:
                return {"error": str(e), "metric": metric}

    async def get_traces(
        self, service: str, min_duration_ms: int = 1000, limit: int = 10
    ) -> dict:
        """Get APM traces for slow endpoints."""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/traces",
                    headers=self.headers,
                    params={
                        "service": service,
                        "min_duration": min_duration_ms * 1_000_000,  # Convert to nanoseconds
                        "limit": limit,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                return {
                    "service": service,
                    "traces": [
                        {
                            "trace_id": t.get("trace_id"),
                            "duration_ms": t.get("duration", 0) / 1_000_000,
                            "resource": t.get("resource"),
                            "error": t.get("error", 0),
                        }
                        for t in data.get("traces", [])[:limit]
                    ],
                }
            except Exception as e:
                return {"error": str(e), "service": service}
