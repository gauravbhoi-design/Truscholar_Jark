from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ─── App ────────────────────────────────────────────────────────────
    app_name: str = "DevOps Co-Pilot"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    # ─── API ────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_allow_all: bool = False  # Set true in production to allow Cloud Run origins
    frontend_url: str = ""  # Production frontend URL; falls back to cors_origins[0]

    # ─── Auth (GitHub OAuth) ──────────────────────────────────────────
    github_client_id: str = ""
    github_client_secret: str = ""
    github_callback_url: str = "http://localhost:8000/api/v1/auth/github/callback"
    github_connect_callback_url: str = "http://localhost:8000/api/v1/auth/github/connect/callback"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # ─── Claude / Anthropic via Vertex AI ──────────────────────────────
    anthropic_api_key: str = ""  # Only needed for direct Anthropic API
    claude_model: str = "claude-opus-4-6"  # Vertex AI model ID for Opus 4.6
    claude_max_tokens: int = 8192
    max_budget_usd: float = 5.0  # Per-session cost cap
    use_vertex_ai: bool = True  # Use GCP Vertex AI instead of direct Anthropic API
    vertex_region: str = "us-east5"  # Vertex AI region with Claude support

    # ─── PostgreSQL ─────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "copilot"
    postgres_password: str = "copilot_dev"
    postgres_db: str = "devops_copilot"

    @property
    def postgres_url(self) -> str:
        # Cloud SQL uses Unix socket: POSTGRES_HOST=/cloudsql/project:region:instance
        if self.postgres_host.startswith("/cloudsql/"):
            return (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@/{self.postgres_db}?host={self.postgres_host}"
            )
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ─── Redis ──────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ─── MongoDB ────────────────────────────────────────────────────────
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "devops_copilot_logs"

    # ─── Qdrant (Vector DB) ─────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # ─── MCP Integrations ───────────────────────────────────────────────
    github_token: str = ""  # Fallback token; per-user tokens used when available
    slack_bot_token: str = ""
    jira_api_token: str = ""
    jira_base_url: str = ""
    sentry_auth_token: str = ""
    datadog_api_key: str = ""

    # ─── AWS ────────────────────────────────────────────────────────────
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # ─── GCP (System — for Vertex AI LLM calls) ─────────────────────────
    gcp_project_id: str = "project-pallavi-tarke"
    gcp_credentials_path: str = "/home/gaurav/TruJark/project-pallavi-tarke-db93ce8e37f9.json"
    google_application_credentials: str = ""

    # ─── GCP OAuth2 (User-facing — connect user's own GCP project) ────
    gcp_oauth_client_id: str = ""
    gcp_oauth_client_secret: str = ""
    gcp_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/gcp/callback"
    google_signin_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    gcp_oauth_scopes: str = (
        "openid email profile "
        "https://www.googleapis.com/auth/cloud-platform.read-only "
        "https://www.googleapis.com/auth/logging.read "
        "https://www.googleapis.com/auth/monitoring.read "
        "https://www.googleapis.com/auth/compute.readonly"
    )

    # ─── Zoho OAuth2 ────────────────────────────────────────────────
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_redirect_uri: str = "http://localhost:8000/api/v1/auth/zoho/callback"

    # ─── Credential Encryption ────────────────────────────────────────
    credentials_encryption_key: str = ""  # Base64-encoded 32-byte key for AES-256-GCM

    # ─── Cloud Run ───────────────────────────────────────────────────────
    cloud_run_url: str = ""  # Set automatically in Cloud Run (e.g., https://copilot-api-xxx.run.app)

    @property
    def effective_frontend_url(self) -> str:
        """Resolve frontend URL for OAuth redirects."""
        if self.frontend_url:
            return self.frontend_url.rstrip("/")
        return self.cors_origins[0] if self.cors_origins else "http://localhost:3000"

    @property
    def effective_github_callback_url(self) -> str:
        if self.cloud_run_url:
            return f"{self.cloud_run_url}/api/v1/auth/github/callback"
        return self.github_callback_url

    @property
    def effective_gcp_oauth_redirect_uri(self) -> str:
        if self.cloud_run_url:
            return f"{self.cloud_run_url}/api/v1/auth/gcp/callback"
        return self.gcp_oauth_redirect_uri

    @property
    def effective_google_signin_redirect_uri(self) -> str:
        if self.cloud_run_url:
            return f"{self.cloud_run_url}/api/v1/auth/google/callback"
        return self.google_signin_redirect_uri

    @property
    def effective_zoho_redirect_uri(self) -> str:
        if self.cloud_run_url:
            return f"{self.cloud_run_url}/api/v1/auth/zoho/callback"
        return self.zoho_redirect_uri

    # ─── Rate Limiting ──────────────────────────────────────────────────
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 500

    model_config = {
        "env_file": ["../.env", ".env"],  # Look in parent dir (project root) and current dir
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
