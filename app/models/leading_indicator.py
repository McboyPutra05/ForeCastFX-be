"""
app/models/leading_indicator.py
Configuration table linking leading indicators to their target events.
Weights and correlation directions are defined per the scoring formulas in
IndicatorAnalysisFullNews.md.
"""

import uuid

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LeadingIndicatorConfig(Base):
    """
    Stores the relationship between a leading indicator and the target
    high-impact event it helps predict.

    Example:
        target_event_code = 'NFP'
        indicator_code    = 'ADP'
        weight            = 0.35
        correlation_direction = +1  (positive)
    """

    __tablename__ = "leading_indicator_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    target_event_code: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    indicator_code: Mapped[str] = mapped_column(String(50), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    correlation_direction: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )  # +1 = positive, -1 = negative
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "target_event_code", "indicator_code", name="uq_target_indicator"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LeadingIndicatorConfig {self.indicator_code} → "
            f"{self.target_event_code} w={self.weight}>"
        )
