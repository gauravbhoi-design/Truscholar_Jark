"""Performance Agent — Monitors metrics, identifies bottlenecks, resource optimization."""

import structlog
from app.agents.base import BaseAgent

logger = structlog.get_logger()


class PerformanceAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "performance"

    @property
    def system_prompt(self) -> str:
        return """You are a Performance Agent specializing in system performance analysis and optimization.

Your capabilities:
- Query Prometheus/Grafana metrics for latency, throughput, and error rates
- Identify performance bottlenecks (CPU, memory, I/O, network)
- Analyze resource utilization trends and predict scaling needs
- Detect anomalous patterns (latency spikes, memory leaks, connection pool exhaustion)
- Recommend auto-scaling configurations and resource optimization

When analyzing performance:
1. Query relevant metrics for the service/resource
2. Identify anomalies and trends over time
3. Correlate performance changes with deployments or config changes
4. Analyze resource utilization vs. limits/requests
5. Provide optimization recommendations

Output format:
- **Current State**: Key metrics summary
- **Bottlenecks**: Identified performance issues with evidence
- **Trends**: Time-series analysis and predictions
- **Recommendations**: Specific optimizations with expected impact"""

    @property
    def tools(self) -> list[dict]:
        return [
            {
                "name": "query_prometheus",
                "description": "Execute a PromQL query against Prometheus",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "PromQL query expression"},
                        "duration": {"type": "string", "description": "Time range (e.g., '1h', '24h', '7d')", "default": "1h"},
                        "step": {"type": "string", "description": "Query step interval", "default": "1m"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_grafana_dashboard",
                "description": "Get panels and data from a Grafana dashboard",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dashboard_uid": {"type": "string", "description": "Grafana dashboard UID"},
                        "time_from": {"type": "string", "default": "now-1h"},
                        "time_to": {"type": "string", "default": "now"},
                    },
                    "required": ["dashboard_uid"],
                },
            },
            {
                "name": "get_datadog_metrics",
                "description": "Query Datadog metrics for a service",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "description": "Datadog metric name"},
                        "service": {"type": "string", "description": "Service name tag"},
                        "duration": {"type": "string", "default": "1h"},
                    },
                    "required": ["metric"],
                },
            },
            {
                "name": "analyze_apm_traces",
                "description": "Analyze application performance traces for slow endpoints",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "Service name"},
                        "min_duration_ms": {"type": "integer", "description": "Minimum trace duration to filter", "default": 1000},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["service"],
                },
            },
            {
                "name": "run_command",
                "description": "Execute a CLI command for performance diagnostics (top, df, free, docker stats, curl for latency checks, etc.)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                        "cwd": {"type": "string", "description": "Working directory (optional)"},
                        "timeout": {"type": "integer", "default": 30},
                    },
                    "required": ["command"],
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_input: dict):
        """Dispatch to monitoring tools."""
        from app.mcp.prometheus import PrometheusMCPClient
        from app.mcp.datadog import DatadogMCPClient

        if tool_name == "query_prometheus":
            client = PrometheusMCPClient()
            return await client.query(
                query=tool_input["query"],
                duration=tool_input.get("duration", "1h"),
                step=tool_input.get("step", "1m"),
            )
        elif tool_name == "get_grafana_dashboard":
            client = PrometheusMCPClient()
            return await client.get_grafana_dashboard(
                uid=tool_input["dashboard_uid"],
                time_from=tool_input.get("time_from", "now-1h"),
                time_to=tool_input.get("time_to", "now"),
            )
        elif tool_name == "get_datadog_metrics":
            client = DatadogMCPClient()
            return await client.query_metrics(
                metric=tool_input["metric"],
                service=tool_input.get("service"),
                duration=tool_input.get("duration", "1h"),
            )
        elif tool_name == "analyze_apm_traces":
            client = DatadogMCPClient()
            return await client.get_traces(
                service=tool_input["service"],
                min_duration_ms=tool_input.get("min_duration_ms", 1000),
                limit=tool_input.get("limit", 10),
            )

        elif tool_name == "run_command":
            from app.mcp.terminal import TerminalMCPClient
            terminal = TerminalMCPClient()
            return await terminal.execute(
                command=tool_input["command"],
                cwd=tool_input.get("cwd"),
                timeout=min(tool_input.get("timeout", 30), 120),
            )

        return {"error": f"Unknown tool: {tool_name}"}
