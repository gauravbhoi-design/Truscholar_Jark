"""PreToolUse safety hooks — Gates for destructive operations requiring approval."""

import uuid
import structlog
from datetime import datetime

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Tools that require human-in-the-loop approval
DESTRUCTIVE_TOOLS = {
    # File operations
    "write_file",
    "delete_file",
    "modify_config",
    # Deployment operations
    "apply_terraform",
    "kubectl_apply",
    "kubectl_delete",
    "docker_push",
    "restart_service",
    # Database operations
    "execute_sql_write",
    "drop_table",
    "run_migration",
    # CI/CD operations
    "trigger_pipeline",
    "merge_pull_request",
    "deploy_to_production",
}

# Tools blocked entirely (never execute)
BLOCKED_TOOLS = {
    "drop_database",
    "format_disk",
    "delete_cluster",
}


class PreToolUseHook:
    """Evaluates tool calls before execution for safety gates."""

    def __init__(self, user: dict):
        self.user = user
        self.user_role = user.get("role", "viewer")

    async def evaluate(self, tool_name: str, tool_input: dict, agent_name: str) -> dict:
        """Evaluate a tool call. Returns approval status and reason.

        Returns:
            {
                "approved": bool,
                "requires_human_approval": bool,
                "reason": str,
                "audit_id": str,
            }
        """
        audit_id = str(uuid.uuid4())

        # Block dangerous tools entirely
        if tool_name in BLOCKED_TOOLS:
            logger.warning(
                "Blocked tool call",
                tool=tool_name,
                agent=agent_name,
                user=self.user.get("sub"),
            )
            return {
                "approved": False,
                "requires_human_approval": False,
                "reason": f"Tool '{tool_name}' is blocked for safety reasons",
                "audit_id": audit_id,
            }

        # Destructive tools require approval
        if tool_name in DESTRUCTIVE_TOOLS:
            # Admins get auto-approved for most operations
            if self.user_role == "admin":
                logger.info("Auto-approved destructive tool for admin", tool=tool_name)
                return {
                    "approved": True,
                    "requires_human_approval": False,
                    "reason": "Admin auto-approval",
                    "audit_id": audit_id,
                }

            # All other roles need explicit approval
            logger.info(
                "Destructive tool requires approval",
                tool=tool_name,
                agent=agent_name,
                user=self.user.get("sub"),
            )
            return {
                "approved": False,
                "requires_human_approval": True,
                "reason": f"Tool '{tool_name}' requires human approval for role '{self.user_role}'",
                "audit_id": audit_id,
            }

        # Budget check
        cost_exceeded = await self._check_budget()
        if cost_exceeded:
            return {
                "approved": False,
                "requires_human_approval": False,
                "reason": f"Session budget of ${settings.max_budget_usd} exceeded",
                "audit_id": audit_id,
            }

        # Non-destructive tools: auto-approve
        return {
            "approved": True,
            "requires_human_approval": False,
            "reason": "Non-destructive operation",
            "audit_id": audit_id,
        }

    async def _check_budget(self) -> bool:
        """Check if the session cost budget has been exceeded."""
        # In production, query Redis for session cost
        return False


class PostToolUseHook:
    """Logs all tool executions for audit trail."""

    async def log(
        self,
        audit_id: str,
        agent_name: str,
        tool_name: str,
        tool_input: dict,
        tool_output: dict,
        duration_ms: int,
        approved: bool,
        user: dict,
    ) -> None:
        """Log tool execution to audit trail."""
        log_entry = {
            "audit_id": audit_id,
            "agent": agent_name,
            "tool": tool_name,
            "input_keys": list(tool_input.keys()),
            "output_size": len(str(tool_output)),
            "duration_ms": duration_ms,
            "approved": approved,
            "user": user.get("sub"),
            "timestamp": datetime.utcnow().isoformat(),
        }

        logger.info("Tool execution logged", **log_entry)

        # In production, persist to PostgreSQL AgentAuditLog table
        # and optionally to MongoDB for full input/output storage
