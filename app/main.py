"""
app/main.py
FastAPI application entrypoint.

Sets up:
    - CORS middleware
    - API v1 router
    - Health check endpoint
    - Startup event for initial data ingestion
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.database import async_session_factory

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: startup & shutdown events
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run tasks on startup and cleanup on shutdown."""
    # 1. Verify database schema and seed baseline data if empty
    try:
        from app.services.seeder import ensure_database_ready

        async with async_session_factory() as session:
            await ensure_database_ready(session)
            logger.info("✅ Database schema verified and baseline data ready.")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")

    # 2. Attempt live background ingestion if API key is configured
    if settings.ALPHA_VANTAGE_API_KEY:
        try:
            import asyncio
            from app.services.data_ingestion import ingest_calendar_data

            async def _bg_ingest():
                try:
                    async with async_session_factory() as session:
                        count = await ingest_calendar_data(session)
                        logger.info(f"✅ Alpha Vantage live ingestion: {count} releases updated.")
                except Exception as ex:
                    logger.warning(f"⚠️ Alpha Vantage background ingestion notice: {ex}")

            asyncio.create_task(_bg_ingest())
        except Exception as e:
            logger.warning(f"⚠️ Live ingestion setup skipped: {e}")
    else:
        logger.info("ℹ️ ALPHA_VANTAGE_API_KEY not set — using local baseline data.")

    yield

    logger.info("👋 Info Trader Backend shutting down...")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Info Trader — US Macroeconomic Prediction API",
    description=(
        "AI-powered prediction engine for US High Impact economic news releases. "
        "Provides BUY/SELL signals for XAUUSD based on leading indicator analysis."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Include API routers
# ---------------------------------------------------------------------------
app.include_router(api_v1_router)


# ---------------------------------------------------------------------------
# Health check (not under /api/v1 — used by Docker, load balancers, etc.)
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "info-trader-backend"}


@app.get("/api/v1/health", tags=["Health"])
async def api_health_check():
    """API-level health check."""
    return {"status": "healthy", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Admin: manual data ingestion trigger
# ---------------------------------------------------------------------------
@app.post("/api/v1/admin/ingest-calendar", tags=["Admin"])
async def trigger_calendar_ingestion():
    """
    Manually trigger calendar data ingestion from Trading Economics.
    Useful for initial setup or debugging.
    """
    from app.services.data_ingestion import ingest_calendar_data

    async with async_session_factory() as session:
        count = await ingest_calendar_data(session)
        return {"status": "success", "ingested": count}


@app.post("/api/v1/admin/ingest-historical", tags=["Admin"])
async def trigger_historical_ingestion(months: int = 12):
    """
    Manually trigger historical data ingestion.
    Seeds the database with past releases for accuracy testing.
    """
    from app.services.data_ingestion import ingest_historical_data

    async with async_session_factory() as session:
        count = await ingest_historical_data(session, months=months)
        return {"status": "success", "ingested": count}


@app.post("/api/v1/admin/check-accuracy", tags=["Admin"])
async def trigger_accuracy_check():
    """
    Manually trigger prediction accuracy verification.
    Checks all unchecked predictions where actual data is now available.
    """
    from app.services.prediction_engine import check_prediction_accuracy

    async with async_session_factory() as session:
        count = await check_prediction_accuracy(session)
        return {"status": "success", "checked": count}
