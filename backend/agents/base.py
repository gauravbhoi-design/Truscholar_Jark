"""
AI DevOps Platform — Base Agent

Each agent has:
1. Report tab: Shows findings, metrics, status for selected repo/service
2. Plan tab: Step-by-step execution plan for current task
3. Command tab: Accept user commands and execute via LLM + tools

The agent brain uses Claude to reason, plan, and execute.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from abc import ABC, abstractmethod

from config import settings
from database import db
from memory import memory

logger = logging.getLogger(__name__)


def get_claude_client():
    """Create Claude client — Vertex AI or direct API."""
    if settings.gcp_project_id:
        from anthropic import AnthropicVertex
        key_path = settings.gcp_key_path
        if key_path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(key_path)
        return AnthropicVertex(project_id=settings.gcp_project_id, region=settings.gcp_region)
    elif settings.anthropic_api_key:
        from anthropic import Anthropic
        return Anthropic(api_key=settings.anthropic_api_key)
    else:
        raise ValueError("No Claude config. Set GCP_PROJECT_ID or ANTHROPIC_API_KEY")


class BaseAgent(ABC):
    """Base class for all DevOps agents."""

    AGENT_TYPE = "base"
    AGENT_NAME = "Base Agent"
    AGENT_ICON = "🤖"
    AGENT_COLOR = "#7a7a8e"
    AGENT_DESCRIPTION = "Base agent"
    AGENT_CATEGORY = "General"

    def __init__(self):
        self.client = None
        self.model = settings.agent_model
        self.max_iterations = settings.agent_max_iterations
        self._conversations: Dict[str, List[dict]] = {}  # task_id -> messages

    def _ensure_client(self):
        if self.client is None:
            self.client = get_claude_client()

    @property
    def info(self) -> Dict[str, str]:
        return {
            "id": self.AGENT_TYPE,
            "name": self.AGENT_NAME,
            "icon": self.AGENT_ICON,
            "color": self.AGENT_COLOR,
            "description": self.AGENT_DESCRIPTION,
            "category": self.AGENT_CATEGORY,
            "status": self._get_status(),
        }

    def _get_status(self) -> str:
        state = memory.get_agent_state(self.AGENT_TYPE)
        return state.get("status", "idle")

    # ── Report Tab ─────────────────────────────────────────────

    @abstractmethod
    async def generate_report(self, repo_id: str = None, context: dict = None) -> Dict[str, Any]:
        """Generate report data for the Report tab. Returns {summary, items, findings}."""
        pass

    async def get_report(self, repo_id: str = None) -> Dict[str, Any]:
        """Get cached report or generate new one."""
        cached = db.get_latest_report(self.AGENT_TYPE, repo_id)
        if cached:
            return cached
        return await self.generate_report(repo_id)

    def save_report(self, repo_id: str, summary: str, items: list, findings: list):
        db.save_agent_report(self.AGENT_TYPE, repo_id, summary, items, findings)

    # ── Plan Tab ───────────────────────────────────────────────

    @abstractmethod
    async def generate_plan(self, command: str, repo_id: str = None, context: dict = None) -> List[Dict[str, Any]]:
        """Generate execution plan for a command. Returns list of step dicts."""
        pass

    async def get_plan(self, repo_id: str = None) -> Optional[Dict[str, Any]]:
        """Get the latest plan."""
        return db.get_latest_plan(self.AGENT_TYPE, repo_id)

    def save_plan(self, repo_id: str, steps: list):
        db.save_agent_plan(self.AGENT_TYPE, repo_id, steps)

    # ── Command Tab (Agent Brain Loop) ─────────────────────────

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent's brain."""
        pass

    def start_conversation(self, task_id: str, goal: str, context: dict = None):
        """Initialize a new agent conversation for a task."""
        mem_context = memory.get_context_for_agent(self.AGENT_TYPE)

        initial_msg = f"GOAL: {goal}"
        if context:
            initial_msg += f"\n\nCONTEXT: {json.dumps(context)}"
        initial_msg += f"\n\n{mem_context}"
        initial_msg += "\n\nYour current working directory is: /workspace\nBegin working. Run one command at a time."

        self._conversations[task_id] = [{"role": "user", "content": initial_msg}]

        memory.update_agent_state(self.AGENT_TYPE, {
            "status": "working",
            "current_task": task_id,
            "last_task": goal[:80],
        })
        memory.log_activity(f"{self.AGENT_NAME} started: {goal[:60]}", self.AGENT_TYPE)

    def decide_next(self, task_id: str, iteration: int) -> dict:
        """Ask the agent brain what to do next."""
        self._ensure_client()

        if iteration > self.max_iterations:
            return {"action": "done", "summary": f"Reached max iterations ({self.max_iterations}).", "thinking": "Safety limit"}

        messages = self._conversations.get(task_id, [])
        if not messages:
            return {"action": "done", "summary": "No conversation context", "thinking": "Error"}

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.get_system_prompt(),
                messages=messages,
            )

            stop_reason = response.stop_reason
            text = response.content[0].text
            messages.append({"role": "assistant", "content": text})

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            if stop_reason == "max_tokens" or not cleaned.endswith("}"):
                messages.append({
                    "role": "user",
                    "content": "Response truncated. Respond with ONLY a short JSON object. Keep 'thinking' to max 10 words."
                })
                return self.decide_next(task_id, iteration)

            decision = json.loads(cleaned)

            # Update memory
            memory.increment_stat("commands_executed")
            if decision.get("action") == "done":
                memory.update_agent_state(self.AGENT_TYPE, {"status": "idle", "last_completed": datetime.utcnow().isoformat()})

            return decision

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse failed: {str(e)[:100]}")
            if iteration <= self.max_iterations - 2:
                messages.append({
                    "role": "user",
                    "content": "Invalid JSON. Respond with ONLY a JSON object."
                })
                return self.decide_next(task_id, iteration)
            return {"action": "done", "summary": "Agent response error", "thinking": str(e)[:50]}
        except Exception as e:
            logger.error(f"Agent brain error: {e}")
            return {"action": "done", "summary": f"Agent error: {str(e)[:200]}", "thinking": "LLM call failed"}

    def feed_result(self, task_id: str, command: str, exit_code: int, stdout: str, stderr: str, workdir: str = "/workspace"):
        """Feed command output back to the agent."""
        messages = self._conversations.get(task_id, [])

        max_out = 8000
        if len(stdout) > max_out:
            stdout = stdout[:max_out // 2] + f"\n...[TRUNCATED {len(stdout)} chars]...\n" + stdout[-max_out // 2:]
        if len(stderr) > 4000:
            stderr = stderr[:2000] + "\n...[TRUNCATED]...\n" + stderr[-2000:]

        result_msg = f"COMMAND RESULT (exit code: {exit_code}):\n"
        result_msg += f"Current directory: {workdir}\n"
        result_msg += f"\nSTDOUT:\n{stdout}\n" if stdout.strip() else "\nSTDOUT: (empty)\n"
        if stderr.strip():
            result_msg += f"\nSTDERR:\n{stderr}\n"
        result_msg += "\nCommand succeeded. What's next?" if exit_code == 0 else "\nCommand FAILED. Analyze the error and adapt."

        messages.append({"role": "user", "content": result_msg})

    def feed_approval_result(self, task_id: str, approved: bool, comment: str = ""):
        messages = self._conversations.get(task_id, [])
        if approved:
            msg = "User APPROVED this action. Proceed."
        else:
            msg = f"User REJECTED this action."
            if comment:
                msg += f" Reason: {comment}"
            msg += " Decide what to do instead."
        messages.append({"role": "user", "content": msg})

    def generate_task_report(self, task_id: str) -> str:
        """Generate a markdown report from the full conversation."""
        self._ensure_client()
        messages = self._conversations.get(task_id, [])
        if not messages:
            return "# No Data\n\nNo conversation history for this task."

        report_prompt = """Based on everything you just did, write a comprehensive MARKDOWN REPORT.
Include: Task Summary, Steps Taken, Findings (grouped by severity), Recommendations.
Write ONLY markdown, no JSON wrapper."""

        messages.append({"role": "user", "content": report_prompt})

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system="Write a detailed technical report in Markdown. Write ONLY markdown, no JSON.",
                messages=messages,
            )
            report = response.content[0].text.strip()
            if report.startswith("```markdown"):
                report = report[len("```markdown"):].strip()
            if report.startswith("```"):
                report = report[3:].strip()
            if report.endswith("```"):
                report = report[:-3].strip()
            return report
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return f"# Report Generation Failed\n\nError: {str(e)}"

    def cleanup(self, task_id: str):
        """Clean up conversation memory for a task."""
        self._conversations.pop(task_id, None)
