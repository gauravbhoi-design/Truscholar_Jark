"""Agent Orchestrator — Supervisor that routes queries to specialized agents."""

import time
import uuid
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.cloud_debugger import CloudDebuggerAgent
from app.agents.codebase_analyzer import CodebaseAnalyzerAgent
from app.agents.commit_analyst import CommitAnalystAgent
from app.agents.deployment_doctor import DeploymentDoctorAgent
from app.agents.engineering_metrics import EngineeringMetricsAgent
from app.agents.performance import PerformanceAgent
from app.agents.supervisor import SupervisorAgent
from app.config import get_settings
from app.models.database import CloudCredential
from app.models.schemas import (
    AgentName,
    AgentResponse,
    AgentStatus,
    PlanResponse,
    PlanStatus,
    PlanStepSchema,
    PlanStepStatus,
)
from app.services.memory import MemoryService

logger = structlog.get_logger()
settings = get_settings()


class AgentOrchestrator:
    """Routes user queries to the appropriate agent(s) via the Supervisor."""

    def __init__(self, db: AsyncSession | None, user: dict):
        self.db = db
        self.user = user
        self.agents = {
            AgentName.CLOUD_DEBUGGER: CloudDebuggerAgent(),
            AgentName.CODEBASE_ANALYZER: CodebaseAnalyzerAgent(),
            AgentName.COMMIT_ANALYST: CommitAnalystAgent(),
            AgentName.DEPLOYMENT_DOCTOR: DeploymentDoctorAgent(),
            AgentName.PERFORMANCE: PerformanceAgent(),
            AgentName.ENGINEERING_METRICS: EngineeringMetricsAgent(),
        }
        self.supervisor = SupervisorAgent(agents=self.agents)
        self.memory = MemoryService(db=db, user_id=user.get("sub", user.get("login", ""))) if db else None

    async def _enrich_user_with_credentials(self) -> dict:
        """Add GCP and GitHub tokens to user dict from DB if available."""
        enriched = dict(self.user)
        if not self.db:
            return enriched

        user_id = self.user.get("sub", self.user.get("login", ""))

        # Load GCP credentials
        try:
            from app.api.gcp_oauth import get_user_gcp_access_token
            gcp_result = await get_user_gcp_access_token(user_id, self.db)
            if gcp_result:
                access_token, project_id = gcp_result
                enriched["gcp_access_token"] = access_token
                enriched["gcp_project_id"] = project_id
                logger.info("GCP credentials loaded", user=user_id, project=project_id)
        except Exception as e:
            logger.debug("No GCP credentials", error=str(e))

        # Load GitHub token from DB if not in JWT (Google sign-in users)
        if not enriched.get("github_token"):
            try:
                from app.utils.encryption import decrypt
                result = await self.db.execute(
                    select(CloudCredential).where(
                        CloudCredential.user_id == user_id,
                        CloudCredential.provider == "github",
                        CloudCredential.is_active == True,
                    )
                )
                cred = result.scalar_one_or_none()
                if cred:
                    enriched["github_token"] = decrypt(cred.encrypted_refresh_token)
                    enriched["login"] = cred.project_id  # GitHub username stored in project_id
                    logger.info("GitHub credentials loaded from DB", user=user_id, login=cred.project_id)
            except Exception as e:
                logger.debug("No GitHub credentials in DB", error=str(e))

        return enriched

    async def process_query(
        self,
        query: str,
        conversation_id: uuid.UUID | None = None,
        context: dict | None = None,
    ) -> AgentResponse:
        """Process a query through the supervisor agent."""
        start = time.monotonic()
        conversation_id = conversation_id or uuid.uuid4()

        try:
            # Enrich user context with GCP credentials if available
            enriched_user = await self._enrich_user_with_credentials()

            # If frontend sent a specific GCP project, override the stored one
            if context and context.get("gcp_project_id"):
                enriched_user["gcp_project_id"] = context["gcp_project_id"]

            # Build memory context
            memory_context = ""
            if self.memory:
                try:
                    memory_context = await self.memory.build_memory_context(query)
                except Exception as e:
                    logger.debug("Memory context failed", error=str(e))

            # Enrich context with memory
            enriched_context = dict(context) if context else {}
            if memory_context:
                enriched_context["_memory"] = memory_context

            # Supervisor classifies intent and routes to agents
            routing = await self.supervisor.classify_and_route(query, context)

            results = []
            agents_used = []
            total_cost = 0.0
            all_tool_calls = []

            # Execute agents (parallel for independent agents)
            for agent_name in routing.agents:
                agent = self.agents.get(agent_name)
                if not agent:
                    continue

                logger.info("Invoking agent", agent=agent_name.value, query=query[:100])
                result = await agent.execute(query=query, context=enriched_context, user=enriched_user)
                results.append(result)
                agents_used.append(agent_name.value)
                total_cost += result.get("cost_usd", 0.0)
                all_tool_calls.extend(result.get("tool_calls", []))

            # Supervisor synthesizes final response
            final_response = await self.supervisor.synthesize(query, results)

            # Save to memory
            if self.memory and final_response:
                try:
                    await self.memory.store_analysis(
                        title=query[:200],
                        content=final_response[:3000],
                        category="analysis",
                        metadata={
                            "agents": agents_used,
                            "cost": total_cost,
                            "tool_calls": len(all_tool_calls),
                        },
                        importance=7 if any(kw in query.lower() for kw in ["error", "fix", "critical", "deploy"]) else 5,
                    )
                    await self.db.commit()  # type: ignore[union-attr]
                except Exception as e:
                    logger.debug("Failed to save memory", error=str(e))

            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "Query processed",
                agents=agents_used,
                elapsed_ms=elapsed_ms,
                cost=total_cost,
            )

            return AgentResponse(
                conversation_id=conversation_id,
                message=final_response,
                agents_used=agents_used,
                tool_calls=all_tool_calls,
                cost_usd=total_cost,
                status=AgentStatus.COMPLETED,
            )

        except Exception as e:
            logger.error("Orchestrator error", error=str(e))
            return AgentResponse(
                conversation_id=conversation_id,
                message=f"I encountered an error processing your request: {str(e)}",
                agents_used=[],
                cost_usd=0.0,
                status=AgentStatus.FAILED,
            )

    async def process_query_stream(
        self,
        query: str,
        conversation_id: uuid.UUID | None = None,
        context: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Stream agent responses in real-time via SSE."""
        conversation_id = conversation_id or uuid.uuid4()

        yield {"event": "thinking", "agent": "supervisor", "data": {"message": "Analyzing your query..."}}

        # Enrich user context with GCP credentials if available
        enriched_user = await self._enrich_user_with_credentials()

        # If frontend sent a specific GCP project, override the stored one
        if context and context.get("gcp_project_id"):
            enriched_user["gcp_project_id"] = context["gcp_project_id"]

        # Build memory context
        memory_context = ""
        if self.memory:
            try:
                memory_context = await self.memory.build_memory_context(query)
                if memory_context:
                    yield {"event": "info", "agent": "supervisor", "data": {"message": "Loaded context from previous analyses"}}
            except Exception:
                pass

        enriched_context = dict(context) if context else {}
        if memory_context:
            enriched_context["_memory"] = memory_context

        try:
            routing = await self.supervisor.classify_and_route(query, context)
        except Exception as e:
            logger.error("Routing failed", error=str(e))
            yield {"event": "error", "agent": "supervisor", "data": {"message": f"Routing failed: {e}"}}
            return

        yield {
            "event": "routing",
            "agent": "supervisor",
            "data": {
                "agents": [a.value for a in routing.agents],
                "reasoning": routing.reasoning,
            },
        }

        results = []
        agents_used = []
        total_cost = 0.0

        for agent_name in routing.agents:
            agent = self.agents.get(agent_name)
            if not agent:
                continue

            yield {"event": "agent_start", "agent": agent_name.value, "data": {"message": f"Starting {agent_name.value}..."}}
            agents_used.append(agent_name.value)

            async for event in agent.execute_with_events(query=query, context=enriched_context, user=enriched_user):
                # Collect the final result
                if event["type"] == "agent_result":
                    results.append(event["data"])
                    total_cost += event["data"].get("cost_usd", 0.0)
                else:
                    # Forward all other events to the client
                    yield {"event": event["type"], "agent": event["agent"], "data": event["data"]}

        # Synthesize final response
        yield {"event": "thinking", "agent": "supervisor", "data": {"message": "Synthesizing results..."}}

        try:
            final_response = await self.supervisor.synthesize(query, results)
        except Exception as e:
            logger.error("Synthesis failed", error=str(e))
            final_response = results[0].get("response", "Error synthesizing results.") if results else "No results."

        # Save to memory
        if self.memory and final_response:
            try:
                await self.memory.store_analysis(
                    title=query[:200],
                    content=final_response[:3000],
                    category="analysis",
                    metadata={"agents": agents_used, "cost": total_cost},
                    importance=7 if any(kw in query.lower() for kw in ["error", "fix", "critical", "deploy"]) else 5,
                )
                await self.db.commit()  # type: ignore[union-attr]
            except Exception:
                pass

        yield {
            "event": "final_response",
            "agent": "supervisor",
            "data": {
                "conversation_id": str(conversation_id),
                "message": final_response,
                "agents_used": agents_used,
                "cost_usd": total_cost,
                "status": "completed",
            },
        }

    # ─── Plan Mode ─────────────────────────────────────────────────────────

    async def generate_plan(
        self,
        query: str,
        context: dict | None = None,
    ) -> PlanResponse:
        """Generate an execution plan for user approval (Human-in-the-Loop)."""
        enriched_user = await self._enrich_user_with_credentials()
        if context and context.get("gcp_project_id"):
            enriched_user["gcp_project_id"] = context["gcp_project_id"]

        # Route to agents
        routing = await self.supervisor.classify_and_route(query, context)

        all_steps: list[dict] = []
        agents_used: list[str] = []
        total_cost = 0.0
        summaries = []

        for agent_name in routing.agents:
            agent = self.agents.get(agent_name)
            if not agent:
                continue

            logger.info("Generating plan", agent=agent_name.value, query=query[:100])
            plan_result = await agent.generate_plan(query=query, context=context, user=enriched_user)

            agents_used.append(agent_name.value)
            total_cost += plan_result.get("cost_usd", 0.0)
            summaries.append(plan_result.get("summary", ""))

            for step in plan_result.get("steps", []):
                step["order"] = len(all_steps) + 1
                all_steps.append(step)

        # Persist the plan in the DB
        if self.db:
            from app.models.database import Plan, PlanStep

            user_id = self.user.get("sub", self.user.get("login", ""))
            plan = Plan(
                user_id=user_id,
                query=query,
                summary=" | ".join(s for s in summaries if s),
                status="pending",
                agents_used=agents_used,
                context=context,
                total_cost_usd=total_cost,
            )
            self.db.add(plan)
            await self.db.flush()

            for step_data in all_steps:
                step = PlanStep(
                    plan_id=plan.id,
                    order=step_data["order"],
                    title=step_data["title"],
                    description=step_data["description"],
                    agent_name=step_data["agent_name"],
                    tool_name=step_data["tool_name"],
                    tool_input=step_data["tool_input"],
                    status="pending",
                )
                self.db.add(step)

            await self.db.commit()
            await self.db.refresh(plan)

            return PlanResponse(
                id=plan.id,
                query=query,
                summary=plan.summary,
                status=PlanStatus.PENDING,
                steps=[
                    PlanStepSchema(
                        id=s.id,
                        order=s.order,
                        title=s.title,
                        description=s.description,
                        agent_name=s.agent_name,
                        tool_name=s.tool_name,
                        tool_input=s.tool_input,
                        status=PlanStepStatus.PENDING,
                    )
                    for s in sorted(plan.steps, key=lambda x: x.order)
                ],
                agents_used=agents_used,
                total_cost_usd=total_cost,
                created_at=plan.created_at,
            )

        # Fallback if no DB (shouldn't happen in production)
        return PlanResponse(
            id=uuid.uuid4(),
            query=query,
            summary=" | ".join(summaries),
            status=PlanStatus.PENDING,
            steps=[PlanStepSchema(**s, status=PlanStepStatus.PENDING) for s in all_steps],
            agents_used=agents_used,
            total_cost_usd=total_cost,
        )

    async def execute_plan_step(
        self,
        plan_id: uuid.UUID,
        step_id: uuid.UUID | None = None,
    ) -> dict:
        """Execute a single approved step from a plan."""
        if not self.db:
            return {"error": "Database required for plan execution"}

        from datetime import datetime

        from app.models.database import Plan, PlanStep

        # Load the plan
        plan_result = await self.db.execute(select(Plan).where(Plan.id == plan_id))
        plan = plan_result.scalar_one_or_none()
        if not plan:
            return {"error": "Plan not found"}

        # Find the step to execute
        if step_id:
            step_result = await self.db.execute(
                select(PlanStep).where(PlanStep.id == step_id, PlanStep.plan_id == plan_id)
            )
            step = step_result.scalar_one_or_none()
        else:
            # Get next approved/pending step
            step_result = await self.db.execute(
                select(PlanStep)
                .where(PlanStep.plan_id == plan_id, PlanStep.status.in_(["approved", "pending"]))
                .order_by(PlanStep.order)
                .limit(1)
            )
            step = step_result.scalar_one_or_none()

        if not step:
            return {"error": "No pending steps to execute", "plan_completed": True}

        # Get the agent for this step
        try:
            agent_name = AgentName(step.agent_name)
        except ValueError:
            return {"error": f"Unknown agent: {step.agent_name}"}

        agent = self.agents.get(agent_name)
        if not agent:
            return {"error": f"Agent not available: {step.agent_name}"}

        # Enrich user with GCP credentials
        enriched_user = await self._enrich_user_with_credentials()
        if plan.context and plan.context.get("gcp_project_id"):
            enriched_user["gcp_project_id"] = plan.context["gcp_project_id"]

        # Mark step as executing
        step.status = "executing"
        await self.db.commit()

        # Execute the step
        logger.info("Executing plan step", plan=str(plan_id), step=str(step.id), tool=step.tool_name)
        result = await agent.execute_single_step(
            tool_name=step.tool_name,
            tool_input=step.tool_input,
            user=enriched_user,
        )

        # Update step status
        step.status = "completed" if result["success"] else "failed"
        step.result = result["result"] if isinstance(result["result"], dict) else {"output": str(result["result"])}
        step.executed_at = datetime.utcnow()
        await self.db.commit()

        # Check if all steps are done
        remaining = await self.db.execute(
            select(PlanStep)
            .where(PlanStep.plan_id == plan_id, PlanStep.status.in_(["pending", "approved"]))
        )
        remaining_steps = remaining.scalars().all()

        if not remaining_steps:
            plan.status = "completed"
            await self.db.commit()

        return {
            "step_id": str(step.id),
            "step_title": step.title,
            "tool_name": step.tool_name,
            "status": step.status,
            "result": step.result,
            "elapsed_ms": result.get("elapsed_ms", 0),
            "plan_completed": len(remaining_steps) == 0,
        }
