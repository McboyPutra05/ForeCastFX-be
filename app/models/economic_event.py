"""
app/models/economic_event.py
Economic Event (master) and Economic Release (data point) entities.

EconomicEvent  — Represents one of the 12 High Impact US news types (CPI, NFP, …).
EconomicRelease — A specific scheduled/historical data release for an event.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EconomicEvent(Base):
    """Master table for the 12 tracked High Impact US economic indicators."""

    __tablename__ = "economic_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact: Mapped[str] = mapped_column(String(10), nullable=False, default="HIGH")
    country_code: Mapped[str] = mapped_column(String(10), nullable=False, default="US")
    source_api: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default="trading_economics"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationship: one event → many releases
    releases: Mapped[list["EconomicRelease"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<EconomicEvent {self.event_code}: {self.event_name}>"


class EconomicRelease(Base):
    """
    A single scheduled or historical data release for an EconomicEvent.
    Stores Previous, Forecast, Actual values and computed deviation.
    """

    __tablename__ = "economic_releases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("economic_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation: Mapped[float | None] = mapped_column(Float, nullable=True)
    usd_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_released: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_api_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationship back to event
    event: Mapped["EconomicEvent"] = relationship(back_populates="releases")

    # Relationship: one release → many prediction logs
    predictions: Mapped[list["PredictionLog"]] = relationship(  # noqa: F821
        back_populates="release", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_releases_event_id", "event_id"),
        Index("idx_releases_date", release_date.desc()),
    )

    def __repr__(self) -> str:
        return f"<EconomicRelease event_id={self.event_id} date={self.release_date}>"
