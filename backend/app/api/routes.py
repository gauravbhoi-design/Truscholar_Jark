"""API routes for the DevOps Co-Pilot platform."""

import json
import uuid

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
