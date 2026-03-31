"""Test Runner Agent — Clone, build, test, CI/CD."""

from typing import Dict, Any, List
from .base import BaseAgent
from integrations.github_client import github_client
from memory import memory


class TestRunnerAgent(BaseAgent):
    AGENT_TYPE = "test_runner"
    AGENT_NAME = "Test Runner"
    AGENT_ICON = "🧪"
    AGENT_COLOR = "#2980B9"
    AGENT_DESCRIPTION = "Clone, build, test, CI/CD"
    AGENT_CATEGORY = "CI/CD"

    def get_system_prompt(self) -> str:
        return """You are an AI Test Runner agent inside a Docker container with CLI access.
You have: gh, git, python3, node/npm, pip, pytest, jest, make, docker, and standard Linux tools.

YOUR SPECIALIZATION: Building, testing, and CI/CD.
- Clone repos and run full test suites
- Detect test failures and diagnose root causes
- Generate missing tests for uncovered code
- Run linters and static analysis
- Build projects and verify they compile

EXECUTION MODEL:
- Run shell commands ONE AT A TIME.
- pip install requires --break-system-packages flag.

RESPONSE FORMAT — ONLY valid JSON:
{"action":"run","command":"...","description":"brief why","risk_level":"low|medium|high|critical","thinking":"1-2 sentences max"}
{"action":"done","summary":"what you accomplished","thinking":"brief"}

RULES:
1. ONE command at a time.
2. Always install dependencies first (pip install -r requirements.txt, npm install).
3. Detect the test framework automatically (pytest, jest, mocha, go test).
4. Report specific test failures with file names and line numbers.
5. If tests are missing, identify which functions lack coverage."""

    async def generate_report(self, repo_id: str = None, context: dict = None) -> Dict[str, Any]:
        if not repo_id:
            return {"summary": "Select a repo to see test report", "items": [], "findings": []}

        owner = context.get("owner", "") if context else ""
        repo = context.get("repo", "") if context else ""
        items = []
        findings = []

        if github_client.is_connected and owner and repo:
            ci = await github_client.get_ci_status(owner, repo)
            ci_status = ci.get("status", "unknown")

            items = [
                {"label": "Build Status", "value": ci_status, "severity": "high" if ci_status == "failure" else "low"},
                {"label": "Total Tests", "value": "—", "severity": "low"},
                {"label": "Passing", "value": "—", "severity": "low"},
                {"label": "Failing", "value": "—", "severity": "low"},
                {"label": "Coverage", "value": "—", "severity": "low"},
                {"label": "Last CI Run", "value": ci.get("created_at", "—")[:10] if ci.get("created_at") else "—", "severity": "low"},
            ]
            summary = f"CI: {ci_status} on {repo}"
            if ci_status == "failure":
                findings.append(f"Latest CI run failed: {ci.get('name', 'workflow')}")
        else:
            items = [
                {"label": "Build Status", "value": "—", "severity": "low"},
                {"label": "Total Tests", "value": "—", "severity": "low"},
            ]
            summary = "Connect GitHub or run tests to see data"

        report = {"summary": summary, "items": items, "findings": findings}
        if repo_id:
            self.save_report(repo_id, summary, items, findings)
        return report

    async def generate_plan(self, command: str, repo_id: str = None, context: dict = None) -> List[Dict[str, Any]]:
        cmd_lower = command.lower()
        if "test" in cmd_lower or "build" in cmd_lower:
            steps = [
                {"id": "s1", "text": "Clone repository", "status": "pending"},
                {"id": "s2", "text": "Detect language and framework", "status": "pending"},
                {"id": "s3", "text": "Install dependencies", "status": "pending"},
                {"id": "s4", "text": "Run test suite", "status": "pending"},
                {"id": "s5", "text": "Collect coverage data", "status": "pending"},
                {"id": "s6", "text": "Analyze failures and generate report", "status": "pending"},
            ]
        else:
            steps = [
                {"id": "s1", "text": "Clone and setup project", "status": "pending"},
                {"id": "s2", "text": "Run full test suite", "status": "pending"},
                {"id": "s3", "text": "Generate test report", "status": "pending"},
            ]

        if repo_id:
            self.save_plan(repo_id, steps)
        return steps
