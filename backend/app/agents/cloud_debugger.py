"""Cloud Debugger Agent — Analyzes cloud platform logs, resources, and deployment failures."""

import structlog
from app.agents.base import BaseAgent

logger = structlog.get_logger()


class CloudDebuggerAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "cloud_debugger"

    @property
    def system_prompt(self) -> str:
        return """You are a Cloud Debugger Agent specializing in analyzing cloud infrastructure issues.

Your capabilities:
- Analyze AWS CloudWatch logs, GCP Cloud Logging entries, and Azure Monitor data
- Diagnose deployment failures, 5xx errors, OOM kills, and resource exhaustion
- Investigate ECS/EKS/GKE service health and container status
- Analyze Lambda/Cloud Function invocation errors
- Check S3/GCS bucket policies and access issues
- List and audit active GCP services: enabled APIs, Compute VMs, Cloud Run, GKE, Cloud Functions, App Engine

When analyzing an issue:
1. Identify the affected service and region
2. Look for error patterns in recent logs
3. Check resource utilization (CPU, memory, disk)
4. Correlate with recent deployments or config changes
5. Provide specific remediation steps

When asked to list or audit services, use the appropriate listing tools to get real data.

Always output structured analysis with:
- **Root Cause**: What went wrong
- **Evidence**: Log entries, metrics, or signals that support the diagnosis
- **Fix**: Step-by-step remediation
- **Prevention**: How to prevent recurrence"""

    @property
    def tools(self) -> list[dict]:
        return [
            {
                "name": "query_cloudwatch_logs",
                "description": "Query AWS CloudWatch log groups with filter patterns",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "log_group": {"type": "string", "description": "CloudWatch log group name"},
                        "filter_pattern": {"type": "string", "description": "CloudWatch filter pattern"},
                        "hours_back": {"type": "integer", "description": "How many hours back to search", "default": 24},
                    },
                    "required": ["log_group"],
                },
            },
            {
                "name": "check_ecs_service",
                "description": "Check ECS service health, task status, and recent events",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cluster": {"type": "string", "description": "ECS cluster name"},
                        "service": {"type": "string", "description": "ECS service name"},
                    },
                    "required": ["cluster", "service"],
                },
            },
            {
                "name": "query_gcp_logs",
                "description": "Query GCP Cloud Logging with advanced filters",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                        "filter_query": {"type": "string", "description": "Cloud Logging filter query"},
                        "hours_back": {"type": "integer", "default": 24},
                    },
                    "required": ["project_id", "filter_query"],
                },
            },
            {
                "name": "check_resource_metrics",
                "description": "Check CPU, memory, disk, and network metrics for a resource",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource_id": {"type": "string", "description": "Cloud resource identifier"},
                        "provider": {"type": "string", "enum": ["aws", "gcp", "azure"]},
                        "metric_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Metrics to query (cpu, memory, disk, network)",
                        },
                    },
                    "required": ["resource_id", "provider"],
                },
            },
            {
                "name": "list_enabled_apis",
                "description": "List all enabled APIs/services in a GCP project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                    },
                    "required": [],
                },
            },
            {
                "name": "list_compute_instances",
                "description": "List all Compute Engine VM instances in a GCP project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                    },
                    "required": [],
                },
            },
            {
                "name": "list_cloud_run_services",
                "description": "List all Cloud Run services in a GCP project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                        "region": {"type": "string", "description": "GCP region (use '-' for all regions)", "default": "-"},
                    },
                    "required": [],
                },
            },
            {
                "name": "list_gke_clusters",
                "description": "List all GKE Kubernetes clusters in a GCP project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                    },
                    "required": [],
                },
            },
            {
                "name": "list_cloud_functions",
                "description": "List all Cloud Functions (v2) in a GCP project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                    },
                    "required": [],
                },
            },
            {
                "name": "list_app_engine_services",
                "description": "List App Engine services in a GCP project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                    },
                    "required": [],
                },
            },
            {
                "name": "query_gcp_logs_for_service_account",
                "description": "Query GCP logs for errors related to a specific service account (useful for CI/CD credential verification)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                        "service_account_email": {"type": "string", "description": "Service account email to search for"},
                        "hours_back": {"type": "integer", "default": 72},
                    },
                    "required": ["project_id", "service_account_email"],
                },
            },
            {
                "name": "query_gcp_deployment_logs",
                "description": "Query GCP logs for deployment-related events (Cloud Run, GKE, Cloud Build) to correlate with CI/CD pipeline runs",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "GCP project ID"},
                        "service_name": {"type": "string", "description": "Cloud Run service or GKE deployment name"},
                        "hours_back": {"type": "integer", "default": 24},
                    },
                    "required": ["project_id"],
                },
            },
            {
                "name": "run_command",
                "description": "Execute a CLI command for diagnostics (gcloud, docker, kubectl, curl, git, etc.). Use this to check live service status, inspect containers, or run cloud CLI commands.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                        "cwd": {"type": "string", "description": "Working directory (optional)"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
                    },
                    "required": ["command"],
                },
            },
        ]

    def _get_gcp_client(self):
        """Create a GCP client using user's credentials if available."""
        from app.mcp.gcp import GCPMCPClient
        user = getattr(self, "_current_user", None) or {}
        return GCPMCPClient(
            user_access_token=user.get("gcp_access_token"),
            project_id=user.get("gcp_project_id"),
        )

    async def _execute_tool(self, tool_name: str, tool_input: dict):
        """Dispatch to MCP cloud tools."""
        from app.mcp.aws import AWSMCPClient

        if tool_name == "query_cloudwatch_logs":
            client = AWSMCPClient()
            return await client.query_cloudwatch(
                log_group=tool_input["log_group"],
                filter_pattern=tool_input.get("filter_pattern", ""),
                hours_back=tool_input.get("hours_back", 24),
            )
        elif tool_name == "check_ecs_service":
            client = AWSMCPClient()
            return await client.check_ecs_service(
                cluster=tool_input["cluster"],
                service=tool_input["service"],
            )
        elif tool_name == "query_gcp_logs":
            client = self._get_gcp_client()
            return await client.query_logs(
                project_id=tool_input.get("project_id", ""),
                filter_query=tool_input["filter_query"],
                hours_back=tool_input.get("hours_back", 24),
            )
        elif tool_name == "check_resource_metrics":
            provider = tool_input.get("provider", "aws")
            if provider == "aws":
                client = AWSMCPClient()
                return await client.get_metrics(
                    resource_id=tool_input["resource_id"],
                    metric_names=tool_input.get("metric_names", ["cpu", "memory"]),
                )
            else:
                client = self._get_gcp_client()
                return await client.get_metrics(
                    resource_id=tool_input["resource_id"],
                    metric_names=tool_input.get("metric_names", ["cpu", "memory"]),
                )
        elif tool_name == "list_enabled_apis":
            client = self._get_gcp_client()
            return await client.list_enabled_apis(project_id=tool_input.get("project_id"))
        elif tool_name == "list_compute_instances":
            client = self._get_gcp_client()
            return await client.list_compute_instances(project_id=tool_input.get("project_id"))
        elif tool_name == "list_cloud_run_services":
            client = self._get_gcp_client()
            return await client.list_cloud_run_services(
                project_id=tool_input.get("project_id"),
                region=tool_input.get("region", "-"),
            )
        elif tool_name == "list_gke_clusters":
            client = self._get_gcp_client()
            return await client.list_gke_clusters(project_id=tool_input.get("project_id"))
        elif tool_name == "list_cloud_functions":
            client = self._get_gcp_client()
            return await client.list_cloud_functions(project_id=tool_input.get("project_id"))
        elif tool_name == "list_app_engine_services":
            client = self._get_gcp_client()
            return await client.list_app_engine_services(project_id=tool_input.get("project_id"))
        elif tool_name == "query_gcp_logs_for_service_account":
            client = self._get_gcp_client()
            sa_email = tool_input["service_account_email"]
            filter_query = f'protoPayload.authenticationInfo.principalEmail="{sa_email}" AND severity>=WARNING'
            return await client.query_logs(
                project_id=tool_input.get("project_id", ""),
                filter_query=filter_query,
                hours_back=tool_input.get("hours_back", 72),
            )
        elif tool_name == "query_gcp_deployment_logs":
            client = self._get_gcp_client()
            service = tool_input.get("service_name", "")
            filters = []
            if service:
                filters.append(f'(resource.labels.service_name="{service}" OR resource.labels.configuration_name="{service}" OR textPayload:"{service}")')
            filters.append('(resource.type="cloud_run_revision" OR resource.type="gke_cluster" OR resource.type="build" OR resource.type="cloud_function")')
            filter_query = " AND ".join(filters)
            return await client.query_logs(
                project_id=tool_input.get("project_id", ""),
                filter_query=filter_query,
                hours_back=tool_input.get("hours_back", 24),
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
