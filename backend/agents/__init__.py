"""Agent registry — all available agents."""

from .code_reviewer import CodeReviewerAgent
from .test_runner import TestRunnerAgent
from .log_monitor import LogMonitorAgent
from .cloud_monitor import CloudMonitorAgent

# Agent registry — instantiate one of each
AGENTS = {
    "code_reviewer": CodeReviewerAgent(),
    "test_runner": TestRunnerAgent(),
    "log_monitor": LogMonitorAgent(),
    "cloud_monitor": CloudMonitorAgent(),
}

def get_agent(agent_type: str):
    return AGENTS.get(agent_type)

def list_agents():
    return [agent.info for agent in AGENTS.values()]
