"""
Approval Gate — Determines whether a step can auto-execute or needs human approval.
"""

from models import TaskStep, RiskLevel
from config import settings


def needs_approval(step: TaskStep) -> bool:
    """Check if a step requires human approval before execution."""

    # Critical risk always needs approval
    if step.risk_level == RiskLevel.CRITICAL:
        return True

    # High risk needs approval
    if step.risk_level == RiskLevel.HIGH:
        return True

    # Check command against explicit patterns
    command_lower = step.command.lower()

    # Force approval if command matches dangerous patterns
    for pattern in settings.require_approval_list:
        if pattern in command_lower:
            return True

    # Auto-approve if command matches safe patterns
    for pattern in settings.auto_approve_list:
        if pattern in command_lower:
            return False

    # Medium risk — auto-approve with logging
    if step.risk_level == RiskLevel.MEDIUM:
        return False

    # Low risk — auto-approve
    if step.risk_level == RiskLevel.LOW:
        return False

    # Default: require approval (fail-safe)
    return True


def classify_risk_override(step: TaskStep) -> RiskLevel:
    """Re-classify risk based on the actual command content.
    
    The LLM's risk classification is a suggestion — this function
    applies hard rules to override when needed.
    """
    command_lower = step.command.lower()

    # Force CRITICAL for destructive operations
    critical_patterns = [
        "rm -rf", "drop database", "drop table",
        "terraform destroy", "gcloud compute instances delete",
        "kubectl delete namespace", "docker system prune",
        "git push --force", "git push -f",
    ]
    for pattern in critical_patterns:
        if pattern in command_lower:
            return RiskLevel.CRITICAL

    # Force HIGH for remote writes
    high_patterns = [
        "git push", "gh pr merge", "gcloud run deploy",
        "gcloud app deploy", "docker push", "kubectl apply",
        "terraform apply", "npm publish",
    ]
    for pattern in high_patterns:
        if pattern in command_lower:
            return RiskLevel.HIGH

    # Force LOW for read-only
    low_patterns = [
        "git status", "git log", "git diff",
        "ls", "cat", "head", "tail", "grep",
        "gh issue list", "gh pr list", "gh repo view",
        "gcloud compute instances list",
        "kubectl get", "docker ps", "docker images",
    ]
    for pattern in low_patterns:
        if pattern in command_lower:
            return RiskLevel.LOW

    return step.risk_level  # Keep LLM's classification
