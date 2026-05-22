from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.monitoring.logger import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger("app.main")
    settings = get_settings()
    log.info("Starting Text-to-SQL service (env=%s)", settings.app_env)
    yield
    log.info("Shutting down Text-to-SQL service")


app = FastAPI(
    title="Enterprise Text-to-SQL Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
