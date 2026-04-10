"""Terminal MCP Client — Gives agents sandboxed CLI command execution.

Supports:
- Host commands (git, gcloud, terraform, npm, etc.)
- Docker container commands (docker exec, logs, inspect, stats)
- Kubernetes commands (kubectl)

Security: Commands run with timeout, blocked dangerous commands,
and no access to modify secrets or credentials.
"""

import asyncio
import shlex

import structlog

logger = structlog.get_logger()

# Commands that are NEVER allowed
BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", "shutdown",
    "reboot", "halt", "init 0", "init 6", "kill -9 1",
    "chmod -R 777 /", "passwd", "useradd", "userdel",
    "curl | sh", "curl | bash", "wget | sh", "wget | bash",
    "docker rm -f", "docker system prune -a",
}

# Only these command prefixes are allowed
ALLOWED_COMMANDS = [
    "ls", "cat", "head", "tail", "grep", "find", "wc", "sort", "uniq",
    "git", "gh", "docker", "kubectl", "gcloud", "gsutil", "terraform",
    "npm", "node", "python", "python3", "pip", "pytest",
    "curl", "wget", "jq",
    "df", "du", "free", "top", "uptime", "whoami", "hostname", "uname",
    "echo", "date", "env", "printenv", "pwd",
    "psql", "redis-cli", "mongosh", "mongo",
    "ruff", "mypy", "eslint", "tsc",
    "ping", "nslookup", "dig", "traceroute", "netstat", "ss",
]

# Docker subcommands that are allowed
ALLOWED_DOCKER_CMDS = [
    "ps", "logs", "inspect", "stats", "top", "exec",
    "images", "network", "volume", "compose",
    "port", "diff", "history",
]

# Docker subcommands that are blocked
BLOCKED_DOCKER_CMDS = [
    "rm", "rmi", "prune", "kill", "stop", "pause",
    "push", "pull", "build", "create", "run",
    "swarm", "service", "stack", "secret",
]

MAX_OUTPUT_LENGTH = 15000  # Characters
DEFAULT_TIMEOUT = 30  # Seconds


class TerminalMCPClient:
    """MCP-compatible client for executing CLI commands with safety guardrails.

    Agents use this to run diagnostics, check container status, view logs,
    and interact with Docker containers — and to drive `gh` / `gcloud` /
    `kubectl` for any operation that no specialized MCP tool covers.

    Per-session workdir tracking lets a sequence of commands feel like an
    interactive shell: `cd ./repo` followed by `ls` runs `ls` inside `./repo`.

    Args:
        working_dir: Default working directory for commands.
        timeout: Default timeout in seconds.
        gcp_access_token: User's OAuth access token for gcloud commands.
            When set, gcloud runs as the user (not the service account).
        github_token: User's GitHub PAT or installation token. When set,
            it's exported as both GITHUB_TOKEN and GH_TOKEN so `gh` and
            `git` commands authenticate as the user.
        gcp_project_id: Default GCP project for gcloud (CLOUDSDK_CORE_PROJECT).
        session_id: When set, workdir mutations persist across calls so
            `cd subdir` followed by `ls` works as expected.
    """

    # Class-level workdir cache keyed by session_id. Process-local — fine
    # for single-instance Cloud Run; for multi-instance we'd push this to
    # Redis. Each entry is just a path string.
    _session_workdirs: dict[str, str] = {}

    def __init__(
        self,
        working_dir: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        gcp_access_token: str | None = None,
        github_token: str | None = None,
        gcp_project_id: str | None = None,
        session_id: str | None = None,
    ):
        self.working_dir = working_dir
        self.timeout = timeout
        self.gcp_access_token = gcp_access_token
        self.github_token = github_token
        self.gcp_project_id = gcp_project_id
        self.session_id = session_id

    def _is_command_allowed(self, command: str) -> tuple[bool, str]:
        """Check if a command is safe to execute."""
        cmd_lower = command.strip().lower()

        # Check blocked commands
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return False, f"Command blocked for safety: contains '{blocked}'"

        # Block pipe to shell (command injection)
        if "| sh" in cmd_lower or "| bash" in cmd_lower or "; rm" in cmd_lower:
            return False, "Piping to shell is not allowed"

        # Parse base command
        try:
            cmd_parts = shlex.split(command)
        except ValueError:
            cmd_parts = command.split()
        if not cmd_parts:
            return False, "Empty command"

        base_cmd = cmd_parts[0].split("/")[-1]

        # Docker-specific checks
        if base_cmd == "docker" and len(cmd_parts) > 1:
            docker_sub = cmd_parts[1]
            if docker_sub in BLOCKED_DOCKER_CMDS:
                return False, f"Docker '{docker_sub}' is blocked for safety. Allowed: {', '.join(ALLOWED_DOCKER_CMDS)}"
            if docker_sub not in ALLOWED_DOCKER_CMDS:
                return False, f"Docker '{docker_sub}' is not in the allowed list. Allowed: {', '.join(ALLOWED_DOCKER_CMDS)}"
            return True, "OK"

        # docker-compose / docker compose
        if base_cmd in ("docker-compose",) or (base_cmd == "docker" and len(cmd_parts) > 1 and cmd_parts[1] == "compose"):
            return True, "OK"

        # General command check
        if not any(base_cmd.startswith(allowed) for allowed in ALLOWED_COMMANDS):
            return False, f"Command '{base_cmd}' is not in the allowed list. Allowed: {', '.join(ALLOWED_COMMANDS[:15])}..."

        return True, "OK"

    def _resolve_session_cwd(self, override: str | None) -> str | None:
        """Compute the effective cwd for a call, honoring session state."""
        if override:
            return override
        if self.session_id and self.session_id in self._session_workdirs:
            return self._session_workdirs[self.session_id]
        return self.working_dir

    def _track_cd(self, command: str, current_cwd: str | None) -> None:
        """If the command was a successful `cd`, update session workdir.

        Parses locally — never re-executes, never trusts the shell.
        """
        if not self.session_id:
            return

        import os
        import re

        # Find any `cd <target>` segments in the command
        targets = re.findall(r"(?:^|;|&&|\|\|)\s*cd\s+([^\s;&|]+)", command)
        if not targets:
            return

        wd = current_cwd or os.getcwd()
        for target in targets:
            target = target.strip().strip("'\"")
            if not target or target == ".":
                continue
            if target == "~":
                wd = os.path.expanduser("~")
            elif target.startswith("/"):
                wd = target
            elif target == "..":
                wd = os.path.dirname(wd.rstrip("/")) or "/"
            else:
                wd = os.path.normpath(os.path.join(wd, target))

        self._session_workdirs[self.session_id] = wd
        logger.info("Session workdir updated", session=self.session_id, cwd=wd)

    async def execute(self, command: str, timeout: int | None = None, cwd: str | None = None) -> dict:
        """Execute a CLI command and return output.

        Args:
            command: Shell command to execute
            timeout: Max seconds to wait (default 30)
            cwd: Working directory (overrides session workdir for this call)
        """
        effective_timeout = timeout or self.timeout
        effective_cwd = self._resolve_session_cwd(cwd)

        # Safety check
        allowed, reason = self._is_command_allowed(command)
        if not allowed:
            logger.warning("Command blocked", command=command[:100], reason=reason)
            return {"error": reason, "exit_code": -1, "stdout": "", "stderr": reason}

        logger.info("Executing command", command=command[:100], cwd=effective_cwd, session=self.session_id)

        # Build per-call env: inherit, then layer in user-scoped credentials
        # so gh/gcloud authenticate as the requesting user, not the service account.
        import os
        env = os.environ.copy()
        cmd_stripped = command.strip()

        if self.gcp_access_token and cmd_stripped.startswith(("gcloud", "gsutil")):
            env["CLOUDSDK_AUTH_ACCESS_TOKEN"] = self.gcp_access_token
        if self.gcp_project_id:
            env["CLOUDSDK_CORE_PROJECT"] = self.gcp_project_id

        if self.github_token and cmd_stripped.startswith(("gh", "git")):
            # gh reads GH_TOKEN, git reads GITHUB_TOKEN via credential helper.
            env["GH_TOKEN"] = self.github_token
            env["GITHUB_TOKEN"] = self.github_token

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=effective_cwd,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )

            stdout_str = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_LENGTH]
            stderr_str = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_LENGTH]

            # Track cd mutations only on successful commands
            if proc.returncode == 0:
                self._track_cd(command, effective_cwd)

            return {
                "exit_code": proc.returncode,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "command": command,
                "cwd": effective_cwd,
                "truncated": len(stdout) > MAX_OUTPUT_LENGTH or len(stderr) > MAX_OUTPUT_LENGTH,
            }

        except TimeoutError:
            return {
                "error": f"Command timed out after {effective_timeout}s",
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Timeout after {effective_timeout} seconds",
                "command": command,
            }
        except Exception as e:
            logger.error("Command execution failed", command=command[:100], error=str(e))
            return {"error": str(e), "exit_code": -1, "stdout": "", "stderr": str(e), "command": command}

    @classmethod
    def reset_session(cls, session_id: str) -> None:
        """Drop a session's workdir state (call when a task ends)."""
        cls._session_workdirs.pop(session_id, None)

    # ─── Docker Convenience Methods ────────────────────────────────────

    async def docker_ps(self, all_containers: bool = False) -> dict:
        """List Docker containers with status, ports, and resource usage."""
        flag = "-a" if all_containers else ""
        return await self.execute(
            f"docker ps {flag} --format 'table {{{{.ID}}}}\\t{{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}\\t{{{{.Ports}}}}'"
        )

    async def docker_logs(self, container: str, lines: int = 100, since: str | None = None) -> dict:
        """Get logs from a Docker container.

        Args:
            container: Container name or ID
            lines: Number of tail lines (default 100)
            since: Time filter (e.g., '10m', '1h', '2024-01-01')
        """
        cmd = f"docker logs --tail {lines}"
        if since:
            cmd += f" --since {since}"
        cmd += f" {container}"
        return await self.execute(cmd, timeout=15)

    async def docker_inspect(self, container: str) -> dict:
        """Inspect a Docker container for config, network, mounts, env vars."""
        # Format output to show the most useful info, not the full JSON blob
        return await self.execute(
            f"docker inspect --format '"
            f"Name: {{{{.Name}}}}\n"
            f"Image: {{{{.Config.Image}}}}\n"
            f"Status: {{{{.State.Status}}}}\n"
            f"Started: {{{{.State.StartedAt}}}}\n"
            f"RestartCount: {{{{.RestartCount}}}}\n"
            f"Ports: {{{{json .NetworkSettings.Ports}}}}\n"
            f"Mounts: {{{{json .Mounts}}}}\n"
            f"Env: {{{{json .Config.Env}}}}' {container}"
        )

    async def docker_stats(self, container: str | None = None) -> dict:
        """Get CPU/memory/network stats for containers."""
        target = container or ""
        return await self.execute(
            f"docker stats --no-stream --format 'table {{{{.Name}}}}\\t{{{{.CPUPerc}}}}\\t{{{{.MemUsage}}}}\\t{{{{.NetIO}}}}\\t{{{{.BlockIO}}}}' {target}",
            timeout=10,
        )

    async def docker_exec(self, container: str, command: str, timeout: int = 30) -> dict:
        """Execute a command inside a running Docker container.

        Args:
            container: Container name or ID
            command: Command to run inside the container
        """
        # Safety: don't allow shell-escape inside docker exec
        cmd_lower = command.lower()
        for blocked in ("rm -rf", "mkfs", "shutdown", "reboot", "passwd"):
            if blocked in cmd_lower:
                return {"error": f"Command '{blocked}' is blocked inside containers too"}

        return await self.execute(
            f"docker exec {container} {command}",
            timeout=min(timeout, 60),
        )

    async def docker_compose_ps(self, compose_file: str | None = None) -> dict:
        """List docker-compose services and their status."""
        cmd = "docker compose ps"
        if compose_file:
            cmd = f"docker compose -f {compose_file} ps"
        return await self.execute(cmd)

    async def docker_compose_logs(self, service: str | None = None, lines: int = 50, compose_file: str | None = None) -> dict:
        """Get docker-compose service logs."""
        cmd = "docker compose"
        if compose_file:
            cmd += f" -f {compose_file}"
        cmd += f" logs --tail {lines}"
        if service:
            cmd += f" {service}"
        return await self.execute(cmd, timeout=15)

    async def docker_network_ls(self) -> dict:
        """List Docker networks."""
        return await self.execute("docker network ls --format 'table {{.Name}}\t{{.Driver}}\t{{.Scope}}'")

    async def docker_volume_ls(self) -> dict:
        """List Docker volumes."""
        return await self.execute("docker volume ls --format 'table {{.Name}}\t{{.Driver}}\t{{.Mountpoint}}'")

    # ─── Service Health Checks ─────────────────────────────────────────

    async def check_service_health(self, url: str) -> dict:
        """Check if a service endpoint is healthy."""
        return await self.execute(
            f"curl -sf -o /dev/null -w 'HTTP %{{http_code}} | Time: %{{time_total}}s | Size: %{{size_download}} bytes' {url}",
            timeout=10,
        )

    async def check_postgres(self, host: str = "localhost", port: int = 5432, db: str = "devops_copilot", user: str = "copilot") -> dict:
        """Check if PostgreSQL is reachable."""
        return await self.execute(
            f"psql -h {host} -p {port} -U {user} -d {db} -c 'SELECT version();'",
            timeout=10,
        )

    async def check_redis(self, url: str = "redis://localhost:6379") -> dict:
        """Check if Redis is reachable."""
        return await self.execute(f"redis-cli -u {url} ping", timeout=5)

    # ─── Git Shortcuts ─────────────────────────────────────────────────

    async def git_status(self, repo_path: str = ".") -> dict:
        return await self.execute(f"git -C {repo_path} status --short")

    async def git_log(self, repo_path: str = ".", limit: int = 10) -> dict:
        return await self.execute(f"git -C {repo_path} log --oneline --no-merges -n {limit}")

    # ─── System Info ───────────────────────────────────────────────────

    async def system_info(self) -> dict:
        """Get system resource overview."""
        return await self.execute(
            "echo '=== DISK ===' && df -h / && echo '\\n=== MEMORY ===' && free -h && echo '\\n=== UPTIME ===' && uptime"
        )
