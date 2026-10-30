from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import make_engine
from app.blocklist import router as blocklist_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Engine creation is lazy: liveness still works without a database connection.
        app.state.engine = make_engine(settings)
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(blocklist_router)
    app.state.settings = settings

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness only: database and Redis readiness are checked separately."""
        return {"status": "ok"}

    return app
