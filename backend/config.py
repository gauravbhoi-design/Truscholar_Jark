"""
AI DevOps Platform — Configuration
"""

from pydantic_settings import BaseSettings
from typing import List
from pathlib import Path
import os

BASE_DIR = Path(os.environ.get("BASE_DIR", Path(__file__).resolve().parent.parent))


class Settings(BaseSettings):
    # Claude via Vertex AI
    gcp_project_id: str = ""
    gcp_region: str = "us-east5"
    gcp_service_account_key: str = ""
    gcp_key_filename: str = "gcp-key.json"
    gcp_key_path_override: str = ""

    # GitHub
    github_token: str = ""

    # Direct Anthropic API (fallback)
    anthropic_api_key: str = ""

    # Server
    orchestrator_host: str = "0.0.0.0"
    orchestrator_port: int = 8000
    log_level: str = "INFO"

    # Redis
    redis_url: str = "redis://redis:6379"

    # Docker
    docker_host: str = "unix:///var/run/docker.sock"
    worker_image: str = "ai-devops-worker:latest"
    worker_timeout: int = 300

    # Agent
    agent_max_iterations: int = 30
    agent_model: str = "claude-opus-4-6@default"

    # Approval
    auto_approve_patterns: str = "test,lint,check,status,log,diff,list,read,cat,ls,pwd"
    require_approval_patterns: str = "push,deploy,delete,destroy,apply,merge,release,publish"

    # Database
    db_path: str = "data/devops_platform.db"

    @property
    def gcp_key_path(self) -> Path:
        if self.gcp_key_path_override:
            return Path(self.gcp_key_path_override)
        env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if env_path:
            return Path(env_path)
        return BASE_DIR / self.gcp_key_filename

    @property
    def auto_approve_list(self) -> List[str]:
        return [p.strip() for p in self.auto_approve_patterns.split(",")]

    @property
    def require_approval_list(self) -> List[str]:
        return [p.strip() for p in self.require_approval_patterns.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
