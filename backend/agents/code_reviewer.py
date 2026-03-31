"""Code Reviewer Agent — PRs, bugs, code quality fixes."""

from typing import Dict, Any, List
from .base import BaseAgent
from integrations.github_client import github_client
from memory import memory


class CodeReviewerAgent(BaseAgent):
    AGENT_TYPE = "code_reviewer"
    AGENT_NAME = "Code Reviewer"
    AGENT_ICON = "🔍"
    AGENT_COLOR = "#C0392B"
    AGENT_DESCRIPTION = "PRs, bugs, code quality, fixes"
    AGENT_CATEGORY = "Analysis"

    def get_system_prompt(self) -> str:
        return """You are an AI Code Review agent running inside a Docker container with CLI access.
You have: gh, git, python3, node/npm, pip, grep, find, curl, and standard Linux tools.

YOUR SPECIALIZATION: Code review, bug detection, code quality analysis.
- Review pull requests and suggest improvements
- Find bugs, security issues, and anti-patterns
- Analyze code coverage and test quality
- Suggest fixes and create fix branches

EXECUTION MODEL:
- Run shell commands ONE AT A TIME.
- After each command you see: stdout, stderr, exit code, and YOUR CURRENT WORKING DIRECTORY.
- pip install requires --break-system-packages flag.

RESPONSE FORMAT — ONLY valid JSON:
{"action":"run","command":"...","description":"brief why","risk_level":"low|medium|high|critical","thinking":"1-2 sentences max"}
{"action":"done","summary":"what you accomplished","thinking":"brief"}
{"action":"ask_human","question":"what you need","thinking":"brief"}

RISK LEVELS: low=read-only, medium=local changes, high=remote writes, critical=destructive

RULES:
1. ONE command at a time.
2. Read code before modifying.
3. After changes, verify (test, diff).
4. Never modify main/master directly — branch first.
5. When reviewing PRs, check: logic errors, security, performance, style, tests."""

    async def generate_report(self, repo_id: str = None, context: dict = None) -> Dict[str, Any]:
        """Generate code review report for a repo."""
        if not repo_id or not context:
            return {"summary": "Select a repo to see code review report", "items": [], "findings": []}

        owner = context.get("owner", "")
        repo = context.get("repo", "")
        items = []
        findings = []

        if github_client.is_connected and owner and repo:
            prs = await github_client.list_prs(owner, repo)
            issues = await github_client.list_issues(owner, repo)
            ci = await github_client.get_ci_status(owner, repo)

            items = [
                {"label": "Open PRs", "value": len(prs), "severity": "high" if len(prs) > 3 else "low"},
                {"label": "Open Issues", "value": len(issues), "severity": "high" if len(issues) > 8 else "medium" if len(issues) > 3 else "low"},
                {"label": "CI Status", "value": ci.get("status", "unknown"), "severity": "high" if ci.get("status") == "failure" else "low"},
                {"label": "Draft PRs", "value": sum(1 for p in prs if p.get("draft")), "severity": "low"},
                {"label": "Stale PRs (>7d)", "value": 0, "severity": "warning"},
            ]

            for pr in prs[:3]:
                findings.append(f"PR #{pr['number']}: {pr['title']} ({pr['head_branch']} → {pr['base_branch']})")

            summary = f"{len(prs)} open PRs, {len(issues)} open issues on {repo}"
        else:
            items = [
                {"label": "Open PRs", "value": "—", "severity": "low"},
                {"label": "Open Issues", "value": "—", "severity": "low"},
                {"label": "CI Status", "value": "—", "severity": "low"},
            ]
            summary = "Connect GitHub to see live data"

        report = {"summary": summary, "items": items, "findings": findings}
        if repo_id:
            self.save_report(repo_id, summary, items, findings)
        memory.update_agent_state(self.AGENT_TYPE, {"last_report": repo_id})
        return report

    async def generate_plan(self, command: str, repo_id: str = None, context: dict = None) -> List[Dict[str, Any]]:
        cmd_lower = command.lower()
        steps = []

        if "review" in cmd_lower or "pr" in cmd_lower:
            steps = [
                {"id": "s1", "text": "Clone repository and checkout PR branch", "status": "pending"},
                {"id": "s2", "text": "List changed files and diff", "status": "pending"},
                {"id": "s3", "text": "Analyze code changes for bugs and issues", "status": "pending"},
                {"id": "s4", "text": "Run tests on PR branch", "status": "pending"},
                {"id": "s5", "text": "Generate review summary with findings", "status": "pending"},
            ]
        elif "bug" in cmd_lower or "fix" in cmd_lower:
            steps = [
                {"id": "s1", "text": "Clone repository", "status": "pending"},
                {"id": "s2", "text": "Analyze codebase for bugs", "status": "pending"},
                {"id": "s3", "text": "Create fix branch", "status": "pending"},
                {"id": "s4", "text": "Apply fixes", "status": "pending"},
                {"id": "s5", "text": "Run tests to verify", "status": "pending"},
                {"id": "s6", "text": "Push and create PR", "status": "pending"},
            ]
        else:
            steps = [
                {"id": "s1", "text": "Clone and analyze repository", "status": "pending"},
                {"id": "s2", "text": "Run code quality checks", "status": "pending"},
                {"id": "s3", "text": "Generate findings report", "status": "pending"},
            ]

        if repo_id:
            self.save_plan(repo_id, steps)
        return steps
