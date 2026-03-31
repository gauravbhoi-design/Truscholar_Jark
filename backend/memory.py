"""
AI DevOps Platform — System Memory

A persistent, self-updating memory system that tracks everything about the
platform's state — repos, services, agents, findings, tasks — like a human
DevOps engineer who remembers everything.

Updates on every action, maintains context across sessions.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger(__name__)


class SystemMemoryManager:
    """
    Manages the platform's system memory.
    
    Memory categories:
    - repos: Current state of each repository (branch, tests, last deploy, health)
    - services: Running services and their metrics
    - infra: Infrastructure state (clusters, projects, regions)
    - credentials: Connection status for integrations
    - findings: Issues, bugs, alerts discovered by agents
    - agents: Each agent's current state and last activity
    - tasks: Task history and patterns
    - stats: Aggregated statistics
    """

    def __init__(self):
        self._initialize_defaults()

    def _initialize_defaults(self):
        """Set up default memory if not already present."""
        defaults = {
            "credentials": {
                "github": "disconnected",
                "gcp": "disconnected",
                "docker": "disconnected",
                "anthropic": "disconnected",
            },
            "infra": {
                "gcp_project": "",
                "region": "",
                "k8s_cluster": "",
                "active_containers": 0,
            },
            "stats": {
                "total_tasks": 0,
                "commands_executed": 0,
                "issues_found": 0,
                "fixes_applied": 0,
            },
        }
        for key, value in defaults.items():
            existing = db.get_memory(key)
            if existing is None:
                db.set_memory(key, value, category=key)

    # ── Core Operations ────────────────────────────────────────

    def update(self, key: str, value: Any, category: str = "general", source: str = "system"):
        """Update a memory entry and log the change."""
        db.set_memory(key, value, category, source)
        self._log(f"Memory updated: {key}", source)

    def get(self, key: str) -> Optional[Any]:
        """Get a memory value."""
        return db.get_memory(key)

    def get_category(self, category: str) -> Dict[str, Any]:
        """Get all memory entries in a category."""
        return db.get_memory_by_category(category)

    def get_full_state(self) -> Dict[str, Any]:
        """Get the complete memory state — used by the dashboard."""
        all_mem = db.get_all_memory()

        # Organize by category
        organized = {
            "repos": {},
            "services": {},
            "infra": {},
            "credentials": {},
            "recent_findings": [],
            "agent_states": {},
            "task_history": [],
            "activity_log": [],
            "stats": {},
            "last_updated": datetime.utcnow().isoformat(),
        }

        for key, entry in all_mem.items():
            cat = entry.get("category", "general")
            val = entry.get("value")
            if cat == "repos":
                organized["repos"][key] = val
            elif cat == "services":
                organized["services"][key] = val
            elif cat == "infra":
                organized["infra"] = val if key == "infra" else organized["infra"]
            elif cat == "credentials":
                organized["credentials"] = val if key == "credentials" else organized["credentials"]
            elif cat == "findings":
                if isinstance(val, list):
                    organized["recent_findings"].extend(val)
                else:
                    organized["recent_findings"].append(val)
            elif cat == "agents":
                organized["agent_states"][key] = val
            elif cat == "stats":
                organized["stats"] = val if key == "stats" else organized["stats"]

        # Get recent activity log
        logs = db.get_logs(limit=30)
        organized["activity_log"] = [
            {"time": log["timestamp"], "text": log["text"], "agent": log.get("agent_type", "system")}
            for log in logs
        ]

        return organized

    # ── Repo Memory ────────────────────────────────────────────

    def update_repo(self, repo_name: str, data: Dict[str, Any]):
        """Update memory about a repository."""
        existing = self.get(f"repo:{repo_name}") or {}
        existing.update(data)
        existing["last_checked"] = datetime.utcnow().isoformat()
        self.update(f"repo:{repo_name}", existing, category="repos", source="github")

    def get_repo_state(self, repo_name: str) -> Optional[Dict[str, Any]]:
        return self.get(f"repo:{repo_name}")

    # ── Service Memory ─────────────────────────────────────────

    def update_service(self, service_name: str, data: Dict[str, Any]):
        existing = self.get(f"service:{service_name}") or {}
        existing.update(data)
        existing["last_checked"] = datetime.utcnow().isoformat()
        self.update(f"service:{service_name}", existing, category="services", source="gcp")

    # ── Agent Memory ───────────────────────────────────────────

    def update_agent_state(self, agent_type: str, data: Dict[str, Any]):
        """Track an agent's current state."""
        existing = self.get(f"agent:{agent_type}") or {}
        existing.update(data)
        existing["last_active"] = datetime.utcnow().isoformat()
        self.update(f"agent:{agent_type}", existing, category="agents", source=agent_type)

    def get_agent_state(self, agent_type: str) -> Dict[str, Any]:
        return self.get(f"agent:{agent_type}") or {"status": "idle", "last_active": None}

    # ── Findings ───────────────────────────────────────────────

    def add_finding(self, finding: str, agent_type: str = "system", severity: str = "medium"):
        """Add a new finding/issue discovered by an agent."""
        findings = self.get("findings_list") or []
        entry = {
            "text": finding,
            "agent": agent_type,
            "severity": severity,
            "time": datetime.utcnow().isoformat(),
        }
        findings.insert(0, entry)
        findings = findings[:50]  # Keep last 50
        self.update("findings_list", findings, category="findings", source=agent_type)
        self._log(f"Finding [{severity}]: {finding}", agent_type)

    def get_findings(self, limit: int = 20) -> List[Dict[str, Any]]:
        findings = self.get("findings_list") or []
        return findings[:limit]

    # ── Credentials ────────────────────────────────────────────

    def update_credential_status(self, service: str, status: str):
        creds = self.get("credentials") or {}
        creds[service] = status
        self.update("credentials", creds, category="credentials")

    # ── Stats ──────────────────────────────────────────────────

    def increment_stat(self, stat_key: str, amount: int = 1):
        stats = self.get("stats") or {}
        stats[stat_key] = stats.get(stat_key, 0) + amount
        self.update("stats", stats, category="stats")

    def get_stats(self) -> Dict[str, Any]:
        return self.get("stats") or {}

    # ── Task Memory ────────────────────────────────────────────

    def record_task_completion(self, task_id: str, command: str, agent_type: str,
                                status: str, summary: str):
        """Record a completed task in memory for pattern learning."""
        history = self.get("task_history") or []
        history.insert(0, {
            "task_id": task_id,
            "command": command,
            "agent": agent_type,
            "status": status,
            "summary": summary,
            "time": datetime.utcnow().isoformat(),
        })
        history = history[:100]  # Keep last 100
        self.update("task_history", history, category="tasks")

    # ── Activity Log ───────────────────────────────────────────

    def _log(self, text: str, agent_type: str = "system"):
        db.add_log(text, agent_type)

    def log_activity(self, text: str, agent_type: str = "system", category: str = "general"):
        db.add_log(text, agent_type, category)

    def get_activity_log(self, limit: int = 30) -> List[Dict[str, str]]:
        logs = db.get_logs(limit)
        return [
            {"time": log["timestamp"], "text": log["text"], "agent": log.get("agent_type", "system")}
            for log in logs
        ]

    # ── Context for Agent Brain ────────────────────────────────

    def get_context_for_agent(self, agent_type: str, repo_name: str = None) -> str:
        """Generate a context summary string that gets injected into the agent's prompt."""
        parts = ["=== SYSTEM MEMORY CONTEXT ==="]

        if repo_name:
            repo_state = self.get_repo_state(repo_name)
            if repo_state:
                parts.append(f"\nRepository '{repo_name}' state: {repo_state}")

        findings = self.get_findings(5)
        if findings:
            parts.append("\nRecent findings:")
            for f in findings:
                parts.append(f"  - [{f['severity']}] {f['text']}")

        agent_state = self.get_agent_state(agent_type)
        if agent_state.get("last_active"):
            parts.append(f"\nYour last activity: {agent_state.get('last_task', 'None')}")

        creds = self.get("credentials") or {}
        connected = [k for k, v in creds.items() if v == "connected"]
        if connected:
            parts.append(f"\nConnected services: {', '.join(connected)}")

        return "\n".join(parts)


# Global instance
memory = SystemMemoryManager()
