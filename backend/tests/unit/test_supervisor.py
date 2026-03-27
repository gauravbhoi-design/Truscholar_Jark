"""Tests for Supervisor Agent routing logic."""

import pytest
from app.agents.supervisor import SupervisorAgent, RoutingDecision
from app.models.schemas import AgentName


class TestFallbackRouting:
    """Test keyword-based fallback routing."""

    def setup_method(self):
        self.supervisor = SupervisorAgent.__new__(SupervisorAgent)
        self.supervisor._agents = {}

    def test_deployment_keywords_route_to_deployment_doctor(self):
        result = self.supervisor._fallback_routing("My k8s pod is crashing")
        assert AgentName.DEPLOYMENT_DOCTOR in result.agents

    def test_log_keywords_route_to_cloud_debugger(self):
        result = self.supervisor._fallback_routing("Check the error logs for 5xx spikes")
        assert AgentName.CLOUD_DEBUGGER in result.agents

    def test_commit_keywords_route_to_commit_analyst(self):
        result = self.supervisor._fallback_routing("What changed in the last git commit?")
        assert AgentName.COMMIT_ANALYST in result.agents

    def test_code_keywords_route_to_codebase_analyzer(self):
        result = self.supervisor._fallback_routing("Review this code for security vulnerabilities")
        assert AgentName.CODEBASE_ANALYZER in result.agents

    def test_performance_keywords_route_to_performance_agent(self):
        result = self.supervisor._fallback_routing("The API is slow with high latency")
        assert AgentName.PERFORMANCE in result.agents

    def test_multi_agent_routing(self):
        result = self.supervisor._fallback_routing("Deployment is failing with 5xx errors in the logs")
        assert AgentName.DEPLOYMENT_DOCTOR in result.agents
        assert AgentName.CLOUD_DEBUGGER in result.agents

    def test_unknown_query_defaults_to_cloud_debugger(self):
        result = self.supervisor._fallback_routing("Hello world")
        assert AgentName.CLOUD_DEBUGGER in result.agents

    def test_routing_returns_parallel_by_default(self):
        result = self.supervisor._fallback_routing("anything")
        assert result.parallel is True
