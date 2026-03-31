"""
Task Executor — Runs steps inside Docker containers with persistent workspace.

Key design: Each task gets a Docker VOLUME mounted at /workspace.
If the container dies (OOM, crash), the volume survives — cloned repos,
installed packages, and all files persist when the container is recreated.
"""

import docker
import docker.errors
import asyncio
import re
import logging
from typing import Tuple
from config import settings

logger = logging.getLogger(__name__)


class DockerExecutor:
    def __init__(self):
        self.client = docker.from_env()
        self._container_cache = {}
        self._workdir_cache = {}
        self._volume_cache = {}  # task_id -> volume name

    def _get_env_vars(self) -> dict:
        env = {}
        if settings.github_token:
            env["GITHUB_TOKEN"] = settings.github_token
            env["GH_TOKEN"] = settings.github_token
        if settings.gcp_project_id:
            env["GCP_PROJECT_ID"] = settings.gcp_project_id
            env["GCP_REGION"] = settings.gcp_region
        if settings.gcp_service_account_key:
            env["GCP_SERVICE_ACCOUNT_KEY"] = settings.gcp_service_account_key
        if settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        return env

    def _get_volumes(self, task_id: str) -> dict:
        """Build volume mounts: persistent workspace + optional GCP key."""
        volumes = {}

        # Persistent workspace volume — survives container death
        vol_name = f"workspace-{task_id[:12]}"
        try:
            self.client.volumes.get(vol_name)
        except docker.errors.NotFound:
            self.client.volumes.create(name=vol_name, labels={"ai-devops": "workspace", "task-id": task_id})
            logger.info(f"Created workspace volume: {vol_name}")
        self._volume_cache[task_id] = vol_name
        volumes[vol_name] = {"bind": "/workspace", "mode": "rw"}

        # GCP key
        gcp_key_path = settings.gcp_key_path
        if gcp_key_path.exists():
            volumes[str(gcp_key_path)] = {"bind": "/tmp/gcp-key.json", "mode": "ro"}

        return volumes

    # ── Startup / Stale Cleanup ────────────────────────────────────

    def startup_cleanup(self):
        """Remove ALL orphaned worker containers and volumes from previous runs."""
        try:
            orphans = self.client.containers.list(all=True, filters={"label": "ai-devops=worker"})
            for c in orphans:
                try:
                    c.stop(timeout=3)
                except Exception:
                    pass
                try:
                    c.remove(force=True)
                except Exception:
                    pass
            if orphans:
                logger.info(f"Startup: removed {len(orphans)} orphaned containers")

            # Also clean old workspace volumes
            old_vols = self.client.volumes.list(filters={"label": "ai-devops=workspace"})
            for v in old_vols:
                try:
                    v.remove(force=True)
                except Exception:
                    pass
            if old_vols:
                logger.info(f"Startup: removed {len(old_vols)} orphaned volumes")
        except Exception as e:
            logger.warning(f"Startup cleanup error: {e}")

    def _kill_stale(self, name: str):
        try:
            old = self.client.containers.get(name)
            logger.info(f"Killing stale container: {name}")
            try:
                old.stop(timeout=3)
            except Exception:
                pass
            old.remove(force=True)
        except docker.errors.NotFound:
            pass
        except Exception as e:
            logger.warning(f"Stale cleanup failed for {name}: {e}")

    # ── Container Lifecycle ────────────────────────────────────────

    async def get_or_create_container(self, task_id: str):
        """Get or create a worker container.

        The workspace volume persists across container restarts,
        so even if the container OOMs, cloned repos and installed
        packages survive in /workspace.
        """
        container_name = f"worker-{task_id[:12]}"

        # Check cache — is container still alive?
        if task_id in self._container_cache:
            container = self._container_cache[task_id]
            try:
                container.reload()
                if container.status == "running":
                    return container
                logger.warning(f"{container_name} died ({container.status}), recreating with same volume")
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            except docker.errors.NotFound:
                logger.warning(f"{container_name} vanished, recreating with same volume")
            self._container_cache.pop(task_id, None)

        # Kill stale container with same name
        await asyncio.to_thread(self._kill_stale, container_name)

        # Create fresh container — SAME volume, so /workspace data persists
        container = await asyncio.to_thread(
            self.client.containers.run,
            image=settings.worker_image,
            detach=True,
            tty=True,
            stdin_open=True,
            environment=self._get_env_vars(),
            volumes=self._get_volumes(task_id),
            working_dir="/workspace",
            mem_limit="4g",        # 4GB — pip install needs memory
            cpu_period=100000,
            cpu_quota=200000,
            network_mode="bridge",
            name=container_name,
            labels={"ai-devops": "worker", "task-id": task_id},
            # Keep container alive even if entrypoint fails
            restart_policy={"Name": "unless-stopped"},
        )
        self._container_cache[task_id] = container

        # Only reset workdir if this is a brand new task (no prior workdir)
        if task_id not in self._workdir_cache:
            self._workdir_cache[task_id] = "/workspace"

        logger.info(f"Created container {container_name}: {container.short_id} (workdir={self._workdir_cache.get(task_id)})")
        return container

    # ── Command Execution ──────────────────────────────────────────

    async def execute_command(self, task_id: str, command: str, timeout: int = None) -> Tuple[int, str, str]:
        """Execute a command in the task's container.

        - Prefixes with `cd <workdir>` so directory persists
        - Tracks workdir by PARSING the command, never re-running it
        """
        timeout = timeout or settings.worker_timeout
        container = await self.get_or_create_container(task_id)
        current_workdir = self._workdir_cache.get(task_id, "/workspace")

        full_command = f'cd {current_workdir} 2>/dev/null; {command}'
        logger.info(f"[{task_id[:8]}] workdir={current_workdir} | cmd={command}")

        try:
            exec_result = await asyncio.to_thread(
                container.exec_run,
                ["bash", "-c", full_command],
                workdir="/workspace",
                demux=True,
            )

            exit_code = exec_result.exit_code
            stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace")
            stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace")

            if exit_code == 0:
                self._track_workdir(task_id, command, current_workdir)

            if len(stdout) > 50000:
                stdout = stdout[:25000] + "\n...[TRUNCATED]...\n" + stdout[-25000:]
            if len(stderr) > 10000:
                stderr = stderr[:5000] + "\n...[TRUNCATED]...\n" + stderr[-5000:]

            return exit_code, stdout, stderr

        except Exception as e:
            logger.error(f"Exec error [{task_id[:8]}]: {e}")
            return 1, "", str(e)

    def get_workdir(self, task_id: str) -> str:
        """Get current working directory for a task (used by agent)."""
        return self._workdir_cache.get(task_id, "/workspace")

    # ── Workdir Tracking ───────────────────────────────────────────

    def _track_workdir(self, task_id: str, command: str, current: str):
        """Update workdir by parsing the command (never re-executes)."""

        clone_match = re.search(
            r'(?:gh\s+repo\s+clone|git\s+clone)\s+\S*?([a-zA-Z0-9_.-]+?)(?:\.git)?(?:\s|$|&&)',
            command
        )
        if clone_match:
            repo = clone_match.group(1)
            # Check if clone target was specified (git clone url /target)
            target_match = re.search(r'git\s+clone\s+\S+\s+(/\S+)', command)
            if target_match:
                new_wd = target_match.group(1)
            else:
                new_wd = f"{current}/{repo}"
            self._workdir_cache[task_id] = new_wd
            logger.info(f"[{task_id[:8]}] workdir → {new_wd} (clone)")
            return

        cd_targets = re.findall(r'cd\s+([^\s;&|]+)', command)
        if cd_targets:
            wd = current
            for target in cd_targets:
                if target.startswith('/'):
                    wd = target
                elif target == '..':
                    wd = '/'.join(wd.rstrip('/').split('/')[:-1]) or '/'
                elif target in ('.', ''):
                    pass
                elif target == '~':
                    wd = '/root'
                else:
                    wd = f"{wd}/{target}"
            self._workdir_cache[task_id] = wd
            logger.info(f"[{task_id[:8]}] workdir → {wd} (cd)")

    # ── Cleanup ────────────────────────────────────────────────────

    async def cleanup_container(self, task_id: str):
        if task_id in self._container_cache:
            container = self._container_cache.pop(task_id)
            try:
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception as e:
                logger.warning(f"Container cleanup error [{task_id[:8]}]: {e}")

        # Also remove the workspace volume
        vol_name = self._volume_cache.pop(task_id, None)
        if vol_name:
            try:
                vol = self.client.volumes.get(vol_name)
                vol.remove(force=True)
                logger.info(f"Removed volume {vol_name}")
            except Exception:
                pass

        self._workdir_cache.pop(task_id, None)
        logger.info(f"Cleaned up task {task_id[:8]}")

    async def cleanup_all(self):
        for task_id in list(self._container_cache.keys()):
            await self.cleanup_container(task_id)
        self.startup_cleanup()


executor = DockerExecutor()
