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
