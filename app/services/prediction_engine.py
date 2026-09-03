"""
app/services/prediction_engine.py
Main prediction pipeline: determines the BUY / SELL / NEUTRAL signal
for the nearest upcoming High Impact event.

Orchestrates:
    1. Find the nearest upcoming high-impact release
    2. Run the scoring engine on its leading indicators
    3. Build the full LatestPrediction response (matching frontend types)
    4. Persist the prediction log
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.economic_event import EconomicEvent, EconomicRelease
from app.models.leading_indicator import LeadingIndicatorConfig
from app.models.prediction_log import PredictionLog
from app.schemas.prediction_schema import (
    EngineMetadataOut,
    IndicatorBreakdownOut,
    LatestPredictionOut,
    LeadingIndicatorOut,
)
from app.services.scoring_engine import ScoringResult, compute_event_score

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal label / subtitle templates
# ---------------------------------------------------------------------------
SIGNAL_LABELS: dict[str, str] = {
    "BUY":     "BUY XAUUSD",
    "SELL":    "SELL XAUUSD",
    "NEUTRAL": "NEUTRAL",
}

SENTIMENT_LABELS: dict[str, str] = {
    "BUY":     "BAD FOR USD",
    "SELL":    "GOOD FOR USD",
    "NEUTRAL": "MIXED SIGNALS",
}

TONE_LABELS: dict[str, str] = {
    "BUY":     "Dovish",
    "SELL":    "Hawkish",
    "NEUTRAL": "Neutral",
}

# Colors for leading indicator cards on the dashboard
SIGNAL_BADGE_COLORS: dict[str, dict[str, str]] = {
    "BULLISH":  {"color": "#10B981", "bg": "#10B981"},
    "BEARISH":  {"color": "#EF4444", "bg": "#EF4444"},
    "NEUTRAL":  {"color": "#F59E0B", "bg": "#F59E0B"},
}


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def generate_latest_prediction(
    db: AsyncSession,
    event_code: str | None = None,
) -> LatestPredictionOut | None:
    """
    Generate (or refresh) the prediction for the nearest upcoming
    High Impact event, or for a specific requested event_code (e.g. 'NFP').

    Returns a fully-populated LatestPredictionOut or None if no
    upcoming event is found.
    """
    now = datetime.now(timezone.utc)

    # 1. Build query for the upcoming unreleased release
    query = (
        select(EconomicRelease)
        .options(selectinload(EconomicRelease.event))
        .join(EconomicEvent)
        .where(
            EconomicRelease.is_released.is_(False),
            EconomicRelease.release_date > now,
            EconomicEvent.is_active.is_(True),
        )
    )

    if event_code:
        query = query.where(EconomicEvent.event_code == event_code.upper())
    else:
        query = query.where(EconomicEvent.impact == "HIGH")

    query = query.order_by(EconomicRelease.release_date.asc()).limit(1)
    release_result = await db.execute(query)
    next_release = release_result.scalar_one_or_none()

    # Fallback if release_date <= now (e.g., event time is right now or past)
    if not next_release:
        fallback_query = (
            select(EconomicRelease)
            .options(selectinload(EconomicRelease.event))
            .join(EconomicEvent)
            .where(
                EconomicRelease.is_released.is_(False),
                EconomicEvent.is_active.is_(True),
            )
        )
        if event_code:
            fallback_query = fallback_query.where(EconomicEvent.event_code == event_code.upper())
        else:
            fallback_query = fallback_query.where(EconomicEvent.impact == "HIGH")

        fallback_query = fallback_query.order_by(EconomicRelease.release_date.desc()).limit(1)
        fallback_res = await db.execute(fallback_query)
        next_release = fallback_res.scalar_one_or_none()

    if not next_release:
        logger.info("No upcoming high-impact releases found.")
        return None

    # Event is already loaded
    event = next_release.event

    # 2. Run the scoring engine
    scoring: ScoringResult = await compute_event_score(db, event.event_code)

    # 3. Build indicator breakdown for engine_metadata
    indicator_breakdowns = [
        IndicatorBreakdownOut(
            code=ind.code,
            weight=ind.weight,
            actual=ind.actual,
            forecast=ind.forecast,
            deviation=ind.deviation,
            raw_score=ind.raw_score,
            weighted_score=ind.weighted_score,
        )
        for ind in scoring.indicators
    ]

    engine_metadata = EngineMetadataOut(indicators=indicator_breakdowns)

    # 4. Build leading_indicators for dashboard cards
    leading_indicators = await _build_leading_indicator_cards(
        db, event.event_code, scoring
    )

    # 5. Calculate countdown
    countdown_seconds = max(
        int((next_release.release_date - now).total_seconds()), 0
    )

    # 6. Build signal labels
    signal = scoring.signal
    signal_label = SIGNAL_LABELS.get(signal, "NEUTRAL")
    tone = TONE_LABELS.get(signal, "Neutral")
    sentiment = SENTIMENT_LABELS.get(signal, "MIXED SIGNALS")
    signal_subtitle = f"Predicted Bias: {sentiment} ({tone} {event.event_name})"

    # 7. Persist prediction log
    prediction_log = PredictionLog(
        release_id=next_release.id,
        signal=signal,
        signal_label=signal_label,
        signal_subtitle=signal_subtitle,
        confidence_score=scoring.confidence_pct,
        composite_score=scoring.composite_score,
        engine_metadata={
            "indicators": [
                {
                    "code": ind.code,
                    "weight": ind.weight,
                    "actual": ind.actual,
                    "forecast": ind.forecast,
                    "deviation": ind.deviation,
                    "raw_score": ind.raw_score,
                    "weighted_score": ind.weighted_score,
                }
                for ind in scoring.indicators
            ]
        },
    )
    db.add(prediction_log)
    await db.commit()

    # 8. Return the full response
    return LatestPredictionOut(
        signal=signal,
        signal_label=signal_label,
        signal_subtitle=signal_subtitle,
        confidence_score=scoring.confidence_pct,
        composite_score=scoring.composite_score,
        event_name=event.event_name,
        event_code=event.event_code,
        release_date=next_release.release_date,
        countdown_seconds=countdown_seconds,
        engine_metadata=engine_metadata,
        leading_indicators=leading_indicators,
    )


# ---------------------------------------------------------------------------
# Helper: build leading indicator cards for the dashboard
# ---------------------------------------------------------------------------

async def _build_leading_indicator_cards(
    db: AsyncSession,
    target_event_code: str,
    scoring: ScoringResult,
) -> list[LeadingIndicatorOut]:
    """
    Build the formatted LeadingIndicator list for the dashboard cards.
    Each card shows: name, signal badge, value, change %, description.
    """
    # Load configs
    configs_result = await db.execute(
        select(LeadingIndicatorConfig).where(
            LeadingIndicatorConfig.target_event_code == target_event_code
        )
    )
    configs = configs_result.scalars().all()
    config_map = {c.indicator_code: c for c in configs}

    cards: list[LeadingIndicatorOut] = []

    for ind_score in scoring.indicators:
        cfg = config_map.get(ind_score.code)
        if not cfg:
            continue

        # Determine badge
        if ind_score.weighted_score > 0.05:
            badge_signal = "BULLISH"
        elif ind_score.weighted_score < -0.05:
            badge_signal = "BEARISH"
        else:
            badge_signal = "NEUTRAL"

        badge = SIGNAL_BADGE_COLORS.get(badge_signal, SIGNAL_BADGE_COLORS["NEUTRAL"])

        # Deviation & Change formatting
        change_val = ind_score.deviation if ind_score.deviation is not None else 0.0

        # Change text color
        if ind_score.weighted_score > 0:
            change_color = "#10B981"
        elif ind_score.weighted_score < 0:
            change_color = "#EF4444"
        else:
            change_color = "#F59E0B"

        # Unit formatting based on indicator type
        unit = ""
        if "ADP" in ind_score.code or "JOBLESS" in ind_score.code:
            unit = "K"
        elif "JOLTS" in ind_score.code:
            unit = "M"
        elif "%" in cfg.indicator_name or "RATE" in ind_score.code or "CPI" in ind_score.code:
            unit = "%"

        if ind_score.actual is not None:
            if unit == "K":
                val_str = f"{ind_score.actual:.0f}K"
            elif unit == "M":
                val_str = f"{ind_score.actual:.2f}M"
            else:
                val_str = f"{ind_score.actual:.2f}{unit}"
        else:
            val_str = "—"

        chg_sign = "+" if change_val >= 0 else ""
        if unit == "K":
            change_text = f"{chg_sign}{change_val:.0f}K"
        elif unit == "M":
            change_text = f"{chg_sign}{change_val:.2f}M"
        else:
            change_text = f"{chg_sign}{change_val:.2f}{unit}"

        cards.append(
            LeadingIndicatorOut(
                name=cfg.indicator_name,
                signal=badge_signal,
                value=val_str,
                change=change_text,
                color=change_color,
                bg=badge["bg"],
                desc=cfg.description or "",
            )
        )

    return cards


# ---------------------------------------------------------------------------
# Accuracy checker
# ---------------------------------------------------------------------------

async def check_prediction_accuracy(db: AsyncSession) -> int:
    """
    For all prediction logs that haven't been accuracy-checked yet,
    check if the actual value has been released and determine
    whether the prediction was correct.

    Logic:
        - If actual > forecast → GOOD_FOR_USD → correct if signal was SELL
        - If actual < forecast → BAD_FOR_USD  → correct if signal was BUY
        - If actual == forecast → NEUTRAL

    Returns the number of predictions checked.
    """
    now = datetime.now(timezone.utc)

    unchecked_result = await db.execute(
        select(PredictionLog)
        .options(selectinload(PredictionLog.release))
        .join(EconomicRelease)
        .where(
            PredictionLog.is_correct.is_(None),
            EconomicRelease.is_released.is_(True),
            EconomicRelease.actual_value.is_not(None),
        )
    )
    unchecked = unchecked_result.scalars().all()

    count = 0
    for pred in unchecked:
        release = pred.release
        if not release or release.actual_value is None or release.forecast_value is None:
            continue

        deviation = release.actual_value - release.forecast_value

        if deviation > 0:
            # Actual beat forecast → Good for USD → SELL was correct
            actual_outcome = "SELL"
        elif deviation < 0:
            # Actual missed forecast → Bad for USD → BUY was correct
            actual_outcome = "BUY"
        else:
            actual_outcome = "NEUTRAL"

        pred.is_correct = pred.signal == actual_outcome
        pred.accuracy_checked_at = now

        # Also update the release's usd_outcome
        if deviation > 0:
            release.usd_outcome = "GOOD_FOR_USD"
        elif deviation < 0:
            release.usd_outcome = "BAD_FOR_USD"
        else:
            release.usd_outcome = "NEUTRAL"
        release.deviation = deviation

        count += 1

    await db.commit()
    logger.info(f"Accuracy checked for {count} predictions.")
    return count
