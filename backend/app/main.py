from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.routes import router as api_router
from app.api.websocket import router as ws_router
from app.config import get_settings
from app.services.redis_service import RedisService

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting DevOps Co-Pilot", version=settings.app_version)

    # Auto-create database tables if they don't exist
    try:
        from sqlalchemy import text

        from app.models.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Lightweight in-place migrations for additive columns.
            # Safe to re-run; PG no-ops if column already exists.
            await conn.execute(text(
                "ALTER TABLE github_app_installations "
                "ADD COLUMN IF NOT EXISTS user_id VARCHAR(255)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_github_app_installations_user_id "
                "ON github_app_installations (user_id)"
            ))
            # User profile fields used by the admin panel
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS login VARCHAR(255)"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500)"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_users_auth0_sub ON users (auth0_sub)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_users_login ON users (login)"
            ))
        logger.info("Database tables verified")
    except Exception as e:
        logger.error("Failed to create database tables", error=str(e))

    app.state.redis = None
    try:
        redis = RedisService(settings.redis_url)
        await redis.connect()
        app.state.redis = redis
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis not available, running without cache", error=str(e))
    yield
    if app.state.redis:
        await app.state.redis.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
)

# ─── Middleware ──────────────────────────────────────────────────────────────

if settings.cors_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ─── Prometheus Metrics ─────────────────────────────────────────────────────

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# ─── Routes ─────────────────────────────────────────────────────────────────

app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(ws_router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "healthy", "version": settings.app_version}
