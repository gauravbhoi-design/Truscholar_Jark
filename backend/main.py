"""
AI DevOps Platform — Main API Server

REST + WebSocket API for the complete platform:
- Dashboard state (repos, services, agents, memory)
- Task management (create, approve, cancel)
- Agent operations (report, plan, command)
- Central manager (actions)
- Memory system
- Real-time WebSocket updates
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from config import settings
from models import TaskCreate, Task, ApprovalRequest, TaskEvent, DashboardState
from orchestrator import Orchestrator
from executor import executor
from database import db
from memory import memory
from agents import list_agents, get_agent, AGENTS
from integrations.github_client import github_client
from integrations.gcp_client import gcp_client

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


# ── WebSocket Manager ─────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, event: TaskEvent):
        data = {
            "task_id": event.task_id,
            "event_type": event.event_type,
            "agent_type": event.agent_type,
            "data": event.data,
            "timestamp": event.timestamp.isoformat(),
        }
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)


ws_manager = ConnectionManager()


# ── App Lifecycle ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 AI DevOps Platform starting...")
    executor.startup_cleanup()

    # Check connections and update memory
    if github_client.is_connected:
        memory.update_credential_status("github", "connected")
        user = await github_client.get_authenticated_user()
        if user:
            memory.log_activity(f"GitHub connected as {user['login']}", "system")
    if gcp_client.is_connected:
        memory.update_credential_status("gcp", "connected")
        memory.log_activity(f"GCP connected: {gcp_client.project_id}", "system")
    if settings.anthropic_api_key or settings.gcp_project_id:
        memory.update_credential_status("anthropic", "connected")

    memory.log_activity("Platform started", "system")
    yield
    logger.info("🛑 Shutting down...")
    await executor.cleanup_all()
    await github_client.close()


app = FastAPI(
    title="AI DevOps Platform",
    description="Autonomous multi-agent DevOps orchestration platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Orchestrator
orchestrator = Orchestrator(event_callback=ws_manager.broadcast)


# ═══════════════════════════════════════════════════════════════
# ─── DASHBOARD STATE ──────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {"name": "AI DevOps Platform", "version": "1.0.0", "status": "running"}


@app.get("/api/dashboard")
async def get_dashboard_state():
    """Full dashboard state — repos, services, agents, actions, memory, stats."""
    repos = await _get_repos()
    services = await _get_services()
    agents_info = list_agents()
    actions = orchestrator.list_actions(limit=50)
    mem_state = memory.get_full_state()
    tasks = [t.model_dump(mode="json") for t in orchestrator.list_tasks(limit=20)]
    stats = db.get_stats()

    return {
        "repos": repos,
        "services": services,
        "agents": agents_info,
        "actions": actions,
        "memory": mem_state,
        "tasks": tasks,
        "stats": stats,
    }


# ═══════════════════════════════════════════════════════════════
# ─── REPOS ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.get("/api/repos")
async def get_repos():
    return await _get_repos()


async def _get_repos():
    """Fetch repos from GitHub and enrich with health data."""
    if not github_client.is_connected:
        return []
    try:
        repos = await github_client.list_repos()
        result = []
        for r in repos[:20]:
            parts = r["full_name"].split("/")
            owner, name = parts[0], parts[1]
            health = await github_client.get_repo_health(owner, name)

            repo = {
                "id": r["id"],
                "name": r["name"],
                "full_name": r["full_name"],
                "language": r.get("language", ""),
                "default_branch": r.get("default_branch", "main"),
                "stars": r.get("stars", 0),
                "open_issues": health.get("issues", r.get("open_issues", 0)),
                "open_prs": health.get("prs", 0),
                "last_commit": health.get("last_commit", ""),
                "last_commit_date": health.get("last_commit_date"),
                "status": health.get("status", "unknown"),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
                "visibility": r.get("visibility", "private"),
            }
            result.append(repo)

            # Update memory
            memory.update_repo(name, {
                "branch": r.get("default_branch", "main"),
                "issues": health.get("issues", 0),
                "prs": health.get("prs", 0),
                "status": health.get("status", "unknown"),
            })

        return result
    except Exception as e:
        logger.error(f"Error fetching repos: {e}")
        return []


@app.get("/api/repos/{owner}/{repo}/issues")
async def get_repo_issues(owner: str, repo: str, state: str = "open"):
    return await github_client.list_issues(owner, repo, state)


@app.get("/api/repos/{owner}/{repo}/prs")
async def get_repo_prs(owner: str, repo: str, state: str = "open"):
    return await github_client.list_prs(owner, repo, state)


@app.get("/api/repos/{owner}/{repo}/branches")
async def get_repo_branches(owner: str, repo: str):
    return await github_client.list_branches(owner, repo)


# ═══════════════════════════════════════════════════════════════
# ─── SERVICES ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.get("/api/services")
async def get_services():
    return await _get_services()


async def _get_services():
    if not gcp_client.is_connected:
        return []
    try:
        services = await gcp_client.list_all_services()
        for svc in services:
            memory.update_service(svc["name"], {
                "type": svc.get("service_type", ""),
                "status": svc.get("status", "unknown"),
                "region": svc.get("region", ""),
            })
        return services
    except Exception as e:
        logger.error(f"Error fetching services: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# ─── AGENTS ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.get("/api/agents")
async def get_agents():
    return list_agents()


@app.get("/api/agents/{agent_type}/report")
async def get_agent_report(agent_type: str, repo_id: str = None):
    """Get or generate an agent's report."""
    agent = get_agent(agent_type)
    if not agent:
        raise HTTPException(404, f"Agent {agent_type} not found")

    context = {}
    if repo_id:
        # Try to resolve owner/repo from repo_id
        repos = await _get_repos()
        for r in repos:
            if r["id"] == repo_id or r["name"] == repo_id:
                parts = r["full_name"].split("/")
                context = {"owner": parts[0], "repo": parts[1]}
                break

    return await agent.generate_report(repo_id, context)


@app.get("/api/agents/{agent_type}/plan")
async def get_agent_plan(agent_type: str, repo_id: str = None):
    agent = get_agent(agent_type)
    if not agent:
        raise HTTPException(404, f"Agent {agent_type} not found")
    plan = await agent.get_plan(repo_id)
    return plan or {"steps": []}


@app.post("/api/agents/{agent_type}/plan")
async def create_agent_plan(agent_type: str, body: dict):
    agent = get_agent(agent_type)
    if not agent:
        raise HTTPException(404, f"Agent {agent_type} not found")
    command = body.get("command", "")
    repo_id = body.get("repo_id")
    steps = await agent.generate_plan(command, repo_id)
    return {"steps": steps}


# ═══════════════════════════════════════════════════════════════
# ─── TASKS ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.post("/api/tasks")
async def create_task(request: TaskCreate):
    task = await orchestrator.create_task(
        command=request.command,
        context=request.context,
        agent_type=request.agent_type.value if request.agent_type else None,
        repo_id=request.repo_id,
    )
    return task.model_dump(mode="json")


@app.get("/api/tasks")
async def list_tasks(limit: int = 20, agent_type: str = None):
    tasks = orchestrator.list_tasks(limit, agent_type)
    return [t.model_dump(mode="json") for t in tasks]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = orchestrator.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump(mode="json")


@app.post("/api/tasks/{task_id}/approve")
async def approve_step(task_id: str, request: ApprovalRequest):
    try:
        task = await orchestrator.approve_step(task_id, request.step_id, request.approved, request.comment)
        return task.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    task = await orchestrator.cancel_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump(mode="json")


@app.get("/api/tasks/{task_id}/report")
async def get_task_report(task_id: str):
    task = orchestrator.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if not task.report:
        raise HTTPException(404, "No report available yet")
    return Response(content=task.report, media_type="text/markdown",
                    headers={"Content-Disposition": f"attachment; filename=report-{task_id[:8]}.md"})


@app.get("/api/tasks/{task_id}/report/preview")
async def preview_report(task_id: str):
    task = orchestrator.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"report": task.report, "has_report": bool(task.report)}


# ═══════════════════════════════════════════════════════════════
# ─── ACTIONS (Central Manager) ────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.get("/api/actions")
async def get_actions(limit: int = 50, type: str = None, agent_type: str = None):
    return orchestrator.list_actions(limit, type, agent_type)


@app.post("/api/actions/{action_id}/complete")
async def complete_action(action_id: str):
    db.update_action_status(action_id, "completed")
    return {"status": "completed"}


@app.post("/api/actions/{action_id}/cancel")
async def cancel_action(action_id: str):
    db.update_action_status(action_id, "cancelled")
    return {"status": "cancelled"}


# ═══════════════════════════════════════════════════════════════
# ─── MEMORY ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.get("/api/memory")
async def get_memory():
    return memory.get_full_state()


@app.get("/api/memory/logs")
async def get_memory_logs(limit: int = 30):
    return memory.get_activity_log(limit)


@app.get("/api/memory/findings")
async def get_findings(limit: int = 20):
    return memory.get_findings(limit)


@app.get("/api/memory/stats")
async def get_stats():
    return {**memory.get_stats(), **db.get_stats()}


# ═══════════════════════════════════════════════════════════════
# ─── WEBSOCKET ────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "create_task":
                    task = await orchestrator.create_task(
                        msg["command"],
                        msg.get("context", {}),
                        msg.get("agent_type"),
                        msg.get("repo_id"),
                    )
                    await ws.send_json({"event_type": "task_created", "task_id": task.id, "data": {"command": task.command}})

                elif msg_type == "approve":
                    await orchestrator.approve_step(msg["task_id"], msg["step_id"], msg.get("approved", True), msg.get("comment", ""))

                elif msg_type == "get_dashboard":
                    repos = await _get_repos()
                    services = await _get_services()
                    await ws.send_json({
                        "event_type": "dashboard_state",
                        "data": {
                            "repos": repos,
                            "services": services,
                            "agents": list_agents(),
                            "stats": db.get_stats(),
                        }
                    })
            except (json.JSONDecodeError, KeyError):
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# ═══════════════════════════════════════════════════════════════
# ─── HEALTH ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "github_connected": github_client.is_connected,
        "gcp_connected": gcp_client.is_connected,
        "active_tasks": sum(1 for t in orchestrator.tasks.values() if t.status.value in ("running", "awaiting_approval", "parsing")),
        "total_tasks": len(orchestrator.tasks),
    }
