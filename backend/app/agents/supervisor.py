"""Supervisor Agent — Routes queries to specialized agents and synthesizes results."""

import structlog
from dataclasses import dataclass

import anthropic

from app.agents.base import BaseAgent
from app.config import get_settings
from app.models.schemas import AgentName

logger = structlog.get_logger()
settings = get_settings()


@dataclass
class RoutingDecision:
    agents: list[AgentName]
    reasoning: str
    parallel: bool = True


class SupervisorAgent(BaseAgent):
    """Entry point for all user queries. Classifies intent and routes to agents."""

    def __init__(self, agents: dict):
        super().__init__()
        self._agents = agents

    @property
    def name(self) -> str:
        return "supervisor"

    @property
    def system_prompt(self) -> str:
        return """You are the Supervisor Agent for a DevOps Co-Pilot platform.
Your job is to:
1. Classify the user's intent
2. Decide which specialized agent(s) to invoke
3. Synthesize results into a clear, actionable response

Available agents:
- cloud_debugger: Analyzes cloud platform logs (AWS/GCP/Azure), resource status, deployment failures
- codebase_analyzer: Static analysis, pattern detection, vulnerability scanning, code quality
- commit_analyst: Analyzes commit history, diffs, identifies breaking changes and regressions
- deployment_doctor: Validates Docker, K8s, Terraform, Helm configs; CI/CD pipeline analysis
- performance: Monitors metrics, identifies bottlenecks, resource optimization

Routing rules:
- Deployment failures → cloud_debugger + deployment_doctor (parallel)
- Code review requests → codebase_analyzer + commit_analyst (parallel)
- Performance issues → performance + cloud_debugger (parallel)
- CI/CD pipeline issues → codebase_analyzer + cloud_debugger (parallel) — analyze GitHub Actions + correlate with GCP logs
- CI/CD + GCP cross-analysis → codebase_analyzer + cloud_debugger (parallel) — check workflow GCP configs, verify credentials, correlate errors
- Infrastructure config questions → deployment_doctor
- Log analysis → cloud_debugger
- Code quality / security → codebase_analyzer
- GCP service audit / list services → cloud_debugger

Always respond with JSON:
{"agents": ["agent_name"], "reasoning": "why these agents", "parallel": true/false}"""

    async def classify_and_route(
        self, query: str, context: dict | None = None
    ) -> RoutingDecision:
        """Classify the query and decide which agents to invoke."""
        messages = self._build_messages(query, context)

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.system_prompt,
            messages=messages,
        )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        # Parse routing decision from LLM response
        try:
            import json
            # Extract JSON from response (may be wrapped in markdown)
            json_str = text
            if "```" in text:
                json_str = text.split("```")[1].strip()
                if json_str.startswith("json"):
                    json_str = json_str[4:].strip()

            decision = json.loads(json_str)
            agent_names = [AgentName(a) for a in decision.get("agents", [])]

            return RoutingDecision(
                agents=agent_names,
                reasoning=decision.get("reasoning", ""),
                parallel=decision.get("parallel", True),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse routing decision, using fallback", error=str(e))
            return self._fallback_routing(query)

    def _fallback_routing(self, query: str) -> RoutingDecision:
        """Keyword-based fallback routing when LLM parsing fails."""
        query_lower = query.lower()
        agents = []

        # CI/CD + GCP cross-analysis
        cicd_keywords = ["ci/cd", "cicd", "pipeline", "workflow", "github actions", "deploy"]
        gcp_keywords = ["gcp", "google cloud", "cloud run", "gke", "service account"]
        has_cicd = any(kw in query_lower for kw in cicd_keywords)
        has_gcp = any(kw in query_lower for kw in gcp_keywords)

        if has_cicd and has_gcp:
            agents.extend([AgentName.CODEBASE_ANALYZER, AgentName.CLOUD_DEBUGGER])
        else:
            if any(kw in query_lower for kw in ["deploy", "pod", "container", "k8s", "kubernetes", "docker", "terraform", "helm"]):
                agents.append(AgentName.DEPLOYMENT_DOCTOR)
            if any(kw in query_lower for kw in ["log", "error", "crash", "5xx", "oom", "aws", "gcp", "service", "api", "cloud"]):
                agents.append(AgentName.CLOUD_DEBUGGER)
            if any(kw in query_lower for kw in ["commit", "diff", "regression", "blame", "git"]):
                agents.append(AgentName.COMMIT_ANALYST)
            if any(kw in query_lower for kw in ["code", "review", "vulnerability", "security", "lint", "ci", "pipeline", "workflow", "action"]):
                agents.append(AgentName.CODEBASE_ANALYZER)
            if any(kw in query_lower for kw in ["slow", "latency", "cpu", "memory", "performance"]):
                agents.append(AgentName.PERFORMANCE)

        if not agents:
            agents = [AgentName.CLOUD_DEBUGGER]  # Default

        return RoutingDecision(agents=agents, reasoning="Fallback keyword routing", parallel=True)

    async def synthesize(self, query: str, results: list[dict]) -> str:
        """Synthesize results from multiple agents into a final response."""
        if not results:
            return "No agents were able to process your query."

        if len(results) == 1:
            return results[0].get("response", "No response generated.")

        # Multi-agent synthesis
        results_text = ""
        for r in results:
            results_text += f"\n### {r['agent']} Agent:\n{r['response']}\n"

        synthesis_prompt = f"""The user asked: "{query}"

Multiple agents provided these analyses:
{results_text}

Synthesize these into a single, clear, actionable response. Prioritize:
1. Root cause identification
2. Specific actionable steps to fix the issue
3. Prevention recommendations

Keep the response concise and well-structured with markdown formatting."""

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system="You synthesize DevOps analysis results into clear, actionable recommendations.",
            messages=[{"role": "user", "content": synthesis_prompt}],
        )

        return "".join(b.text for b in response.content if b.type == "text")
