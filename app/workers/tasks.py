"""
app/workers/tasks.py
Celery background tasks for data ingestion, prediction generation,
and accuracy verification.

These tasks use synchronous database sessions since Celery workers
run in a separate process outside the async FastAPI event loop.
"""

import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to run an async function from a synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Task: Ingest calendar data from Trading Economics API
# ---------------------------------------------------------------------------
@celery_app.task(name="app.workers.tasks.task_ingest_calendar", bind=True)
def task_ingest_calendar(self):
    """
    Fetch upcoming economic calendar events from Trading Economics
    and upsert into the database.
    Runs every 6 hours via Celery Beat.
    """
    logger.info("Starting calendar data ingestion from Trading Economics API...")

    async def _ingest():
        from app.core.database import async_session_factory
        from app.services.data_ingestion import ingest_calendar_data

        async with async_session_factory() as session:
            count = await ingest_calendar_data(session)
            return count

    try:
        count = _run_async(_ingest())
        logger.info(f"Calendar ingestion complete: {count} new releases ingested.")
        return {"status": "success", "ingested": count}
    except Exception as exc:
        logger.error(f"Calendar ingestion failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)


# ---------------------------------------------------------------------------
# Task: Generate/refresh predictions
# ---------------------------------------------------------------------------
@celery_app.task(name="app.workers.tasks.task_generate_predictions", bind=True)
def task_generate_predictions(self):
    """
    Generate or refresh the prediction for the nearest upcoming
    High Impact event.
    Runs every 30 minutes via Celery Beat.
    """
    logger.info("Starting prediction generation...")

    async def _predict():
        from app.core.database import async_session_factory
        from app.services.prediction_engine import generate_latest_prediction

        async with async_session_factory() as session:
            prediction = await generate_latest_prediction(session)
            return prediction

    try:
        result = _run_async(_predict())
        if result:
            logger.info(
                f"Prediction generated: {result.signal} for {result.event_name} "
                f"(confidence: {result.confidence_score}%)"
            )
            return {
                "status": "success",
                "signal": result.signal,
                "event": result.event_name,
                "confidence": result.confidence_score,
            }
        else:
            logger.info("No upcoming events to predict.")
            return {"status": "no_events"}
    except Exception as exc:
        logger.error(f"Prediction generation failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


# ---------------------------------------------------------------------------
# Task: Check prediction accuracy
# ---------------------------------------------------------------------------
@celery_app.task(name="app.workers.tasks.task_check_accuracy", bind=True)
def task_check_accuracy(self):
    """
    For all unchecked predictions where actual data is now available,
    determine whether the prediction was correct (HIT or MISS).
    Runs every hour via Celery Beat.
    """
    logger.info("Starting prediction accuracy check...")

    async def _check():
        from app.core.database import async_session_factory
        from app.services.prediction_engine import check_prediction_accuracy

        async with async_session_factory() as session:
            count = await check_prediction_accuracy(session)
            return count

    try:
        count = _run_async(_check())
        logger.info(f"Accuracy check complete: {count} predictions verified.")
        return {"status": "success", "checked": count}
    except Exception as exc:
        logger.error(f"Accuracy check failed: {exc}")
        raise self.retry(exc=exc, countdown=120, max_retries=3)


# ---------------------------------------------------------------------------
# Task: Ingest historical data (manual trigger, not scheduled)
# ---------------------------------------------------------------------------
@celery_app.task(name="app.workers.tasks.task_ingest_historical")
def task_ingest_historical(months: int = 12):
    """
    One-time task to seed historical data from Trading Economics.
    Triggered manually via API or admin command.
    """
    logger.info(f"Starting historical data ingestion ({months} months)...")

    async def _ingest():
        from app.core.database import async_session_factory
        from app.services.data_ingestion import ingest_historical_data

        async with async_session_factory() as session:
            count = await ingest_historical_data(session, months=months)
            return count

    count = _run_async(_ingest())
    logger.info(f"Historical ingestion complete: {count} records.")
    return {"status": "success", "ingested": count}
