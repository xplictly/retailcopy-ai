"""Main FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.database import init_db
from app.workers.batch_worker import recover_interrupted_jobs

logger = logging.getLogger(__name__)
_settings = get_settings()

logging.basicConfig(
    level=_settings.log_level.upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RetailCopy AI starting up...")
    await init_db()
    logger.info("Database initialized.")
    await recover_interrupted_jobs()
    logger.info("Batch job recovery complete.")

    # Demo mode warning
    provider = _settings.llm_provider
    if provider == "demo" or not _settings._has_active_key():
        logger.warning(
            "Running in DEMO MODE. Set LLM_PROVIDER and corresponding API key in .env for live generation."
        )

    yield
    logger.info("RetailCopy AI shutting down.")


app = FastAPI(
    title="RetailCopy AI API",
    description=(
        "GenAI-powered retail product content generation platform. "
        "Transforms product data into SEO-friendly descriptions with factual validation."
    ),
    version=_settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.frontend_origin, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register Routers ──────────────────────────────────────────────────────────
from app.api.v1.products import router as products_router
from app.api.v1.imports import router as imports_router
from app.api.v1.batch_jobs import router as batch_router
from app.api.v1.analytics import router as analytics_router

app.include_router(products_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(batch_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": _settings.app_version,
        "provider": _settings.llm_provider,
        "demo_mode": _settings.is_demo_mode,
    }
