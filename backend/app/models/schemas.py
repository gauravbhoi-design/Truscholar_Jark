import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ─── Enums ──────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


class AgentName(str, Enum):
    SUPERVISOR = "supervisor"
    CLOUD_DEBUGGER = "cloud_debugger"
    CODEBASE_ANALYZER = "codebase_analyzer"
    COMMIT_ANALYST = "commit_analyst"
    DEPLOYMENT_DOCTOR = "deployment_doctor"
    PERFORMANCE = "performance"
    ENGINEERING_METRICS = "engineering_metrics"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


# ─── User Schemas ───────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Conversation Schemas ───────────────────────────────────────────────────

class ConversationCreate(BaseModel):
    title: str = "New Conversation"


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    is_active: bool
    total_cost_usd: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    agent_name: str | None = None
    tool_calls: dict | None = None
    cost_usd: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Agent Schemas ──────────────────────────────────────────────────────────

class AgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000)
    conversation_id: uuid.UUID | None = None
    context: dict | None = None


class AgentResponse(BaseModel):
    conversation_id: uuid.UUID
    message: str
    agents_used: list[str]
    tool_calls: list[dict] = []
    cost_usd: float = 0.0
    status: AgentStatus


class AgentStreamEvent(BaseModel):
    event: str  # "thinking", "tool_call", "text", "done", "error"
    agent: str | None = None
    data: dict


# ─── Tool Approval ──────────────────────────────────────────────────────────

class ToolApprovalRequest(BaseModel):
    audit_log_id: uuid.UUID
    approved: bool
    reason: str | None = None


# ─── Audit Log ──────────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    id: uuid.UUID
    agent_name: str
    tool_name: str
    tool_input: dict
    tool_output: dict | None
    approved: bool
    duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Plan Mode (Human-in-the-Loop) ────────────────────────────────────────


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"


class PlanStepSchema(BaseModel):
    id: uuid.UUID | None = None
    order: int
    title: str
    description: str
    agent_name: str
    tool_name: str
    tool_input: dict
    status: PlanStepStatus = PlanStepStatus.PENDING
    result: dict | None = None
    cost_usd: float = 0.0

    model_config = {"from_attributes": True}


class PlanResponse(BaseModel):
    id: uuid.UUID
    query: str
    summary: str
    status: PlanStatus
    steps: list[PlanStepSchema]
    agents_used: list[str] | None = None
    total_cost_usd: float = 0.0
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class PlanApprovalRequest(BaseModel):
    plan_id: uuid.UUID
    action: str = Field(..., pattern="^(approve_all|reject|approve_step|skip_step)$")
    step_id: uuid.UUID | None = None  # Required for approve_step / skip_step


class StepExecutionRequest(BaseModel):
    plan_id: uuid.UUID
    step_id: uuid.UUID | None = None  # If None, execute next pending approved step
