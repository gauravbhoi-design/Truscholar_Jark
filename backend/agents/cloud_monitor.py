"""Cloud Monitor Agent — Metrics, uptime, cost."""

from typing import Dict, Any, List
from .base import BaseAgent
from integrations.gcp_client import gcp_client
from memory import memory


class CloudMonitorAgent(BaseAgent):
    AGENT_TYPE = "cloud_monitor"
    AGENT_NAME = "Cloud Monitor"
    AGENT_ICON = "☁️"
    AGENT_COLOR = "#27AE60"
    AGENT_DESCRIPTION = "Metrics, uptime, cost"
    AGENT_CATEGORY = "Infrastructure"

    def get_system_prompt(self) -> str:
        return """You are an AI Cloud Monitor agent inside a Docker container with CLI access.
You have: gcloud, kubectl, docker, curl, jq, and standard Linux tools.

YOUR SPECIALIZATION: Cloud infrastructure monitoring.
- Monitor GCP services: Cloud Run, GKE, Compute Engine
- Track CPU, memory, disk usage
- Analyze cost and billing trends
- Check service health and uptime
- Monitor Kubernetes pod status

EXECUTION MODEL:
- Run shell commands ONE AT A TIME.
- Use gcloud for GCP resources.
- Use kubectl for K8s monitoring.

RESPONSE FORMAT — ONLY valid JSON:
{"action":"run","command":"...","description":"brief why","risk_level":"low|medium|high|critical","thinking":"1-2 sentences max"}
{"action":"done","summary":"what you accomplished","thinking":"brief"}

RULES:
1. ONE command at a time.
2. Focus on actionable metrics.
3. Flag anything over 80% utilization.
4. Track cost anomalies.
5. Report on service health status."""

    async def generate_report(self, repo_id: str = None, context: dict = None) -> Dict[str, Any]:
        items = []
        findings = []

        if gcp_client.is_connected:
            services = await gcp_client.list_all_services()
            running = sum(1 for s in services if s.get("status") == "running")
            items = [
                {"label": "Total Services", "value": len(services), "severity": "low"},
                {"label": "Running", "value": running, "severity": "low"},
                {"label": "Stopped/Error", "value": len(services) - running, "severity": "high" if len(services) - running > 0 else "low"},
                {"label": "GCP Project", "value": gcp_client.project_id or "—", "severity": "low"},
                {"label": "Region", "value": gcp_client.region, "severity": "low"},
            ]
            summary = f"{running}/{len(services)} services running"

            for svc in services:
                if svc.get("status") != "running":
                    findings.append(f"{svc['name']} ({svc['service_type']}) is {svc.get('status', 'unknown')}")
        else:
            items = [
                {"label": "GCP Status", "value": "Not connected", "severity": "warning"},
                {"label": "Services", "value": "—", "severity": "low"},
            ]
            summary = "Connect GCP to see infrastructure metrics"

        report = {"summary": summary, "items": items, "findings": findings}
        if repo_id:
            self.save_report(repo_id, summary, items, findings)
        return report

    async def generate_plan(self, command: str, repo_id: str = None, context: dict = None) -> List[Dict[str, Any]]:
        cmd_lower = command.lower()
        if "cost" in cmd_lower or "billing" in cmd_lower:
            steps = [
                {"id": "s1", "text": "Fetch billing data from GCP", "status": "pending"},
                {"id": "s2", "text": "Analyze cost by service", "status": "pending"},
                {"id": "s3", "text": "Identify cost anomalies", "status": "pending"},
                {"id": "s4", "text": "Generate optimization recommendations", "status": "pending"},
            ]
        elif "deploy" in cmd_lower:
            steps = [
                {"id": "s1", "text": "Check current deployment status", "status": "pending"},
                {"id": "s2", "text": "Validate deployment config", "status": "pending"},
                {"id": "s3", "text": "Execute deployment", "status": "pending"},
                {"id": "s4", "text": "Verify health checks", "status": "pending"},
                {"id": "s5", "text": "Monitor for errors post-deploy", "status": "pending"},
            ]
        else:
            steps = [
                {"id": "s1", "text": "List all cloud services", "status": "pending"},
                {"id": "s2", "text": "Check health and metrics", "status": "pending"},
                {"id": "s3", "text": "Generate infrastructure report", "status": "pending"},
            ]

        if repo_id:
            self.save_plan(repo_id, steps)
        return steps
