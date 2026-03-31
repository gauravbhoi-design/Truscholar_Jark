"""
AI DevOps Platform — Database Layer (SQLite)
Persists tasks, actions, memory, and agent state across restarts.
"""

import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from config import settings

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self):
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                context TEXT DEFAULT '{}',
                agent_type TEXT DEFAULT 'orchestrator',
                repo_id TEXT,
                status TEXT DEFAULT 'running',
                steps TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                report TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS actions (
                id TEXT PRIMARY KEY,
                type TEXT DEFAULT 'pending',
                agent_type TEXT DEFAULT 'orchestrator',
                description TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                severity TEXT DEFAULT 'low',
                task_id TEXT,
                repo_id TEXT,
                created_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value TEXT,
                category TEXT DEFAULT 'general',
                updated_at TEXT,
                source TEXT DEFAULT 'system'
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                text TEXT,
                agent_type TEXT DEFAULT 'system',
                category TEXT DEFAULT 'general'
            );

            CREATE TABLE IF NOT EXISTS agent_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_type TEXT,
                repo_id TEXT,
                summary TEXT,
                items TEXT DEFAULT '[]',
                findings TEXT DEFAULT '[]',
                generated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_type TEXT,
                repo_id TEXT,
                steps TEXT DEFAULT '[]',
                created_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_type);
            CREATE INDEX IF NOT EXISTS idx_actions_type ON actions(type);
            CREATE INDEX IF NOT EXISTS idx_actions_agent ON actions(agent_type);
            CREATE INDEX IF NOT EXISTS idx_memory_category ON memory(category);
            CREATE INDEX IF NOT EXISTS idx_log_timestamp ON activity_log(timestamp);
        """)
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")

    # ── Tasks ──────────────────────────────────────────────────

    def save_task(self, task: dict):
        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO tasks
            (id, command, context, agent_type, repo_id, status, steps, summary, report, error, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task["id"], task["command"], json.dumps(task.get("context", {})),
            task.get("agent_type", "orchestrator"), task.get("repo_id"),
            task["status"], json.dumps(task.get("steps", []), default=str),
            task.get("summary", ""), task.get("report", ""), task.get("error", ""),
            task.get("created_at", datetime.utcnow().isoformat()),
            task.get("updated_at", datetime.utcnow().isoformat()),
            task.get("completed_at"),
        ))
        conn.commit()
        conn.close()

    def get_task(self, task_id: str) -> Optional[dict]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["context"] = json.loads(d["context"])
        d["steps"] = json.loads(d["steps"])
        return d

    def list_tasks(self, limit: int = 50, agent_type: str = None, status: str = None) -> List[dict]:
        conn = self._connect()
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        if agent_type:
            query += " AND agent_type = ?"
            params.append(agent_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        result = []
        for row in rows:
            d = dict(row)
            d["context"] = json.loads(d["context"])
            d["steps"] = json.loads(d["steps"])
            result.append(d)
        return result

    # ── Actions ────────────────────────────────────────────────

    def save_action(self, action: dict):
        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO actions
            (id, type, agent_type, description, detail, severity, task_id, repo_id, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            action["id"], action.get("type", "pending"),
            action.get("agent_type", "orchestrator"),
            action.get("description", ""), action.get("detail", ""),
            action.get("severity", "low"), action.get("task_id"),
            action.get("repo_id"),
            action.get("created_at", datetime.utcnow().isoformat()),
            action.get("completed_at"),
        ))
        conn.commit()
        conn.close()

    def list_actions(self, limit: int = 100, action_type: str = None, agent_type: str = None) -> List[dict]:
        conn = self._connect()
        query = "SELECT * FROM actions WHERE 1=1"
        params = []
        if action_type:
            query += " AND type = ?"
            params.append(action_type)
        if agent_type:
            query += " AND agent_type = ?"
            params.append(agent_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def update_action_status(self, action_id: str, status: str):
        conn = self._connect()
        completed = datetime.utcnow().isoformat() if status in ("completed", "failed", "cancelled") else None
        conn.execute(
            "UPDATE actions SET type = ?, completed_at = ? WHERE id = ?",
            (status, completed, action_id)
        )
        conn.commit()
        conn.close()

    # ── Memory ─────────────────────────────────────────────────

    def set_memory(self, key: str, value: Any, category: str = "general", source: str = "system"):
        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO memory (key, value, category, updated_at, source)
            VALUES (?, ?, ?, ?, ?)
        """, (key, json.dumps(value, default=str), category, datetime.utcnow().isoformat(), source))
        conn.commit()
        conn.close()

    def get_memory(self, key: str) -> Optional[Any]:
        conn = self._connect()
        row = conn.execute("SELECT value FROM memory WHERE key = ?", (key,)).fetchone()
        conn.close()
        if row:
            return json.loads(row["value"])
        return None

    def get_memory_by_category(self, category: str) -> Dict[str, Any]:
        conn = self._connect()
        rows = conn.execute("SELECT key, value, updated_at FROM memory WHERE category = ?", (category,)).fetchall()
        conn.close()
        result = {}
        for row in rows:
            result[row["key"]] = {"value": json.loads(row["value"]), "updated_at": row["updated_at"]}
        return result

    def get_all_memory(self) -> Dict[str, Any]:
        conn = self._connect()
        rows = conn.execute("SELECT key, value, category, updated_at FROM memory").fetchall()
        conn.close()
        result = {}
        for row in rows:
            result[row["key"]] = {
                "value": json.loads(row["value"]),
                "category": row["category"],
                "updated_at": row["updated_at"],
            }
        return result

    # ── Activity Log ───────────────────────────────────────────

    def add_log(self, text: str, agent_type: str = "system", category: str = "general"):
        conn = self._connect()
        conn.execute(
            "INSERT INTO activity_log (timestamp, text, agent_type, category) VALUES (?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), text, agent_type, category),
        )
        conn.commit()
        conn.close()

    def get_logs(self, limit: int = 50, agent_type: str = None) -> List[dict]:
        conn = self._connect()
        query = "SELECT * FROM activity_log WHERE 1=1"
        params = []
        if agent_type:
            query += " AND agent_type = ?"
            params.append(agent_type)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # ── Agent Reports ──────────────────────────────────────────

    def save_agent_report(self, agent_type: str, repo_id: str, summary: str, items: list, findings: list):
        conn = self._connect()
        conn.execute("""
            INSERT INTO agent_reports (agent_type, repo_id, summary, items, findings, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (agent_type, repo_id, summary, json.dumps(items), json.dumps(findings), datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

    def get_latest_report(self, agent_type: str, repo_id: str = None) -> Optional[dict]:
        conn = self._connect()
        if repo_id:
            row = conn.execute(
                "SELECT * FROM agent_reports WHERE agent_type = ? AND repo_id = ? ORDER BY generated_at DESC LIMIT 1",
                (agent_type, repo_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM agent_reports WHERE agent_type = ? ORDER BY generated_at DESC LIMIT 1",
                (agent_type,),
            ).fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["items"] = json.loads(d["items"])
            d["findings"] = json.loads(d["findings"])
            return d
        return None

    # ── Agent Plans ────────────────────────────────────────────

    def save_agent_plan(self, agent_type: str, repo_id: str, steps: list):
        conn = self._connect()
        conn.execute("""
            INSERT INTO agent_plans (agent_type, repo_id, steps, created_at)
            VALUES (?, ?, ?, ?)
        """, (agent_type, repo_id, json.dumps(steps, default=str), datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

    def get_latest_plan(self, agent_type: str, repo_id: str = None) -> Optional[dict]:
        conn = self._connect()
        if repo_id:
            row = conn.execute(
                "SELECT * FROM agent_plans WHERE agent_type = ? AND repo_id = ? ORDER BY created_at DESC LIMIT 1",
                (agent_type, repo_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM agent_plans WHERE agent_type = ? ORDER BY created_at DESC LIMIT 1",
                (agent_type,),
            ).fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["steps"] = json.loads(d["steps"])
            return d
        return None

    # ── Stats ──────────────────────────────────────────────────

    def get_stats(self) -> dict:
        conn = self._connect()
        total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'failed'").fetchone()[0]
        running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('running', 'awaiting_approval', 'parsing')").fetchone()[0]
        total_actions = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        pending_actions = conn.execute("SELECT COUNT(*) FROM actions WHERE type = 'pending'").fetchone()[0]
        conn.close()
        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "running_tasks": running,
            "total_actions": total_actions,
            "pending_actions": pending_actions,
            "success_rate": f"{(completed / total_tasks * 100):.0f}%" if total_tasks > 0 else "N/A",
        }


db = Database()
