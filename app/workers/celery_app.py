"""
app/workers/celery_app.py
Celery application configuration for background task processing.
Uses Redis as the message broker.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

# ---------------------------------------------------------------------------
# Celery App
# ---------------------------------------------------------------------------

celery_app = Celery(
    "info_trader",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

# ---------------------------------------------------------------------------
# Celery Configuration
# ---------------------------------------------------------------------------

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task behavior
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Result backend
    result_expires=3600,  # 1 hour
)

# ---------------------------------------------------------------------------
# Periodic beat schedule
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    # Fetch fresh calendar data from Trading Economics every 6 hours
    "ingest-calendar-data": {
        "task": "app.workers.tasks.task_ingest_calendar",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    # Regenerate predictions every 30 minutes
    "generate-predictions": {
        "task": "app.workers.tasks.task_generate_predictions",
        "schedule": crontab(minute="*/30"),
    },
    # Check prediction accuracy every hour
    "check-accuracy": {
        "task": "app.workers.tasks.task_check_accuracy",
        "schedule": crontab(minute=15, hour="*"),
    },
}
