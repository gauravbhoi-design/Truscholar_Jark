"""Commit Analyst Agent — Analyzes git history, diffs, and identifies regressions."""

import structlog

from app.agents.base import BaseAgent

logger = structlog.get_logger()


class CommitAnalystAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "commit_analyst"

    @property
    def system_prompt(self) -> str:
        return """You are a Commit Analyst Agent specializing in git history analysis and regression detection.

Your capabilities:
- Analyze commit histories to identify breaking changes
- Compare diffs between branches, tags, and commits
- Detect regressions introduced by specific commits
- Identify patterns in commit frequency, size, and risk
- Correlate production incidents with recent deployments

When analyzing commits:
1. Fetch recent commit history for the affected timeframe
2. Analyze diffs for risky changes (config changes, DB migrations, dependency updates)
3. Check for common regression patterns
4. Correlate with deployment timestamps
5. Identify the most likely culprit commit

Output format:
- **Suspect Commits**: Ranked list of commits likely to have caused the issue
- **Diff Analysis**: Key changes in each suspect commit
- **Risk Assessment**: Why each change is risky
- **Recommendation**: Revert, hotfix, or investigate further"""

    @property
    def mcp_tools(self) -> list[dict]:
        return [
            {
                "name": "get_commit_history",
                "description": "Get recent commits for a repository or branch",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "branch": {"type": "string", "default": "main"},
                        "limit": {"type": "integer", "default": 20},
                        "since": {"type": "string", "description": "ISO date string to filter from"},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "get_commit_diff",
                "description": "Get the diff for a specific commit",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "sha": {"type": "string", "description": "Commit SHA"},
                    },
                    "required": ["repo", "sha"],
                },
            },
            {
                "name": "compare_refs",
                "description": "Compare two branches, tags, or commits",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "base": {"type": "string", "description": "Base ref (branch, tag, or SHA)"},
                        "head": {"type": "string", "description": "Head ref to compare"},
                    },
                    "required": ["repo", "base", "head"],
                },
            },
            {
                "name": "get_pull_request",
                "description": "Get details of a pull request including review comments",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "pr_number": {"type": "integer"},
                    },
                    "required": ["repo", "pr_number"],
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_input: dict):
        """Dispatch to Git MCP tools."""
        from app.mcp.github import GitHubMCPClient

        user_token = getattr(self, "_current_user", {}).get("github_token") if getattr(self, "_current_user", None) else None
        github = GitHubMCPClient(user_token=user_token)

        if tool_name == "get_commit_history":
            return await github.get_commits(
                repo=tool_input["repo"],
                branch=tool_input.get("branch", "main"),
                limit=tool_input.get("limit", 20),
                since=tool_input.get("since"),
            )
        elif tool_name == "get_commit_diff":
            return await github.get_commit_diff(
                repo=tool_input["repo"],
                sha=tool_input["sha"],
            )
        elif tool_name == "compare_refs":
            return await github.compare(
                repo=tool_input["repo"],
                base=tool_input["base"],
                head=tool_input["head"],
            )
        elif tool_name == "get_pull_request":
            return await github.get_pull_request(
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
            )

        return await super()._execute_tool(tool_name, tool_input)
