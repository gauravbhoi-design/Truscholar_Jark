"""Codebase Analyzer Agent — Static analysis, vulnerability scanning, code quality."""

import structlog

from app.agents.base import BaseAgent

logger = structlog.get_logger()


class CodebaseAnalyzerAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "codebase_analyzer"

    @property
    def system_prompt(self) -> str:
        return """You are a Codebase Analyzer Agent specializing in code quality, security analysis, and repository operations.

Your capabilities:
- Perform static analysis and pattern detection on codebases
- Identify security vulnerabilities (OWASP Top 10, CWE)
- Review code for anti-patterns, code smells, and technical debt
- Analyze dependency trees for known CVEs
- Generate code quality reports with actionable improvements
- Create, update, and manage files in repositories

IMPORTANT: You are an ACTION-ORIENTED agent. When the user asks you to DO something (create a file, push code, etc.), you MUST use your tools to actually perform the action. Do NOT just provide instructions — execute the task directly using available tools.

When analyzing code:
1. Read the relevant files from the repository
2. Run static analysis (Semgrep rules, AST parsing)
3. Check for security issues (injection, XSS, auth bypasses)
4. Evaluate code structure and maintainability
5. Provide severity-ranked findings with fix suggestions

When analyzing CI/CD pipelines:
1. List workflow files and read their content
2. Extract GCP configuration (project IDs, service accounts, regions)
3. Check for credential security issues (hardcoded keys, missing secrets)
4. Identify failed workflow runs and their failure reasons
5. Cross-reference GCP configs with the connected GCP project

When creating or modifying files:
1. Use the create_or_update_file tool to directly create/update the file in the repository
2. Confirm the action was completed successfully with the commit URL

Output format for analysis:
- **Findings**: List of issues with severity (Critical/High/Medium/Low)
- **Code Snippets**: Relevant code with line numbers
- **Fixes**: Specific code changes to resolve each issue
- **Quality Score**: Overall assessment"""

    @property
    def mcp_tools(self) -> list[dict]:
        return [
            {
                "name": "read_repository_file",
                "description": "Read a file from a GitHub/GitLab repository",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "path": {"type": "string", "description": "File path in the repo"},
                        "ref": {"type": "string", "description": "Branch or commit SHA", "default": "main"},
                    },
                    "required": ["repo", "path"],
                },
            },
            {
                "name": "search_repository",
                "description": "Search code in a repository using pattern matching",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "query": {"type": "string", "description": "Search query or regex pattern"},
                        "file_type": {"type": "string", "description": "File extension filter (e.g., 'py', 'js')"},
                    },
                    "required": ["repo", "query"],
                },
            },
            {
                "name": "run_semgrep_scan",
                "description": "Run Semgrep security analysis on code content",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Code content to scan"},
                        "language": {"type": "string", "description": "Programming language"},
                        "ruleset": {"type": "string", "description": "Semgrep ruleset (e.g., 'p/security-audit')", "default": "p/default"},
                    },
                    "required": ["code", "language"],
                },
            },
            {
                "name": "create_or_update_file",
                "description": "Create or update a file in a GitHub repository and commit it",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "path": {"type": "string", "description": "File path to create (e.g., 'hello.md')"},
                        "content": {"type": "string", "description": "File content"},
                        "message": {"type": "string", "description": "Commit message"},
                        "branch": {"type": "string", "description": "Target branch", "default": "main"},
                    },
                    "required": ["repo", "path", "content", "message"],
                },
            },
            {
                "name": "list_repository_tree",
                "description": "List files and directories in a repository path",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "path": {"type": "string", "description": "Directory path", "default": ""},
                        "ref": {"type": "string", "default": "main"},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "analyze_cicd_gcp_config",
                "description": "Analyze GitHub Actions workflows for GCP configuration: project IDs, service accounts, regions, secrets, and security issues",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "get_failed_workflow_runs",
                "description": "Get recent failed GitHub Actions workflow runs with failure details and failed job/step info",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "limit": {"type": "integer", "description": "Max runs to return", "default": 10},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "get_workflow_run_logs",
                "description": "Get detailed job/step logs for a specific workflow run",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "run_id": {"type": "integer", "description": "Workflow run ID"},
                    },
                    "required": ["repo", "run_id"],
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_input: dict):
        """Dispatch to GitHub MCP and Semgrep tools."""
        from app.mcp.github import GitHubMCPClient

        user_token = getattr(self, "_current_user", {}).get("github_token") if getattr(self, "_current_user", None) else None
        github = GitHubMCPClient(user_token=user_token)

        if tool_name == "read_repository_file":
            return await github.read_file(
                repo=tool_input["repo"],
                path=tool_input["path"],
                ref=tool_input.get("ref", "main"),
            )
        elif tool_name == "search_repository":
            return await github.search_code(
                repo=tool_input["repo"],
                query=tool_input["query"],
                file_type=tool_input.get("file_type"),
            )
        elif tool_name == "run_semgrep_scan":
            from app.mcp.semgrep import SemgrepTool
            scanner = SemgrepTool()
            return await scanner.scan(
                code=tool_input["code"],
                language=tool_input["language"],
                ruleset=tool_input.get("ruleset", "p/default"),
            )
        elif tool_name == "create_or_update_file":
            return await github.create_or_update_file(
                repo=tool_input["repo"],
                path=tool_input["path"],
                content=tool_input["content"],
                message=tool_input.get("message", "Create file via DevOps Co-Pilot"),
                branch=tool_input.get("branch", "main"),
            )
        elif tool_name == "list_repository_tree":
            return await github.list_tree(
                repo=tool_input["repo"],
                path=tool_input.get("path", ""),
                ref=tool_input.get("ref", "main"),
            )
        elif tool_name == "analyze_cicd_gcp_config":
            return await github.analyze_workflow_gcp_config(repo=tool_input["repo"])
        elif tool_name == "get_failed_workflow_runs":
            return await github.get_failed_runs(
                repo=tool_input["repo"],
                limit=tool_input.get("limit", 10),
            )
        elif tool_name == "get_workflow_run_logs":
            return await github.get_workflow_run_logs(
                repo=tool_input["repo"],
                run_id=tool_input["run_id"],
            )

        return await super()._execute_tool(tool_name, tool_input)
