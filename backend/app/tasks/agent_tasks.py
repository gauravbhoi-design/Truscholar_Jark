"""Celery tasks for async agent execution."""

import asyncio
import uuid

import structlog

from app.services.orchestrator import AgentOrchestrator
from app.tasks.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, name="app.tasks.agent_tasks.run_agent_query")
def run_agent_query(self, query: str, user: dict, conversation_id: str | None = None):
    """Run an agent query asynchronously via Celery."""
    logger.info("Celery task started", task_id=self.request.id, query=query[:100])

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        orchestrator = AgentOrchestrator(db=None, user=user)
        result = loop.run_until_complete(
            orchestrator.process_query(
                query=query,
                conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
            )
        )
        return result.model_dump(mode="json")
    except Exception as e:
        logger.error("Celery task failed", task_id=self.request.id, error=str(e))
        raise
    finally:
        loop.close()


@celery_app.task(bind=True, name="app.tasks.agent_tasks.run_background_analysis")
def run_background_analysis(self, repo: str, analysis_type: str, user: dict):
    """Run a background codebase or deployment analysis."""
    logger.info(
        "Background analysis started",
        task_id=self.request.id,
        repo=repo,
        type=analysis_type,
    )

    analysis_queries = {
        "security_scan": f"Perform a comprehensive security scan on the repository {repo}. "
                        f"Check for OWASP Top 10 vulnerabilities, exposed secrets, and dependency CVEs.",
        "code_quality": f"Analyze code quality for {repo}. Check for anti-patterns, "
                       f"code smells, test coverage gaps, and technical debt.",
        "deployment_health": f"Check the deployment health for {repo}. Validate Docker, K8s, "
                           f"and CI/CD configurations. Identify misconfigurations.",
        "performance_audit": f"Audit performance for services in {repo}. Check resource "
                           f"utilization, latency trends, and scaling configuration.",
    }

    query = analysis_queries.get(analysis_type, f"Analyze {repo} for {analysis_type}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        orchestrator = AgentOrchestrator(db=None, user=user)
        result = loop.run_until_complete(orchestrator.process_query(query=query))
        return result.model_dump(mode="json")
    except Exception as e:
        logger.error("Background analysis failed", error=str(e))
        raise
    finally:
        loop.close()
