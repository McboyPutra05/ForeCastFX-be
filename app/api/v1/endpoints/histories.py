"""
app/api/v1/endpoints/histories.py
Historical release data and prediction accuracy endpoints.

Frontend consumers:
    frontend/src/lib/api/history.ts → fetchHistoricalReleases(eventCode?)
    Calls: GET /api/v1/history/?event_code=CPI

    frontend/src/lib/api/history.ts → fetchAccuracySummary()
    Calls: GET /api/v1/history/accuracy-summary
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.economic_event import EconomicEvent, EconomicRelease
from app.models.prediction_log import PredictionLog
from app.schemas.prediction_schema import (
    AccuracyByEventOut,
    AccuracySummaryResponse,
    HistoricalReleaseOut,
    HistoryListResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/history/
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=HistoryListResponse,
    summary="Get historical releases with prediction results",
)
async def get_historical_releases(
    event_code: str | None = Query(None, description="Filter by event code (e.g. CPI, NFP)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Return historical (released) economic data points,
    with attached prediction results if available.
    """
    # Build base query for released events
    query = (
        select(EconomicRelease)
        .join(EconomicEvent)
        .options(
            selectinload(EconomicRelease.event),
            selectinload(EconomicRelease.predictions),
        )
        .where(EconomicRelease.is_released.is_(True))
        .order_by(EconomicRelease.release_date.desc())
    )

    if event_code:
        query = query.where(EconomicEvent.event_code == event_code.upper())

    # Count total
    count_query = (
        select(func.count())
        .select_from(EconomicRelease)
        .join(EconomicEvent)
        .where(EconomicRelease.is_released.is_(True))
    )
    if event_code:
        count_query = count_query.where(EconomicEvent.event_code == event_code.upper())

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    releases = result.scalars().all()

    # Build response
    items: list[HistoricalReleaseOut] = []
    for rel in releases:
        event = rel.event

        # Get the latest prediction for this release (if any)
        latest_pred = None
        if rel.predictions:
            latest_pred = sorted(
                rel.predictions, key=lambda p: p.predicted_at, reverse=True
            )[0]

        items.append(
            HistoricalReleaseOut(
                id=rel.id,
                event_name=event.event_name,
                event_code=event.event_code,
                release_date=rel.release_date,
                period_label=rel.period_label,
                previous_value=rel.previous_value,
                forecast_value=rel.forecast_value,
                actual_value=rel.actual_value,
                deviation=rel.deviation,
                usd_outcome=rel.usd_outcome,
                is_released=rel.is_released,
                predicted_signal=latest_pred.signal if latest_pred else None,
                confidence_score=latest_pred.confidence_score if latest_pred else None,
                is_correct=latest_pred.is_correct if latest_pred else None,
            )
        )

    return HistoryListResponse(
        releases=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/history/accuracy-summary
# ---------------------------------------------------------------------------
@router.get(
    "/accuracy-summary",
    response_model=AccuracySummaryResponse,
    summary="Get prediction accuracy summary by event type",
)
async def get_accuracy_summary(db: AsyncSession = Depends(get_db)):
    """
    Return accuracy statistics grouped by event code.
    Shows hit rate, total predictions, and average confidence.
    """
    # Query prediction logs joined with releases and events
    result = await db.execute(
        select(
            EconomicEvent.event_code,
            EconomicEvent.event_name,
            func.count(PredictionLog.id).label("total"),
            func.count(
                func.nullif(PredictionLog.is_correct, False)
            ).filter(PredictionLog.is_correct.is_(True)).label("correct"),
            func.avg(PredictionLog.confidence_score).label("avg_conf"),
        )
        .select_from(PredictionLog)
        .join(EconomicRelease, PredictionLog.release_id == EconomicRelease.id)
        .join(EconomicEvent, EconomicRelease.event_id == EconomicEvent.id)
        .where(PredictionLog.is_correct.is_not(None))
        .group_by(EconomicEvent.event_code, EconomicEvent.event_name)
    )
    rows = result.all()

    accuracy_by_event: list[AccuracyByEventOut] = []
    total_all = 0
    correct_all = 0

    for row in rows:
        total_count = row.total or 0
        correct_count = row.correct or 0
        acc_pct = (correct_count / total_count * 100) if total_count > 0 else 0.0
        avg_conf = float(row.avg_conf or 0)

        total_all += total_count
        correct_all += correct_count

        accuracy_by_event.append(
            AccuracyByEventOut(
                event_code=row.event_code,
                event_name=row.event_name,
                total_predictions=total_count,
                correct_predictions=correct_count,
                accuracy_pct=round(acc_pct, 1),
                avg_confidence_score=round(avg_conf, 1),
            )
        )

    overall = round((correct_all / total_all * 100), 1) if total_all > 0 else None

    return AccuracySummaryResponse(
        accuracy_by_event=accuracy_by_event,
        overall_accuracy_pct=overall,
    )
