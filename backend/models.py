"""
AI DevOps Platform — Data Models
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime
import uuid


# ── Enums ──────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class StepStatus(str, Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStatus(str, Enum):
    PARSING = "parsing"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentType(str, Enum):
    CODE_REVIEWER = "code_reviewer"
    TEST_RUNNER = "test_runner"
    LOG_MONITOR = "log_monitor"
    CLOUD_MONITOR = "cloud_monitor"
    ORCHESTRATOR = "orchestrator"


class ActionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TODO = "todo"


# ── Core Models ────────────────────────────────────────────────

class TaskStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    order: int
    description: str
    command: str
    tool: str
    risk_level: RiskLevel = RiskLevel.LOW
    status: StepStatus = StepStatus.PENDING
    output: str = ""
    error: str = ""
    thinking: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    approved_by: Optional[str] = None


class TaskCreate(BaseModel):
    command: str
    context: Dict[str, Any] = {}
    agent_type: Optional[AgentType] = None
    repo_id: Optional[str] = None


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command: str
    context: Dict[str, Any] = {}
    agent_type: AgentType = AgentType.ORCHESTRATOR
    repo_id: Optional[str] = None
    status: TaskStatus = TaskStatus.RUNNING
    steps: List[TaskStep] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    summary: str = ""
    report: str = ""
    error: str = ""

    def current_step(self) -> Optional[TaskStep]:
        for step in self.steps:
            if step.status in (StepStatus.PENDING, StepStatus.AWAITING_APPROVAL, StepStatus.RUNNING):
                return step
        return None


class ApprovalRequest(BaseModel):
    task_id: str = ""
    step_id: str
    approved: bool
    comment: str = ""


class TaskEvent(BaseModel):
    task_id: str
    event_type: str
    agent_type: str = "orchestrator"
    data: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Repo & Service Models ──────────────────────────────────────

class RepoInfo(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    full_name: str = ""
    language: str = ""
    default_branch: str = "main"
    stars: int = 0
    open_issues: int = 0
    open_prs: int = 0
    last_commit: Optional[str] = None
    last_commit_date: Optional[datetime] = None
    status: str = "unknown"  # healthy, warning, critical
    url: str = ""
    description: str = ""
    topics: List[str] = []
    visibility: str = "private"
    updated_at: Optional[datetime] = None


class ServiceInfo(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    service_type: str = ""  # cloud_run, gke, compute, managed_db
    region: str = ""
    status: str = "unknown"  # running, stopped, error, deploying
    cpu_usage: str = "0%"
    memory_usage: str = "0MB"
    daily_cost: str = "$0.00"
    url: str = ""
    project: str = ""
    last_deployed: Optional[datetime] = None


# ── Agent Models ───────────────────────────────────────────────

class AgentReport(BaseModel):
    """Report data for an agent's Report tab."""
    agent_type: AgentType
    repo_id: Optional[str] = None
    summary: str = ""
    items: List[Dict[str, Any]] = []
    findings: List[str] = []
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentPlanStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str
    status: str = "pending"  # pending, in_progress, done, failed
    output: str = ""


class AgentPlan(BaseModel):
    """Plan for an agent's Plan tab."""
    agent_type: AgentType
    repo_id: Optional[str] = None
    steps: List[AgentPlanStep] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Action (Central Manager) ──────────────────────────────────

class Action(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: ActionStatus = ActionStatus.PENDING
    agent_type: AgentType = AgentType.ORCHESTRATOR
    description: str = ""
    detail: str = ""
    severity: str = "low"  # low, medium, high, critical
    task_id: Optional[str] = None
    repo_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# ── Memory System ──────────────────────────────────────────────

class MemoryEntry(BaseModel):
    key: str
    value: Any
    category: str = "general"  # repos, infra, credentials, findings, agents, tasks
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = "system"


class SystemMemory(BaseModel):
    repos: Dict[str, Any] = {}
    services: Dict[str, Any] = {}
    infra: Dict[str, Any] = {}
    credentials: Dict[str, str] = {}
    recent_findings: List[str] = []
    agent_states: Dict[str, Any] = {}
    task_history: List[Dict[str, Any]] = []
    activity_log: List[Dict[str, str]] = []
    stats: Dict[str, Any] = {}
    last_updated: datetime = Field(default_factory=datetime.utcnow)


# ── API Response Models ────────────────────────────────────────

class DashboardState(BaseModel):
    repos: List[RepoInfo] = []
    services: List[ServiceInfo] = []
    agents: List[Dict[str, Any]] = []
    actions: List[Action] = []
    memory: SystemMemory = SystemMemory()
    tasks: List[Task] = []
    stats: Dict[str, Any] = {}
