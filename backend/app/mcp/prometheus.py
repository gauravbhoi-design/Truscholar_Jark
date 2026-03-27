"""Prometheus & Grafana MCP Client — Metrics queries and dashboard access."""

import httpx
import structlog
from app.config import get_settings

logger = structlog.get_logger()


class PrometheusMCPClient:
    """MCP-compatible client for Prometheus and Grafana."""

    def __init__(self, prometheus_url: str = "http://localhost:9090", grafana_url: str = "http://localhost:3001"):
        self.prometheus_url = prometheus_url
        self.grafana_url = grafana_url

    async def query(self, query: str, duration: str = "1h", step: str = "1m") -> dict:
        """Execute a PromQL range query."""
        duration_map = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}
        seconds = duration_map.get(duration, 3600)

        import time
        end = time.time()
        start = end - seconds

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.prometheus_url}/api/v1/query_range",
                    params={"query": query, "start": start, "end": end, "step": step},
                )
                resp.raise_for_status()
                data = resp.json()

                results = data.get("data", {}).get("result", [])
                return {
                    "query": query,
                    "result_count": len(results),
                    "results": [
                        {
                            "metric": r.get("metric", {}),
                            "values_count": len(r.get("values", [])),
                            "latest_value": r["values"][-1][1] if r.get("values") else None,
                        }
                        for r in results[:20]
                    ],
                }
            except Exception as e:
                return {"error": str(e), "query": query}

    async def get_grafana_dashboard(
        self, uid: str, time_from: str = "now-1h", time_to: str = "now"
    ) -> dict:
        """Get Grafana dashboard panels."""
        settings = get_settings()
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{self.grafana_url}/api/dashboards/uid/{uid}",
                    headers={"Authorization": f"Bearer {settings.datadog_api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()

                dashboard = data.get("dashboard", {})
                panels = dashboard.get("panels", [])
                return {
                    "uid": uid,
                    "title": dashboard.get("title"),
                    "panels": [
                        {"id": p.get("id"), "title": p.get("title"), "type": p.get("type")}
                        for p in panels[:20]
                    ],
                }
            except Exception as e:
                return {"error": str(e), "uid": uid}
