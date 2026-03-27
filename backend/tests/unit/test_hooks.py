"""Tests for safety hooks."""

import pytest
from app.hooks.safety import PreToolUseHook


class TestPreToolUseHook:
    @pytest.fixture
    def admin_hook(self):
        return PreToolUseHook(user={"sub": "admin|1", "role": "admin"})

    @pytest.fixture
    def engineer_hook(self):
        return PreToolUseHook(user={"sub": "eng|1", "role": "engineer"})

    @pytest.fixture
    def viewer_hook(self):
        return PreToolUseHook(user={"sub": "view|1", "role": "viewer"})

    @pytest.mark.asyncio
    async def test_non_destructive_tools_auto_approved(self, engineer_hook):
        result = await engineer_hook.evaluate("query_cloudwatch_logs", {}, "cloud_debugger")
        assert result["approved"] is True
        assert result["requires_human_approval"] is False

    @pytest.mark.asyncio
    async def test_destructive_tools_blocked_for_engineer(self, engineer_hook):
        result = await engineer_hook.evaluate("kubectl_delete", {"namespace": "prod"}, "deployment_doctor")
        assert result["approved"] is False
        assert result["requires_human_approval"] is True

    @pytest.mark.asyncio
    async def test_destructive_tools_auto_approved_for_admin(self, admin_hook):
        result = await admin_hook.evaluate("kubectl_apply", {"manifest": "..."}, "deployment_doctor")
        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_blocked_tools_rejected_for_everyone(self, admin_hook):
        result = await admin_hook.evaluate("drop_database", {}, "any_agent")
        assert result["approved"] is False
        assert result["requires_human_approval"] is False

    @pytest.mark.asyncio
    async def test_audit_id_always_returned(self, engineer_hook):
        result = await engineer_hook.evaluate("read_file", {}, "codebase_analyzer")
        assert "audit_id" in result
        assert len(result["audit_id"]) > 0
