"""
app/api/v1/endpoints/predictions.py
Prediction endpoints for the Hero Prediction Frame and prediction logs.

Frontend consumers:
    frontend/src/lib/api/predictions.ts → fetchLatestPrediction()
    Calls: GET /api/v1/predictions/latest

    frontend/src/lib/api/predictions.ts → fetchPredictionById(id)
    Calls: GET /api/v1/predictions/{id}
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.prediction_log import PredictionLog
from app.schemas.prediction_schema import LatestPredictionOut, PredictionLogOut
from app.services.prediction_engine import generate_latest_prediction

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/predictions/latest
# ---------------------------------------------------------------------------
@router.get(
    "/latest",
    response_model=LatestPredictionOut,
    summary="Get the latest BUY/SELL prediction for the nearest High Impact event",
)
async def get_latest_prediction(
    event_code: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Powers the Hero Prediction Frame on the dashboard.
    Generates a fresh prediction for the nearest upcoming High Impact event,
    or for a specific requested event_code (e.g. 'NFP').
    """
    prediction = await generate_latest_prediction(db, event_code=event_code)

    if not prediction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No upcoming High Impact events found to generate a prediction.",
        )

    return prediction


# ---------------------------------------------------------------------------
# GET /api/v1/predictions/{id}
# ---------------------------------------------------------------------------
@router.get(
    "/{prediction_id}",
    response_model=PredictionLogOut,
    summary="Get a specific prediction log entry by ID",
)
async def get_prediction_by_id(
    prediction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a specific prediction log entry."""
    result = await db.execute(
        select(PredictionLog).where(PredictionLog.id == prediction_id)
    )
    prediction = result.scalar_one_or_none()

    if not prediction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prediction with id {prediction_id} not found.",
        )

    return prediction
