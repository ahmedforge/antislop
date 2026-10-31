from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.blocklist import router as blocklist_router
from app.config import Settings
from app.db import make_engine
from app.metrics import ApprovedChannelsCollector, Metrics, MetricsMiddleware
from app.metrics import router as metrics_router
from app.moderation import router as moderation_router
from app.submissions import router as submissions_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    metrics = Metrics()
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Engine creation is lazy: liveness still works without a database connection.
        app.state.engine = make_engine(settings)
        app.state.redis = Redis.from_url(
            str(settings.redis_url), decode_responses=True,
            socket_connect_timeout=1, socket_timeout=1, retry=Retry(NoBackoff(), 0),
        )
        collector = ApprovedChannelsCollector(app.state.engine)
        metrics.registry.register(collector)
        try:
            yield
        finally:
            metrics.registry.unregister(collector)
            app.state.redis.close()
            app.state.engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(MetricsMiddleware, metrics=metrics)
    app.include_router(metrics_router)
    app.include_router(blocklist_router)
    app.include_router(submissions_router)
    app.include_router(moderation_router)
    app.state.settings = settings
    app.state.metrics = metrics

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness only: database and Redis readiness are checked separately."""
        return {"status": "ok"}

    return app
