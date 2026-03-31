"""Log Monitor Agent — Errors, RCA, alerts."""

from typing import Dict, Any, List
from .base import BaseAgent
from memory import memory


class LogMonitorAgent(BaseAgent):
    AGENT_TYPE = "log_monitor"
    AGENT_NAME = "Log Monitor"
    AGENT_ICON = "📊"
    AGENT_COLOR = "#D4A017"
    AGENT_DESCRIPTION = "Errors, RCA, alerts"
    AGENT_CATEGORY = "Monitoring"

    def get_system_prompt(self) -> str:
        return """You are an AI Log Monitor agent inside a Docker container with CLI access.
You have: gcloud, kubectl, docker, grep, awk, jq, curl, and standard Linux tools.

YOUR SPECIALIZATION: Log analysis, error detection, root cause analysis.
- Fetch and analyze logs from Cloud Run, GKE, and compute instances
- Detect error patterns and anomalies
- Perform root cause analysis on failures
- Set up alerts and monitoring
- Correlate errors across services

EXECUTION MODEL:
- Run shell commands ONE AT A TIME.
- Use gcloud logging read for GCP logs.
- Use kubectl logs for K8s logs.

RESPONSE FORMAT — ONLY valid JSON:
{"action":"run","command":"...","description":"brief why","risk_level":"low|medium|high|critical","thinking":"1-2 sentences max"}
{"action":"done","summary":"what you accomplished","thinking":"brief"}

RULES:
1. ONE command at a time.
2. Start with recent logs (last 1-6 hours).
3. Filter by severity (ERROR, WARNING, CRITICAL).
4. Look for patterns: repeated errors, cascading failures, resource exhaustion.
5. Include timestamps and service names in findings."""

    async def generate_report(self, repo_id: str = None, context: dict = None) -> Dict[str, Any]:
        # Log reports are based on services, not repos
        items = [
            {"label": "Errors (24h)", "value": "—", "severity": "low"},
            {"label": "Warnings (24h)", "value": "—", "severity": "low"},
            {"label": "Top Error", "value": "—", "severity": "low"},
            {"label": "Error Rate", "value": "—", "severity": "low"},
            {"label": "Last Alert", "value": "—", "severity": "low"},
        ]

        findings = memory.get_findings(5)
        finding_texts = [f["text"] for f in findings if f.get("agent") == self.AGENT_TYPE]

        summary = "Run log analysis to see real-time data"
        report = {"summary": summary, "items": items, "findings": finding_texts}
        if repo_id:
            self.save_report(repo_id, summary, items, finding_texts)
        return report

    async def generate_plan(self, command: str, repo_id: str = None, context: dict = None) -> List[Dict[str, Any]]:
        cmd_lower = command.lower()
        if "error" in cmd_lower or "rca" in cmd_lower or "root cause" in cmd_lower:
            steps = [
                {"id": "s1", "text": "Fetch recent error logs", "status": "pending"},
                {"id": "s2", "text": "Group errors by type and frequency", "status": "pending"},
                {"id": "s3", "text": "Identify top error patterns", "status": "pending"},
                {"id": "s4", "text": "Trace error origins across services", "status": "pending"},
                {"id": "s5", "text": "Generate root cause analysis report", "status": "pending"},
            ]
        else:
            steps = [
                {"id": "s1", "text": "Fetch logs from all services", "status": "pending"},
                {"id": "s2", "text": "Filter and analyze", "status": "pending"},
                {"id": "s3", "text": "Generate monitoring report", "status": "pending"},
            ]

        if repo_id:
            self.save_plan(repo_id, steps)
        return steps
