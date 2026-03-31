"""
AI DevOps Platform — Central Orchestrator

The brain of the platform. Routes commands to agents, manages the task queue,
tracks all actions (pending/completed/todo), and coordinates multi-agent workflows.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Callable, Optional, List, Dict, Any

from models import (
    Task, TaskStep, TaskStatus, StepStatus, RiskLevel, TaskEvent,
    Action, ActionStatus, AgentType
)
from agents import get_agent, AGENTS
from executor import executor
from approval import needs_approval, classify_risk_override
from database import db
from memory import memory

logger = logging.getLogger(__name__)


class Orchestrator:
    """Central orchestrator — manages agents, tasks, actions."""

    def __init__(self, event_callback: Optional[Callable] = None):
        self.tasks: Dict[str, Task] = {}
        self.event_callback = event_callback
        self._load_persisted_tasks()

    def _load_persisted_tasks(self):
        """Load tasks from DB on startup."""
        try:
            saved = db.list_tasks(limit=100)
            for t in saved:
                task = Task(**t)
                self.tasks[task.id] = task
            logger.info(f"Loaded {len(self.tasks)} tasks from database")
        except Exception as e:
            logger.warning(f"Failed to load tasks: {e}")

    async def emit(self, task_id: str, event_type: str, agent_type: str = "orchestrator", data: dict = {}):
        event = TaskEvent(task_id=task_id, event_type=event_type, agent_type=agent_type, data=data)
        if self.event_callback:
            await self.event_callback(event)
        logger.info(f"[{task_id[:8]}] {event_type}: {data.get('message', data.get('description', ''))[:80]}")

    # ── Task Creation & Routing ────────────────────────────────

    async def create_task(self, command: str, context: dict = {},
                          agent_type: str = None, repo_id: str = None) -> Task:
        """Create a task, route to the right agent, and start the agentic loop."""

        # Auto-detect agent type from command if not specified
        if not agent_type:
            agent_type = self._route_command(command)

        task = Task(
            command=command,
            context=context,
            agent_type=AgentType(agent_type),
            repo_id=repo_id,
        )
        self.tasks[task.id] = task

        # Record action
        action = Action(
            type=ActionStatus.PENDING,
            agent_type=AgentType(agent_type),
            description=f"Task: {command[:80]}",
            task_id=task.id,
            repo_id=repo_id,
            severity="medium",
        )
        db.save_action(action.model_dump())

        # Log
        await self.emit(task.id, "task_created", agent_type, {"command": command, "agent": agent_type})
        memory.log_activity(f"Task created: {command[:60]}", agent_type)
        memory.increment_stat("total_tasks")

        # Persist
        self._save_task(task)

        # Start agent loop
        asyncio.create_task(self._agent_loop(task))

        return task

    def _route_command(self, command: str) -> str:
        """Auto-detect which agent should handle a command."""
        cmd = command.lower()

        if any(kw in cmd for kw in ["review", "pr", "pull request", "bug", "fix", "code quality", "refactor"]):
            return "code_reviewer"
        elif any(kw in cmd for kw in ["test", "build", "ci", "coverage", "lint", "pytest", "jest"]):
            return "test_runner"
        elif any(kw in cmd for kw in ["log", "error", "rca", "alert", "monitor log", "crash", "exception"]):
            return "log_monitor"
        elif any(kw in cmd for kw in ["deploy", "cloud", "gcp", "kubernetes", "k8s", "infra", "cost", "uptime", "service"]):
            return "cloud_monitor"
        else:
            return "code_reviewer"  # Default

    # ── Agent Loop ─────────────────────────────────────────────

    async def _agent_loop(self, task: Task):
        """Main agentic loop — LLM drives everything."""
        agent = get_agent(task.agent_type.value)
        if not agent:
            task.status = TaskStatus.FAILED
            task.error = f"Unknown agent type: {task.agent_type}"
            self._save_task(task)
            return

        task.status = TaskStatus.RUNNING
        agent.start_conversation(task.id, task.command, task.context)
        iteration = 0

        await self.emit(task.id, "agent_thinking", task.agent_type.value, {
            "message": f"{agent.AGENT_NAME} is analyzing the goal..."
        })

        try:
            while True:
                iteration += 1
                decision = await asyncio.to_thread(agent.decide_next, task.id, iteration)
                action = decision.get("action", "done")

                # ── DONE ──────────────────────────────────────
                if action == "done":
                    summary = decision.get("summary", "Task completed")
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.utcnow()
                    task.summary = summary

                    # Generate report
                    await self.emit(task.id, "generating_report", task.agent_type.value, {
                        "message": f"{agent.AGENT_NAME} generating report..."
                    })
                    report = await asyncio.to_thread(agent.generate_task_report, task.id)
                    task.report = report

                    await self.emit(task.id, "task_completed", task.agent_type.value, {
                        "message": summary,
                        "iterations": iteration,
                        "has_report": True,
                    })

                    # Update memory and actions
                    memory.record_task_completion(task.id, task.command, task.agent_type.value, "completed", summary)
                    memory.increment_stat("tasks_completed")
                    self._complete_action(task.id)

                    await executor.cleanup_container(task.id)
                    agent.cleanup(task.id)
                    self._save_task(task)
                    return

                # ── ASK HUMAN ─────────────────────────────────
                if action == "ask_human":
                    question = decision.get("question", "Need clarification")
                    step = TaskStep(
                        order=len(task.steps) + 1,
                        description=f"Agent needs input: {question}",
                        command="", tool="human",
                        risk_level=RiskLevel.LOW,
                        status=StepStatus.AWAITING_APPROVAL,
                        thinking=decision.get("thinking", ""),
                    )
                    task.steps.append(step)
                    task.status = TaskStatus.AWAITING_APPROVAL

                    await self.emit(task.id, "agent_question", task.agent_type.value, {
                        "step_id": step.id, "question": question,
                    })
                    self._save_task(task)
                    return

                # ── RUN COMMAND ───────────────────────────────
                if action == "run":
                    command = decision.get("command", "")
                    description = decision.get("description", command[:60])
                    risk = decision.get("risk_level", "low")

                    step = TaskStep(
                        order=len(task.steps) + 1,
                        description=description,
                        command=command,
                        tool=self._detect_tool(command),
                        risk_level=RiskLevel(risk),
                        status=StepStatus.PENDING,
                        thinking=decision.get("thinking", ""),
                    )
                    step.risk_level = classify_risk_override(step)
                    task.steps.append(step)
                    task.updated_at = datetime.utcnow()

                    await self.emit(task.id, "agent_decided", task.agent_type.value, {
                        "step_id": step.id, "description": description,
                        "command": command, "risk_level": step.risk_level.value,
                        "iteration": iteration,
                    })

                    # Approval gate
                    if needs_approval(step):
                        step.status = StepStatus.AWAITING_APPROVAL
                        task.status = TaskStatus.AWAITING_APPROVAL
                        await self.emit(task.id, "approval_needed", task.agent_type.value, {
                            "step_id": step.id, "command": command,
                            "risk_level": step.risk_level.value,
                            "message": f"Agent wants to run: {command}",
                        })
                        self._save_task(task)
                        return

                    # Execute
                    await self._execute_step(task, step, agent)
                    self._save_task(task)
                    await asyncio.sleep(0.3)
                    continue

                # Unknown action
                agent.feed_result(task.id, "", 1, "", f"Unknown action: {action}.")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.exception(f"Agent loop error for task {task.id}")
            await self.emit(task.id, "task_failed", task.agent_type.value, {"message": str(e)})
            memory.add_finding(f"Task failed: {str(e)[:100]}", task.agent_type.value, "high")
            await executor.cleanup_container(task.id)
            agent.cleanup(task.id)
            self._save_task(task)

    async def _execute_step(self, task: Task, step: TaskStep, agent):
        step.status = StepStatus.RUNNING
        step.started_at = datetime.utcnow()

        await self.emit(task.id, "step_started", task.agent_type.value, {
            "step_id": step.id, "command": step.command,
        })

        exit_code, stdout, stderr = await executor.execute_command(task.id, step.command)
        step.completed_at = datetime.utcnow()
        step.output = stdout

        if exit_code == 0:
            step.status = StepStatus.SUCCESS
            await self.emit(task.id, "step_completed", task.agent_type.value, {
                "step_id": step.id, "output_preview": stdout[:300],
            })
        else:
            step.status = StepStatus.FAILED
            step.error = stderr or f"Exit code: {exit_code}"
            await self.emit(task.id, "step_failed", task.agent_type.value, {
                "step_id": step.id, "error": step.error[:300],
            })
            memory.add_finding(f"Command failed: {step.command[:50]} — {step.error[:50]}", task.agent_type.value, "medium")

        current_workdir = executor.get_workdir(task.id)
        agent.feed_result(task.id, step.command, exit_code, stdout, stderr, workdir=current_workdir)

    # ── Approval ───────────────────────────────────────────────

    async def approve_step(self, task_id: str, step_id: str, approved: bool, comment: str = "") -> Task:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        agent = get_agent(task.agent_type.value)
        if not agent:
            raise ValueError(f"No agent for {task.agent_type}")

        step = next((s for s in task.steps if s.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found")

        if not approved:
            step.status = StepStatus.SKIPPED
            step.error = f"Rejected: {comment}"
            agent.feed_approval_result(task.id, False, comment)
            task.status = TaskStatus.RUNNING
            asyncio.create_task(self._agent_loop(task))
            memory.log_activity(f"Step rejected: {step.description[:40]}", task.agent_type.value)
            self._save_task(task)
            return task

        step.status = StepStatus.APPROVED
        step.approved_by = "user"

        if not step.command:
            agent.feed_approval_result(task.id, True, comment)
            task.status = TaskStatus.RUNNING
            asyncio.create_task(self._agent_loop(task))
            self._save_task(task)
            return task

        task.status = TaskStatus.RUNNING
        await self._execute_step(task, step, agent)
        asyncio.create_task(self._agent_loop(task))
        memory.log_activity(f"Step approved: {step.description[:40]}", task.agent_type.value)
        self._save_task(task)
        return task

    # ── Actions ────────────────────────────────────────────────

    def add_action(self, agent_type: str, description: str, severity: str = "low",
                   action_type: str = "pending", task_id: str = None, repo_id: str = None) -> Action:
        action = Action(
            type=ActionStatus(action_type),
            agent_type=AgentType(agent_type),
            description=description,
            severity=severity,
            task_id=task_id,
            repo_id=repo_id,
        )
        db.save_action(action.model_dump())
        return action

    def _complete_action(self, task_id: str):
        actions = db.list_actions(limit=100)
        for a in actions:
            if a.get("task_id") == task_id and a.get("type") == "pending":
                db.update_action_status(a["id"], "completed")

    def list_actions(self, limit: int = 50, action_type: str = None, agent_type: str = None) -> List[dict]:
        return db.list_actions(limit, action_type, agent_type)

    # ── Tasks ──────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def list_tasks(self, limit: int = 20, agent_type: str = None) -> List[Task]:
        tasks = sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)
        if agent_type:
            tasks = [t for t in tasks if t.agent_type.value == agent_type]
        return tasks[:limit]

    async def cancel_task(self, task_id: str) -> Optional[Task]:
        task = self.tasks.get(task_id)
        if task:
            task.status = TaskStatus.CANCELLED
            await executor.cleanup_container(task_id)
            agent = get_agent(task.agent_type.value)
            if agent:
                agent.cleanup(task_id)
            self._save_task(task)
        return task

    # ── Helpers ─────────────────────────────────────────────────

    def _save_task(self, task: Task):
        task.updated_at = datetime.utcnow()
        db.save_task(task.model_dump(mode="json"))

    def _detect_tool(self, command: str) -> str:
        cmd = command.strip().split()[0] if command.strip() else ""
        tool_map = {
            "gh": "github", "git": "git", "gcloud": "gcp",
            "docker": "docker", "kubectl": "kubernetes",
            "terraform": "terraform", "claude": "claude-code",
            "npm": "node", "npx": "node", "node": "node",
            "python3": "python", "python": "python", "pip": "python",
            "pytest": "python", "make": "shell", "curl": "shell",
        }
        return tool_map.get(cmd, "shell")
