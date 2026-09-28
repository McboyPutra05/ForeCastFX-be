"""
app/api/v1/endpoints/calendar.py
Economic Calendar endpoints.

Frontend consumer:
    frontend/src/lib/api/calendar.ts → fetchUpcomingEvents()
    Calls: GET /api/v1/calendar/upcoming?limit=100&include_past=true
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
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
# GET /api/v1/calendar/upcoming (Full Economic Calendar)
# ---------------------------------------------------------------------------
@router.get(
    "/upcoming",
    response_model=CalendarListResponse,
    summary="Get upcoming and recent economic event releases for the calendar",
)
async def get_upcoming_events(
    limit: int = Query(100, ge=1, le=500),
    impact: str | None = Query(None, description="Filter by impact: HIGH, MEDIUM, LOW"),
    include_past: bool = Query(True, description="Include past/released events with actual data in the calendar"),
    month: str | None = Query("this_month", description="Filter by month e.g. this_month, 2026-09, ALL"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return economic releases for the calendar.
    Includes Previous, Forecast, Actual (for released events), and prediction bias.
    """
    now = datetime.now(timezone.utc)

    # Build query
    query = (
        select(EconomicRelease)
        .join(EconomicEvent)
        .options(
            selectinload(EconomicRelease.event),
            selectinload(EconomicRelease.predictions),
        )
        .where(EconomicEvent.is_active.is_(True))
    )

    if not include_past:
        query = query.where(EconomicRelease.release_date > now)
    else:
        # If month is specified e.g. this_month or 2026-09
        if month == "this_month":
            query = query.where(
                func.extract("year", EconomicRelease.release_date) == 2026,
                func.extract("month", EconomicRelease.release_date) == 9,
            )
        elif month and month != "ALL" and "-" in month:
            parts = month.split("-")
            try:
                y = int(parts[0])
                m = int(parts[1])
                query = query.where(
                    func.extract("year", EconomicRelease.release_date) == y,
                    func.extract("month", EconomicRelease.release_date) == m,
                )
            except ValueError:
                pass

    if impact and impact != "ALL":
        query = query.where(EconomicEvent.impact == impact.upper())

    # Sort chronologically (earliest to latest in the calendar)
    query = query.order_by(EconomicRelease.release_date.asc()).limit(limit)

    result = await db.execute(query)
    releases = result.scalars().all()

    events_out: list[UpcomingReleaseOut] = []
    for rel in releases:
        event = rel.event

        # Find the latest prediction for this release
        latest_pred = None
        if rel.predictions:
            latest_pred = sorted(rel.predictions, key=lambda p: p.predicted_at, reverse=True)[0]

        bias = latest_pred.signal if latest_pred else None
        conf = latest_pred.confidence_score if latest_pred else None

        dev_val = rel.deviation
        if dev_val is None and rel.actual_value is not None and rel.forecast_value is not None:
            dev_val = round(rel.actual_value - rel.forecast_value, 2)

        events_out.append(
            UpcomingReleaseOut(
                id=rel.id,
                event=EconomicEventOut.model_validate(event),
                release_date=rel.release_date,
                period_label=rel.period_label,
                previous_value=rel.previous_value,
                forecast_value=rel.forecast_value,
                actual_value=rel.actual_value,
                deviation=dev_val,
                usd_outcome=rel.usd_outcome,
                is_released=rel.is_released,
                bias_recommendation=bias,
                confidence_score=conf,
                event_name=event.event_name,
                impact=event.impact,
                country_code=event.country_code,
            )
        )

    return CalendarListResponse(events=events_out, total=len(events_out))
