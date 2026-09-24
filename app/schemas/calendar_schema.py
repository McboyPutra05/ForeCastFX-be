"""
app/schemas/calendar_schema.py
Pydantic response schemas for the Economic Calendar endpoints.

Must match 1:1 with frontend TypeScript types in:
  frontend/src/types/calendar.ts
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class EconomicEventOut(BaseModel):
    """Mirrors frontend `EconomicEvent` type."""

    id: uuid.UUID
    event_name: str
    event_code: str
    description: str | None = None
    impact: str  # "HIGH" | "MEDIUM" | "LOW"
    country_code: str
    source_api: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class UpcomingReleaseOut(BaseModel):
    """
    Mirrors frontend `UpcomingRelease` type.
    An upcoming or recent release row for the Economic Calendar Table.
    """

    id: uuid.UUID
    event: EconomicEventOut
    release_date: datetime
    period_label: str | None = None
    previous_value: float | None = None
    forecast_value: float | None = None
    actual_value: float | None = None
    deviation: float | None = None
    usd_outcome: str | None = None
    is_released: bool = False
    bias_recommendation: str | None = None  # "BUY" | "SELL" | "NEUTRAL" | "WATCH"
    confidence_score: float | None = None

    # Extra flat fields used by the frontend's EconomicCalendarTable component
    event_name: str = ""
    impact: str = "HIGH"
    country_code: str = "US"

    model_config = {"from_attributes": True}


class CalendarListResponse(BaseModel):
    """Mirrors frontend `CalendarListResponse` type."""

    events: list[UpcomingReleaseOut]
    total: int
