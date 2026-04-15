"""API routes for the DevOps Co-Pilot platform."""

import json
import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_role
from app.api.gcp_oauth import router as gcp_oauth_router
from app.api.github_app import router as github_app_router
from app.api.github_oauth import router as github_oauth_router
from app.api.metrics_routes import router as metrics_router
from app.api.zoho_oauth import router as zoho_oauth_router
from app.config import get_settings
from app.models.database import get_db
from app.models.schemas import (
    AgentRequest,
    AgentResponse,
    ConversationCreate,
    ConversationResponse,
    PlanApprovalRequest,
    PlanResponse,
    StepExecutionRequest,
    UserRole,
)
from app.services.orchestrator import AgentOrchestrator

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter()

# Include OAuth routes
router.include_router(github_oauth_router)
router.include_router(gcp_oauth_router)
router.include_router(zoho_oauth_router)
router.include_router(metrics_router)
router.include_router(github_app_router)


# ─── Agent Endpoints ────────────────────────────────────────────────────────


@router.post("/agent/query", response_model=AgentResponse)
async def agent_query(
    request: AgentRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a query to the AI agent orchestrator."""
    orchestrator = AgentOrchestrator(db=db, user=user)
    try:
        result = await orchestrator.process_query(
            query=request.query,
            conversation_id=request.conversation_id,
            context=request.context,
        )
        return result
    except Exception as e:
        logger.error("Agent query failed", error=str(e), user=user.get("sub"))
        raise HTTPException(status_code=500, detail="Agent processing failed")


@router.post("/agent/query/stream")
async def agent_query_stream(
    request: AgentRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream agent execution events via Server-Sent Events (SSE)."""
    orchestrator = AgentOrchestrator(db=db, user=user)

    async def event_generator():
        try:
            async for event in orchestrator.process_query_stream(
                query=request.query,
                conversation_id=request.conversation_id,
                context=request.context,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error("SSE stream error", error=str(e))
            yield f"data: {json.dumps({'event': 'error', 'agent': None, 'data': {'message': str(e)}})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Live Log Streaming ────────────────────────────────────────────────────


@router.get("/agent/logs/stream")
async def stream_live_logs(
    project_id: str | None = None,
    resource_type: str | None = None,
    service_name: str | None = None,
    severity: str = "DEFAULT",
    filter: str | None = None,
    duration: int = 120,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream live GCP logs via Server-Sent Events."""
    from app.api.gcp_oauth import get_user_gcp_access_token
    from app.mcp.gcp import GCPMCPClient

    user_id = user.get("sub", user.get("login", ""))
    token_result = await get_user_gcp_access_token(user_id, db)
    if not token_result:
        raise HTTPException(status_code=403, detail="No GCP connection. Connect GCP in Settings.")

    access_token, default_project = token_result
    target_project = project_id or default_project

    client = GCPMCPClient(user_access_token=access_token, project_id=target_project)

    async def event_generator():
        import json as json_mod

        # Send initial metadata
        yield f"data: {json_mod.dumps({'event': 'connected', 'project_id': target_project, 'filter': filter or '', 'severity': severity})}\n\n"

        try:
            # Try gRPC tail first, fall back to REST polling
            try:
                async for entry in client.tail_logs(
                    project_id=target_project,
                    resource_type=resource_type,
                    service_name=service_name,
                    severity=severity,
                    custom_filter=filter,
                ):
                    if "error" in entry:
                        # gRPC failed, switch to REST
                        raise Exception(entry["error"])
                    yield f"data: {json_mod.dumps({'event': 'log', **entry})}\n\n"
            except Exception as grpc_err:
                logger.info("gRPC tail failed, falling back to REST polling", error=str(grpc_err))
                yield f"data: {json_mod.dumps({'event': 'info', 'message': 'Using REST polling mode'})}\n\n"

                filter_query = ""
                parts = []
                if severity and severity != "DEFAULT":
                    parts.append(f"severity>={severity}")
                if resource_type:
                    parts.append(f'resource.type="{resource_type}"')
                if service_name:
                    parts.append(f'(resource.labels.service_name="{service_name}" OR textPayload:"{service_name}")')
                if filter:
                    parts.append(filter)
                filter_query = " AND ".join(parts)

                async for entry in client.tail_logs_rest(
                    project_id=target_project,
                    filter_query=filter_query,
                    duration_seconds=min(duration, 300),
                ):
                    if "error" in entry:
                        yield f"data: {json_mod.dumps({'event': 'error', 'message': entry['error']})}\n\n"
                        break
                    if "done" in entry:
                        yield f"data: {json_mod.dumps({'event': 'done', 'message': entry.get('message', 'Stream ended')})}\n\n"
                        break
                    yield f"data: {json_mod.dumps({'event': 'log', **entry})}\n\n"

        except Exception as e:
            yield f"data: {json_mod.dumps({'event': 'error', 'message': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Plan Mode (Human-in-the-Loop) ─────────────────────────────────────────


@router.post("/agent/plan", response_model=PlanResponse)
async def generate_plan(
    request: AgentRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an execution plan for user approval before running."""
    orchestrator = AgentOrchestrator(db=db, user=user)
    return await orchestrator.generate_plan(
        query=request.query,
        context=request.context,
    )


@router.post("/agent/plan/approve")
async def approve_plan(
    request: PlanApprovalRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve, reject, or modify a plan."""
    from sqlalchemy import select

    from app.models.database import Plan, PlanStep

    plan_result = await db.execute(select(Plan).where(Plan.id == request.plan_id))
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if request.action == "approve_all":
        plan.status = "approved"
        steps_result = await db.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id, PlanStep.status == "pending")
        )
        for step in steps_result.scalars():
            step.status = "approved"
        await db.commit()
        return {"status": "approved", "plan_id": str(plan.id)}

    elif request.action == "reject":
        plan.status = "rejected"
        await db.commit()
        return {"status": "rejected", "plan_id": str(plan.id)}

    elif request.action == "approve_step" and request.step_id:
        step_result = await db.execute(
            select(PlanStep).where(PlanStep.id == request.step_id, PlanStep.plan_id == plan.id)
        )
        approve_step = step_result.scalar_one_or_none()
        if approve_step:
            approve_step.status = "approved"
            await db.commit()
        return {"status": "step_approved", "step_id": str(request.step_id)}

    elif request.action == "skip_step" and request.step_id:
        step_result = await db.execute(
            select(PlanStep).where(PlanStep.id == request.step_id, PlanStep.plan_id == plan.id)
        )
        skip_step = step_result.scalar_one_or_none()
        if skip_step:
            skip_step.status = "skipped"
            await db.commit()
        return {"status": "step_skipped", "step_id": str(request.step_id)}

    raise HTTPException(status_code=400, detail="Invalid action")


@router.post("/agent/plan/execute-step")
async def execute_plan_step(
    request: StepExecutionRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a single approved step from a plan."""
    orchestrator = AgentOrchestrator(db=db, user=user)
    result = await orchestrator.execute_plan_step(
        plan_id=request.plan_id,
        step_id=request.step_id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/agent/plans")
async def list_plans(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent plans for the current user."""
    from sqlalchemy import select

    from app.models.database import Plan

    user_id = user.get("sub", user.get("login", ""))
    result = await db.execute(
        select(Plan).where(Plan.user_id == user_id).order_by(Plan.created_at.desc()).limit(20)
    )
    plans = result.scalars().all()
    return [{"id": str(p.id), "query": p.query, "summary": p.summary, "status": p.status, "created_at": str(p.created_at)} for p in plans]


# ─── Conversation Endpoints ─────────────────────────────────────────────────


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    data: ConversationCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation."""
    from app.models.database import Conversation

    conv = Conversation(
        user_id=user.get("db_id", uuid.uuid4()),
        title=data.title,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversations for the current user."""
    from sqlalchemy import select

    from app.models.database import Conversation

    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.get("db_id"))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get messages for a conversation."""
    from sqlalchemy import select

    from app.models.database import Message

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()


# ─── Memory Endpoints ──────────────────────────────────────────────────────


@router.get("/memory/analyses")
async def get_memory_analyses(
    query: str = "",
    limit: int = 10,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search or list past analyses from agent memory."""
    from app.services.memory import MemoryService
    user_id = user.get("sub", user.get("login", ""))
    memory = MemoryService(db=db, user_id=user_id)

    if query:
        return await memory.search_memories(query, limit=limit)
    return await memory.get_recent_analyses(limit=limit)


@router.get("/memory/preferences")
async def get_preferences(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all user preferences."""
    from app.services.memory import MemoryService
    user_id = user.get("sub", user.get("login", ""))
    memory = MemoryService(db=db, user_id=user_id)
    return await memory.get_all_preferences()


@router.post("/memory/preferences")
async def set_preference(
    request: dict,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a user preference."""
    from app.services.memory import MemoryService
    user_id = user.get("sub", user.get("login", ""))
    memory = MemoryService(db=db, user_id=user_id)

    key = request.get("key", "")
    value = request.get("value", "")
    if not key:
        raise HTTPException(status_code=400, detail="Key is required")

    await memory.set_preference(key, value)
    await db.commit()
    return {"status": "saved", "key": key}


# ─── Audit Endpoints ────────────────────────────────────────────────────────


@router.get("/audit/logs")
async def get_audit_logs(
    limit: int = 50,
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.ENGINEER)),
    db: AsyncSession = Depends(get_db),
):
    """Get agent audit logs."""
    from sqlalchemy import select

    from app.models.database import AgentAuditLog

    result = await db.execute(
        select(AgentAuditLog).order_by(AgentAuditLog.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


# ─── Admin Endpoints ────────────────────────────────────────────────────────


@router.get("/admin/stats")
async def get_stats(
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Get platform usage stats."""
    from sqlalchemy import func, select

    from app.models.database import AgentAuditLog, Conversation, User

    users_count = await db.scalar(select(func.count(User.id)))
    conversations_count = await db.scalar(select(func.count(Conversation.id)))
    total_cost = await db.scalar(select(func.sum(Conversation.total_cost_usd))) or 0.0
    audit_count = await db.scalar(select(func.count(AgentAuditLog.id)))

    return {
        "total_users": users_count,
        "total_conversations": conversations_count,
        "total_cost_usd": round(total_cost, 2),
        "total_agent_actions": audit_count,
    }


@router.get("/admin/users")
async def list_all_users(
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """List every user with usage and cost aggregates for the admin panel.

    Joins users → conversations to compute per-user totals. Plan and
    GitHub-App-Installation counts are joined separately by JWT-sub since
    those tables key on the string sub instead of the User UUID.
    """
    from sqlalchemy import func, select

    from app.models.database import (
        Conversation,
        GitHubAppInstallation,
        Message,
        Plan,
        User,
    )

    # Per-user conversation + cost aggregates
    conv_agg = (
        select(
            Conversation.user_id.label("user_id"),
            func.count(Conversation.id).label("conversation_count"),
            func.coalesce(func.sum(Conversation.total_cost_usd), 0.0).label("conversation_cost"),
            func.max(Conversation.updated_at).label("last_conversation_at"),
        )
        .group_by(Conversation.user_id)
        .subquery()
    )

    # Per-user message count (joined through conversations)
    msg_agg = (
        select(
            Conversation.user_id.label("user_id"),
            func.count(Message.id).label("message_count"),
        )
        .join(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.user_id)
        .subquery()
    )

    # Plans key on JWT sub (string), join via User.auth0_sub
    plan_agg = (
        select(
            Plan.user_id.label("sub"),
            func.count(Plan.id).label("plan_count"),
            func.coalesce(func.sum(Plan.total_cost_usd), 0.0).label("plan_cost"),
        )
        .group_by(Plan.user_id)
        .subquery()
    )

    install_agg = (
        select(
            GitHubAppInstallation.user_id.label("sub"),
            func.count(GitHubAppInstallation.id).label("installation_count"),
        )
        .where(GitHubAppInstallation.is_active == True)
        .group_by(GitHubAppInstallation.user_id)
        .subquery()
    )

    # Most-used agent per user — pick the agent with the highest message
    # count, falling back to None if the user has no messages.
    primary_agent_agg = (
        select(
            Conversation.user_id.label("user_id"),
            Message.agent_name.label("agent_name"),
            func.count(Message.id).label("agent_msg_count"),
        )
        .join(Message, Message.conversation_id == Conversation.id)
        .where(Message.agent_name.isnot(None))
        .group_by(Conversation.user_id, Message.agent_name)
        .subquery()
    )

    query = (
        select(
            User.id,
            User.email,
            User.name,
            User.login,
            User.avatar_url,
            User.role,
            User.is_active,
            User.created_at,
            User.last_login_at,
            User.login_count,
            func.coalesce(conv_agg.c.conversation_count, 0).label("conversation_count"),
            func.coalesce(conv_agg.c.conversation_cost, 0.0).label("conversation_cost"),
            conv_agg.c.last_conversation_at,
            func.coalesce(msg_agg.c.message_count, 0).label("message_count"),
            func.coalesce(plan_agg.c.plan_count, 0).label("plan_count"),
            func.coalesce(plan_agg.c.plan_cost, 0.0).label("plan_cost"),
            func.coalesce(install_agg.c.installation_count, 0).label("installation_count"),
        )
        .outerjoin(conv_agg, conv_agg.c.user_id == User.id)
        .outerjoin(msg_agg, msg_agg.c.user_id == User.id)
        .outerjoin(plan_agg, plan_agg.c.sub == User.auth0_sub)
        .outerjoin(install_agg, install_agg.c.sub == User.auth0_sub)
    )

    result = await db.execute(query)
    rows = result.all()

    # Compute primary agent per user (separate query — joining inline
    # would force a complex window function).
    primary_agents: dict[str, str] = {}
    pa_result = await db.execute(
        select(
            primary_agent_agg.c.user_id,
            primary_agent_agg.c.agent_name,
            primary_agent_agg.c.agent_msg_count,
        ).order_by(primary_agent_agg.c.user_id, primary_agent_agg.c.agent_msg_count.desc())
    )
    for pa_row in pa_result.all():
        if str(pa_row.user_id) not in primary_agents:
            primary_agents[str(pa_row.user_id)] = pa_row.agent_name

    users_out = []
    grand_cost = 0.0
    for r in rows:
        total_cost = float(r.conversation_cost or 0.0) + float(r.plan_cost or 0.0)
        grand_cost += total_cost
        # Last activity = max(last_login, last_conversation)
        last_active = None
        for ts in (r.last_login_at, r.last_conversation_at):
            if ts and (last_active is None or ts > last_active):
                last_active = ts
        users_out.append({
            "id": str(r.id),
            "email": r.email,
            "name": r.name,
            "login": r.login,
            "avatar_url": r.avatar_url,
            "role": r.role,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_login_at": r.last_login_at.isoformat() if r.last_login_at else None,
            "last_active_at": last_active.isoformat() if last_active else None,
            "login_count": int(r.login_count or 0),
            "primary_agent": primary_agents.get(str(r.id)),
            "conversation_count": int(r.conversation_count or 0),
            "message_count": int(r.message_count or 0),
            "plan_count": int(r.plan_count or 0),
            "installation_count": int(r.installation_count or 0),
            "total_cost_usd": round(total_cost, 4),
        })

    # Sort by total cost descending — most expensive users first
    users_out.sort(key=lambda u: u["total_cost_usd"], reverse=True)

    return {
        "total_users": len(users_out),
        "total_cost_usd": round(grand_cost, 4),
        "users": users_out,
    }


@router.patch("/admin/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    payload: dict,
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Promote or demote a user (admin / engineer / viewer)."""
    from sqlalchemy import select

    from app.models.database import User

    new_role = payload.get("role", "")
    if new_role not in {r.value for r in UserRole}:
        raise HTTPException(status_code=400, detail=f"Invalid role: {new_role}")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Don't let an admin demote themselves into a lockout
    if str(target.id) == user.get("db_id") and new_role != "admin":
        raise HTTPException(status_code=400, detail="You can't demote yourself")

    target.role = new_role
    await db.commit()
    return {"id": str(target.id), "role": target.role}


@router.get("/admin/users/{user_id}")
async def get_user_detail(
    user_id: uuid.UUID,
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Drill-down on a single user — agent breakdown, tool breakdown,
    connected services, recent activity, and a 30-day cost trend.
    """
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.models.database import (
        AgentAuditLog,
        CloudCredential,
        Conversation,
        GitHubAppInstallation,
        Message,
        Plan,
        User,
    )

    # ─── 1. The user row itself ───────────────────────────────────────
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    sub = target.auth0_sub  # for tables that key on the JWT sub string

    # ─── 2. Per-agent usage ───────────────────────────────────────────
    agent_q = await db.execute(
        select(
            Message.agent_name,
            func.count(Message.id).label("msg_count"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("agent_cost"),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id)
        .where(Message.agent_name.isnot(None))
        .group_by(Message.agent_name)
        .order_by(func.count(Message.id).desc())
    )
    per_agent = [
        {
            "agent": r.agent_name,
            "message_count": int(r.msg_count),
            "cost_usd": round(float(r.agent_cost or 0.0), 4),
        }
        for r in agent_q.all()
    ]

    # ─── 3. Per-tool usage (from audit log) ───────────────────────────
    tool_q = await db.execute(
        select(
            AgentAuditLog.tool_name,
            AgentAuditLog.agent_name,
            func.count(AgentAuditLog.id).label("call_count"),
            func.coalesce(func.avg(AgentAuditLog.duration_ms), 0).label("avg_ms"),
        )
        .join(Conversation, Conversation.id == AgentAuditLog.conversation_id)
        .where(Conversation.user_id == user_id)
        .group_by(AgentAuditLog.tool_name, AgentAuditLog.agent_name)
        .order_by(func.count(AgentAuditLog.id).desc())
        .limit(50)
    )
    per_tool = [
        {
            "tool": r.tool_name,
            "agent": r.agent_name,
            "call_count": int(r.call_count),
            "avg_duration_ms": int(r.avg_ms or 0),
            "kind": "cli" if r.tool_name in ("run_shell", "run_command") else "mcp",
        }
        for r in tool_q.all()
    ]

    # MCP vs CLI split
    cli_calls = sum(t["call_count"] for t in per_tool if t["kind"] == "cli")
    mcp_calls = sum(t["call_count"] for t in per_tool if t["kind"] == "mcp")

    # ─── 4. Connected services ────────────────────────────────────────
    services: list[dict] = []
    if sub:
        cred_q = await db.execute(
            select(CloudCredential).where(CloudCredential.user_id == sub)
        )
        for c in cred_q.scalars().all():
            services.append({
                "provider": c.provider,
                "email": c.email,
                "project_id": c.project_id,
                "is_active": c.is_active,
                "connected_at": c.connected_at.isoformat() if c.connected_at else None,
                "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
            })

    installs: list[dict] = []
    if sub:
        inst_q = await db.execute(
            select(GitHubAppInstallation).where(GitHubAppInstallation.user_id == sub)
        )
        for i in inst_q.scalars().all():
            installs.append({
                "installation_id": i.installation_id,
                "account_login": i.account_login,
                "account_type": i.account_type,
                "is_active": i.is_active,
                "installed_at": i.installed_at.isoformat() if i.installed_at else None,
            })

    # ─── 5. Recent conversations ──────────────────────────────────────
    conv_q = await db.execute(
        select(
            Conversation.id,
            Conversation.title,
            Conversation.total_cost_usd,
            Conversation.created_at,
            Conversation.updated_at,
            func.count(Message.id).label("msg_count"),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .limit(20)
    )
    recent_conversations = [
        {
            "id": str(c.id),
            "title": c.title,
            "message_count": int(c.msg_count or 0),
            "cost_usd": round(float(c.total_cost_usd or 0.0), 4),
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conv_q.all()
    ]

    # ─── 6. Recent audit log entries (what they actually ran) ─────────
    audit_q = await db.execute(
        select(AgentAuditLog)
        .join(Conversation, Conversation.id == AgentAuditLog.conversation_id)
        .where(Conversation.user_id == user_id)
        .order_by(AgentAuditLog.created_at.desc())
        .limit(30)
    )
    recent_audit = [
        {
            "id": str(a.id),
            "agent": a.agent_name,
            "tool": a.tool_name,
            "duration_ms": a.duration_ms,
            "approved": a.approved,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            # Truncated input summary so the response stays bounded
            "tool_input_preview": str(a.tool_input)[:200] if a.tool_input else None,
        }
        for a in audit_q.scalars().all()
    ]

    # ─── 7. 30-day cost trend (daily buckets) ─────────────────────────
    thirty_days_ago = datetime.now() - timedelta(days=30)
    cost_q = await db.execute(
        select(
            func.date(Message.created_at).label("day"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("day_cost"),
            func.count(Message.id).label("day_msgs"),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id)
        .where(Message.created_at >= thirty_days_ago)
        .group_by(func.date(Message.created_at))
        .order_by(func.date(Message.created_at))
    )
    cost_trend = [
        {
            "date": str(r.day),
            "cost_usd": round(float(r.day_cost or 0.0), 4),
            "message_count": int(r.day_msgs or 0),
        }
        for r in cost_q.all()
    ]

    # ─── 8. Plan count + cost (keyed on string sub) ───────────────────
    plan_count = 0
    plan_cost = 0.0
    if sub:
        plan_row = await db.execute(
            select(
                func.count(Plan.id),
                func.coalesce(func.sum(Plan.total_cost_usd), 0.0),
            ).where(Plan.user_id == sub)
        )
        pc, pt = plan_row.one()
        plan_count = int(pc or 0)
        plan_cost = float(pt or 0.0)

    # Total cost = conversations + plans
    conv_total_row = await db.execute(
        select(func.coalesce(func.sum(Conversation.total_cost_usd), 0.0))
        .where(Conversation.user_id == user_id)
    )
    conv_total = float(conv_total_row.scalar() or 0.0)

    return {
        "user": {
            "id": str(target.id),
            "email": target.email,
            "name": target.name,
            "login": target.login,
            "avatar_url": target.avatar_url,
            "role": target.role,
            "is_active": target.is_active,
            "created_at": target.created_at.isoformat() if target.created_at else None,
            "last_login_at": target.last_login_at.isoformat() if target.last_login_at else None,
            "login_count": int(target.login_count or 0),
            "auth0_sub": target.auth0_sub,
        },
        "totals": {
            "conversation_count": len(recent_conversations),  # 20-cap; raw count via /admin/users
            "plan_count": plan_count,
            "conversation_cost_usd": round(conv_total, 4),
            "plan_cost_usd": round(plan_cost, 4),
            "total_cost_usd": round(conv_total + plan_cost, 4),
            "tool_calls_total": cli_calls + mcp_calls,
            "tool_calls_cli": cli_calls,
            "tool_calls_mcp": mcp_calls,
        },
        "per_agent": per_agent,
        "per_tool": per_tool,
        "services": services,
        "github_app_installations": installs,
        "recent_conversations": recent_conversations,
        "recent_audit_log": recent_audit,
        "cost_trend_30d": cost_trend,
    }


@router.get("/admin/activity")
async def get_platform_activity(
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Platform-wide usage stats — DAU/WAU/MAU, top agents, top tools,
    cost trend. Drives the activity header in the admin panel.
    """
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.models.database import (
        AgentAuditLog,
        Conversation,
        Message,
        User,
    )

    now = datetime.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # ─── DAU / WAU / MAU ──────────────────────────────────────────────
    # Active = had a message-producing event in the window. Falls back
    # to last_login_at for users with no messages yet.
    async def _active_users_since(since: datetime) -> int:
        # Users with messages in the window
        msg_users = await db.execute(
            select(func.count(func.distinct(Conversation.user_id)))
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.created_at >= since)
        )
        msg_count = msg_users.scalar() or 0

        # Users who at least logged in in the window (covers no-message users)
        login_users = await db.execute(
            select(func.count(User.id)).where(User.last_login_at >= since)
        )
        login_count = login_users.scalar() or 0

        # Conservative max — same user might be in both sets, but this
        # bounds the count without an expensive UNION DISTINCT.
        return max(msg_count, login_count)

    dau = await _active_users_since(day_ago)
    wau = await _active_users_since(week_ago)
    mau = await _active_users_since(month_ago)

    total_users = await db.scalar(select(func.count(User.id))) or 0
    new_users_30d = await db.scalar(
        select(func.count(User.id)).where(User.created_at >= month_ago)
    ) or 0

    # ─── Top agents by message count ──────────────────────────────────
    top_agents_q = await db.execute(
        select(
            Message.agent_name,
            func.count(Message.id).label("calls"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("cost"),
        )
        .where(Message.agent_name.isnot(None))
        .group_by(Message.agent_name)
        .order_by(func.count(Message.id).desc())
        .limit(5)
    )
    top_agents = [
        {
            "agent": r.agent_name,
            "calls": int(r.calls),
            "cost_usd": round(float(r.cost or 0.0), 4),
        }
        for r in top_agents_q.all()
    ]

    # ─── Top tools by call count ──────────────────────────────────────
    top_tools_q = await db.execute(
        select(
            AgentAuditLog.tool_name,
            func.count(AgentAuditLog.id).label("calls"),
        )
        .group_by(AgentAuditLog.tool_name)
        .order_by(func.count(AgentAuditLog.id).desc())
        .limit(10)
    )
    top_tools = [
        {
            "tool": r.tool_name,
            "calls": int(r.calls),
            "kind": "cli" if r.tool_name in ("run_shell", "run_command") else "mcp",
        }
        for r in top_tools_q.all()
    ]

    # ─── Cost trend (last 7 days, daily buckets) ──────────────────────
    cost_q = await db.execute(
        select(
            func.date(Message.created_at).label("day"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("cost"),
            func.count(Message.id).label("msgs"),
        )
        .where(Message.created_at >= week_ago)
        .group_by(func.date(Message.created_at))
        .order_by(func.date(Message.created_at))
    )
    cost_trend_7d = [
        {
            "date": str(r.day),
            "cost_usd": round(float(r.cost or 0.0), 4),
            "message_count": int(r.msgs or 0),
        }
        for r in cost_q.all()
    ]

    return {
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "total_users": total_users,
        "new_users_30d": new_users_30d,
        "top_agents": top_agents,
        "top_tools": top_tools,
        "cost_trend_7d": cost_trend_7d,
    }


# ─── Billing Dashboard ─────────────────────────────────────────────────────


@router.get("/admin/billing")
async def get_billing_dashboard(
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Admin billing dashboard data.

    Returns platform-wide spend totals (today/7d/30d/MTD/all-time),
    daily cost trend (last 30 days), per-agent breakdown,
    per-model breakdown, and top 10 users by spend — all driven
    directly off the messages table.
    """
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.models.database import Conversation, Message, User

    now = datetime.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ─── Spend totals at various time horizons ───────────────────────
    async def _window_totals(since):
        q = select(
            func.coalesce(func.sum(Message.cost_usd), 0.0),
            func.coalesce(func.sum(Message.input_tokens), 0),
            func.coalesce(func.sum(Message.output_tokens), 0),
            func.count(Message.id),
        ).where(Message.cost_usd > 0)
        if since is not None:
            q = q.where(Message.created_at >= since)
        row = (await db.execute(q)).one()
        return {
            "cost_usd": round(float(row[0] or 0.0), 4),
            "input_tokens": int(row[1] or 0),
            "output_tokens": int(row[2] or 0),
            "message_count": int(row[3] or 0),
        }

    today = await _window_totals(day_ago)
    last_7d = await _window_totals(week_ago)
    last_30d = await _window_totals(month_ago)
    mtd = await _window_totals(mtd_start)
    all_time = await _window_totals(None)

    # ─── Daily trend (last 30 days) ──────────────────────────────────
    trend_q = await db.execute(
        select(
            func.date(Message.created_at).label("day"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("cost"),
            func.coalesce(func.sum(Message.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(Message.output_tokens), 0).label("out_tok"),
            func.count(Message.id).label("msgs"),
        )
        .where(Message.created_at >= month_ago)
        .where(Message.cost_usd > 0)
        .group_by(func.date(Message.created_at))
        .order_by(func.date(Message.created_at))
    )
    daily_trend = [
        {
            "date": str(r.day),
            "cost_usd": round(float(r.cost or 0.0), 4),
            "input_tokens": int(r.in_tok or 0),
            "output_tokens": int(r.out_tok or 0),
            "message_count": int(r.msgs or 0),
        }
        for r in trend_q.all()
    ]

    # ─── Per-agent breakdown ──────────────────────────────────────────
    agent_q = await db.execute(
        select(
            Message.agent_name,
            func.count(Message.id).label("calls"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("cost"),
            func.coalesce(func.sum(Message.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(Message.output_tokens), 0).label("out_tok"),
            func.coalesce(func.avg(Message.cost_usd), 0.0).label("avg_cost"),
        )
        .where(Message.agent_name.isnot(None))
        .where(Message.cost_usd > 0)
        .group_by(Message.agent_name)
        .order_by(func.sum(Message.cost_usd).desc())
    )
    per_agent = [
        {
            "agent": r.agent_name,
            "calls": int(r.calls),
            "cost_usd": round(float(r.cost or 0.0), 4),
            "input_tokens": int(r.in_tok or 0),
            "output_tokens": int(r.out_tok or 0),
            "avg_cost_usd": round(float(r.avg_cost or 0.0), 6),
        }
        for r in agent_q.all()
    ]

    # ─── Per-model breakdown ──────────────────────────────────────────
    model_q = await db.execute(
        select(
            Message.model,
            func.count(Message.id).label("calls"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("cost"),
            func.coalesce(func.sum(Message.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(Message.output_tokens), 0).label("out_tok"),
        )
        .where(Message.model.isnot(None))
        .where(Message.cost_usd > 0)
        .group_by(Message.model)
        .order_by(func.sum(Message.cost_usd).desc())
    )
    per_model = [
        {
            "model": r.model,
            "calls": int(r.calls),
            "cost_usd": round(float(r.cost or 0.0), 4),
            "input_tokens": int(r.in_tok or 0),
            "output_tokens": int(r.out_tok or 0),
        }
        for r in model_q.all()
    ]

    # ─── Top 10 users by spend ───────────────────────────────────────
    top_users_q = await db.execute(
        select(
            User.id,
            User.email,
            User.name,
            User.login,
            User.avatar_url,
            func.count(Message.id).label("msgs"),
            func.coalesce(func.sum(Message.cost_usd), 0.0).label("cost"),
            func.coalesce(func.sum(Message.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(Message.output_tokens), 0).label("out_tok"),
        )
        .join(Conversation, Conversation.user_id == User.id)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(Message.cost_usd > 0)
        .group_by(User.id)
        .order_by(func.sum(Message.cost_usd).desc())
        .limit(10)
    )
    top_users = [
        {
            "id": str(r.id),
            "email": r.email,
            "name": r.name,
            "login": r.login,
            "avatar_url": r.avatar_url,
            "message_count": int(r.msgs or 0),
            "cost_usd": round(float(r.cost or 0.0), 4),
            "input_tokens": int(r.in_tok or 0),
            "output_tokens": int(r.out_tok or 0),
        }
        for r in top_users_q.all()
    ]

    # ─── Projected monthly spend ──────────────────────────────────────
    # Simple linear extrapolation: MTD cost / days elapsed * days in month
    import calendar as _cal

    days_in_month = _cal.monthrange(now.year, now.month)[1]
    days_elapsed = max(1, now.day)
    projected_monthly = round(
        (mtd["cost_usd"] / days_elapsed) * days_in_month,
        2,
    )

    return {
        "totals": {
            "today": today,
            "last_7d": last_7d,
            "last_30d": last_30d,
            "mtd": mtd,
            "all_time": all_time,
        },
        "projected_monthly_usd": projected_monthly,
        "daily_trend_30d": daily_trend,
        "per_agent": per_agent,
        "per_model": per_model,
        "top_users": top_users,
    }


# ─── DB Inspector ───────────────────────────────────────────────────────────
#
# Lets an admin browse production Cloud SQL data without needing psql or
# the Cloud SQL proxy. Returns row counts for every table and a sample of
# the most recent rows from each, with sensitive columns masked.

# Columns whose values are PII, secrets, or huge blobs — masked in output.
_SENSITIVE_COLUMNS = {
    "encrypted_refresh_token",
    "key_hash",
    "tool_input",
    "tool_output",
    "payload_summary",
    "permissions",
    "events",
    "selected_repositories",
    "metrics_data",
    "scores",
    "responses",
    "context",
    "extra_data",
    "tool_calls",
    "agents_used",
    "result",
    "content",  # Message bodies can be huge
}

# Tables we expose. Listed explicitly so a future model addition doesn't
# accidentally leak data without review.
_INSPECTABLE_TABLES = [
    "users",
    "conversations",
    "messages",
    "agent_audit_logs",
    "agent_memories",
    "user_preferences",
    "cloud_credentials",
    "plans",
    "plan_steps",
    "github_app_installations",
    "webhook_events",
    "api_keys",
    "teams",
    "metric_snapshots",
    "metric_data_points",
    "survey_responses",
]


def _mask_row(row: dict) -> dict:
    """Mask sensitive columns and truncate large strings for display."""
    out = {}
    for k, v in row.items():
        if k in _SENSITIVE_COLUMNS:
            if v is None:
                out[k] = None
            elif isinstance(v, (dict, list)):
                out[k] = f"<{type(v).__name__} {len(v)} items>"
            elif isinstance(v, str):
                out[k] = f"<masked, {len(v)} chars>"
            else:
                out[k] = "<masked>"
        elif isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + f"…[+{len(v) - 200} chars]"
        elif hasattr(v, "isoformat"):  # datetime
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


@router.get("/admin/db/inspect")
async def db_inspect(
    table: str | None = None,
    limit: int = 10,
    user: dict = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Browse Cloud SQL production data.

    Without `?table=` returns a summary: every inspectable table with
    its row count plus the column list. With `?table=name&limit=N`
    returns the N most recent rows of that table (sorted by created_at
    or id desc) with sensitive columns masked.
    """
    from sqlalchemy import text

    safe_limit = max(1, min(limit, 100))

    # ── Summary mode (no table specified) ──────────────────────────
    if not table:
        summary = []
        for t in _INSPECTABLE_TABLES:
            try:
                count_q = await db.execute(text(f"SELECT COUNT(*) FROM {t}"))
                count = count_q.scalar() or 0
                col_q = await db.execute(text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = :t ORDER BY ordinal_position"
                ), {"t": t})
                columns = [{"name": c.column_name, "type": c.data_type} for c in col_q.all()]
                summary.append({
                    "table": t,
                    "row_count": int(count),
                    "columns": columns,
                })
            except Exception as e:
                summary.append({"table": t, "error": str(e)[:200]})

        total_rows = sum(s.get("row_count", 0) for s in summary)
        return {
            "database": settings.postgres_db if hasattr(settings, "postgres_db") else None,
            "total_tables": len(summary),
            "total_rows": total_rows,
            "tables": summary,
            "usage": "Append ?table=<name>&limit=<n> to fetch sample rows from a specific table.",
        }

    # ── Detail mode (table specified) ──────────────────────────────
    if table not in _INSPECTABLE_TABLES:
        raise HTTPException(
            status_code=400,
            detail=f"Table '{table}' is not in the inspectable allowlist. "
                   f"Allowed: {', '.join(_INSPECTABLE_TABLES)}",
        )

    # Find a column to sort by — prefer created_at, fall back to id
    col_q = await db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :t"
    ), {"t": table})
    col_names = {c.column_name for c in col_q.all()}

    if "created_at" in col_names:
        order_by = "created_at DESC"
    elif "installed_at" in col_names:
        order_by = "installed_at DESC"
    elif "connected_at" in col_names:
        order_by = "connected_at DESC"
    elif "id" in col_names:
        order_by = "id DESC"
    else:
        order_by = "1"

    rows_q = await db.execute(text(f"SELECT * FROM {table} ORDER BY {order_by} LIMIT :lim"), {"lim": safe_limit})
    rows = [_mask_row(dict(r._mapping)) for r in rows_q.all()]

    count_q = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))
    total = int(count_q.scalar() or 0)

    return {
        "table": table,
        "total_rows": total,
        "returned": len(rows),
        "ordered_by": order_by,
        "rows": rows,
    }
