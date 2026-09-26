"""
app/schemas/prediction_schema.py
Pydantic response schemas for the Prediction endpoints.

Must match 1:1 with frontend TypeScript types in:
  frontend/src/types/prediction.ts
  frontend/src/types/history.ts
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Prediction sub-components
# ---------------------------------------------------------------------------

class IndicatorBreakdownOut(BaseModel):
    """Mirrors frontend `IndicatorBreakdown` type."""

    code: str
    weight: float
    actual: float
    forecast: float
    deviation: float
    raw_score: float
    weighted_score: float


class EngineMetadataOut(BaseModel):
    """Mirrors frontend `EngineMetadata` type."""

    indicators: list[IndicatorBreakdownOut]


class LeadingIndicatorOut(BaseModel):
    """
    Mirrors frontend `LeadingIndicator` type.
    Formatted for direct use by the dashboard UI cards.
    """

    name: str
    signal: str    # e.g. "BULLISH", "BEARISH", "NEUTRAL"
    value: str     # e.g. "3.2%"
    change: str    # e.g. "+0.3%"
    color: str     # hex color for the change text
    bg: str        # hex background for the signal badge
    desc: str      # short description


# ---------------------------------------------------------------------------
# Main prediction response
# ---------------------------------------------------------------------------

class LatestPredictionOut(BaseModel):
    """
    Mirrors frontend `LatestPrediction` type.
    Returned by GET /api/v1/predictions/latest for the Hero Prediction Frame.
    """

    signal: str              # "BUY" | "SELL" | "NEUTRAL"
    signal_label: str        # "BUY XAUUSD" | "SELL XAUUSD" | "NEUTRAL"
    signal_subtitle: str     # "Predicted Bias: BAD FOR USD (Dovish CPI)"
    confidence_score: float  # 0.0 – 100.0
    composite_score: float   # weighted z-score sum, roughly -1.0 to +1.0
    event_name: str
    event_code: str
    release_date: datetime
    previous_value: float | None = None
    forecast_value: float | None = None
    period_label: str | None = None
    countdown_seconds: int
    engine_metadata: EngineMetadataOut
    leading_indicators: list[LeadingIndicatorOut] | None = None


# ---------------------------------------------------------------------------
# Prediction log entry (for history views)
# ---------------------------------------------------------------------------

class PredictionLogOut(BaseModel):
    """Mirrors frontend `PredictionLogEntry` type."""

    id: uuid.UUID
    release_id: uuid.UUID
    signal: str
    signal_label: str
    confidence_score: float
    is_correct: bool | None = None
    predicted_at: datetime
    accuracy_checked_at: datetime | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# History-specific schemas
# ---------------------------------------------------------------------------

class HistoricalReleaseOut(BaseModel):
    """A past release with prediction data attached for the history table."""

    id: uuid.UUID
    event_name: str
    event_code: str
    release_date: datetime
    period_label: str | None = None
    previous_value: float | None = None
    forecast_value: float | None = None
    actual_value: float | None = None
    deviation: float | None = None
    usd_outcome: str | None = None
    is_released: bool
    predicted_signal: str | None = None
    confidence_score: float | None = None
    is_correct: bool | None = None

    model_config = {"from_attributes": True}


class HistoryListResponse(BaseModel):
    """Mirrors frontend `HistoryListResponse` type."""

    releases: list[HistoricalReleaseOut]
    total: int
    page: int = 1
    page_size: int = 50


class AccuracyByEventOut(BaseModel):
    """Mirrors frontend `AccuracySummaryByEvent` type."""

    event_code: str
    event_name: str
    total_predictions: int
    correct_predictions: int
    accuracy_pct: float
    avg_confidence_score: float


class AccuracySummaryResponse(BaseModel):
    """Mirrors frontend `AccuracySummaryResponse` type."""

    accuracy_by_event: list[AccuracyByEventOut]
    overall_accuracy_pct: float | None = None
