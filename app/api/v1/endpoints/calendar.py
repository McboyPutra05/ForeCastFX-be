"""
app/api/v1/endpoints/calendar.py
Economic Calendar endpoints.

Frontend consumer:
    frontend/src/lib/api/calendar.ts → fetchUpcomingEvents()
    Calls: GET /api/v1/calendar/upcoming?limit=10
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.economic_event import EconomicEvent, EconomicRelease
from app.models.prediction_log import PredictionLog
from app.schemas.calendar_schema import (
    CalendarListResponse,
    EconomicEventOut,
    UpcomingReleaseOut,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/upcoming
# ---------------------------------------------------------------------------
@router.get(
    "/upcoming",
    response_model=CalendarListResponse,
    summary="Get upcoming economic event releases",
)
async def get_upcoming_events(
    limit: int = Query(10, ge=1, le=100),
    impact: str | None = Query(None, description="Filter by impact: HIGH, MEDIUM, LOW"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return upcoming economic releases sorted by date ascending.
    Includes Previous, Forecast, and any existing prediction bias.
    """
    now = datetime.now(timezone.utc)

    # Build query
    query = (
        select(EconomicRelease)
        .join(EconomicEvent)
        .options(selectinload(EconomicRelease.event))
        .where(
            EconomicRelease.release_date > now,
            EconomicEvent.is_active.is_(True),
        )
        .order_by(EconomicRelease.release_date.asc())
    )

    if impact:
        query = query.where(EconomicEvent.impact == impact.upper())

    query = query.limit(limit)

    result = await db.execute(query)
    releases = result.scalars().all()

    # For each release, check if there's a prediction
    events_out: list[UpcomingReleaseOut] = []
    for rel in releases:
        event = rel.event

        # Find the latest prediction for this release
        pred_result = await db.execute(
            select(PredictionLog)
            .where(PredictionLog.release_id == rel.id)
            .order_by(PredictionLog.predicted_at.desc())
            .limit(1)
        )
        prediction = pred_result.scalar_one_or_none()

        bias = prediction.signal if prediction else None
        conf = prediction.confidence_score if prediction else None

        events_out.append(
            UpcomingReleaseOut(
                id=rel.id,
                event=EconomicEventOut.model_validate(event),
                release_date=rel.release_date,
                period_label=rel.period_label,
                previous_value=rel.previous_value,
                forecast_value=rel.forecast_value,
                bias_recommendation=bias,
                confidence_score=conf,
                event_name=event.event_name,
                impact=event.impact,
                country_code=event.country_code,
            )
        )

    return CalendarListResponse(events=events_out, total=len(events_out))
