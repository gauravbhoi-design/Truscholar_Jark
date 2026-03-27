"""Celery app configuration for async agent task processing."""

from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "devops_copilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minute max per task
    task_soft_time_limit=240,  # Soft limit at 4 minutes
    worker_prefetch_multiplier=1,  # One task at a time per worker
    worker_max_tasks_per_child=50,  # Restart workers after 50 tasks (memory safety)
    task_routes={
        "app.tasks.agent_tasks.run_agent_query": {"queue": "agents"},
        "app.tasks.agent_tasks.run_background_analysis": {"queue": "background"},
        "app.tasks.embedding_tasks.*": {"queue": "embeddings"},
    },
)
