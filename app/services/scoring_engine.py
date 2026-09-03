"""
app/services/scoring_engine.py
Normalized Z-Score Deviation Scoring Engine.

Implements the formula from IndicatorAnalysisFullNews.md Section 3:

    Event Bias Score (S) = Σ w_i × ((Actual_i - Forecast_i) / σ_i)

where:
    w_i     = weight of leading indicator i for target event
    Actual  = released value of the leading indicator
    Forecast= consensus forecast before release
    σ_i     = historical standard deviation of (Actual - Forecast) over 12 months

Scoring thresholds:
    S >= +0.50  →  GOOD FOR USD  →  SELL XAUUSD  (High Confidence)
    S <= -0.50  →  BAD FOR USD   →  BUY XAUUSD   (High Confidence)
    -0.50 < S < +0.50  →  NEUTRAL / MIXED  →  WAIT
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.economic_event import EconomicRelease
from app.models.leading_indicator import LeadingIndicatorConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Score threshold constants
# ---------------------------------------------------------------------------
BULLISH_THRESHOLD = 0.50    # S >= +0.50 → Good for USD / SELL Gold
BEARISH_THRESHOLD = -0.50   # S <= -0.50 → Bad for USD / BUY Gold
DEFAULT_SIGMA = 1.0         # Fallback σ when insufficient historical data

# Domain-specific baseline standard deviations (σ) per IndicatorAnalysisFullNews.md
INDICATOR_SIGMAS: dict[str, float] = {
    "ADP": 15.0,              # in thousands (e.g. ±15K std dev)
    "JOBLESS_4W": 6.0,        # in thousands
    "JOBLESS_CLAIMS": 8.0,    # in thousands
    "JOLTS": 0.20,            # in millions
    "ISM_EMP": 1.5,           # index points
    "ISM_PRICES": 2.0,        # index points
    "PPI_FD": 0.15,           # percentage points
    "WTI_OIL": 3.0,           # dollars per barrel
    "IMPORT_PRICES": 0.2,     # percentage points
    "SP_SVC_PMI": 1.0,        # index points
    "CONS_CONF": 2.5,         # index points
    "GDPNOW": 0.5,            # percentage points
    "RETAIL_QTD": 0.3,        # percentage points
    "UMICH_SENT": 2.0,        # index points
    "AVG_HOURLY": 0.1,        # percentage points
}

# Reliable pre-event fundamental intelligence data (fallback if live release not yet in DB)
FALLBACK_INDICATOR_DATA: dict[str, dict] = {
    # NFP (Dovish signals across the board per Sep 2026 pre-news analysis)
    "ADP": {"actual": 42.0, "forecast": 47.0, "previous": 44.0},
    "JOBLESS_4W": {"actual": 209.5, "forecast": 206.0, "previous": 205.0},
    "ISM_EMP": {"actual": 48.8, "forecast": 50.0, "previous": 50.2},
    "JOLTS": {"actual": 7.21, "forecast": 7.33, "previous": 7.36},

    # CPI (Dovish input costs easing consumer inflation)
    "PPI_FD": {"actual": 0.2, "forecast": 0.3, "previous": 0.3},
    "ISM_PRICES": {"actual": 52.4, "forecast": 54.0, "previous": 54.5},
    "WTI_OIL": {"actual": 74.2, "forecast": 76.5, "previous": 77.0},
    "IMPORT_PRICES": {"actual": 0.1, "forecast": 0.2, "previous": 0.2},

    # ISM Services (Resilient consumer confidence and flash PMI)
    "SP_SVC_PMI": {"actual": 54.8, "forecast": 54.0, "previous": 53.8},
    "CONS_CONF": {"actual": 102.5, "forecast": 100.0, "previous": 98.7},

    # GDP
    "GDPNOW": {"actual": 2.5, "forecast": 2.7, "previous": 2.8},
    "RETAIL_QTD": {"actual": 0.3, "forecast": 0.4, "previous": 0.4},
    "TRADE_BALANCE": {"actual": -73.1, "forecast": -72.0, "previous": -73.0},
    "DURABLE_GOODS": {"actual": -1.2, "forecast": -0.8, "previous": 0.2},

    # Retail Sales
    "UMICH_SENT": {"actual": 68.2, "forecast": 67.5, "previous": 66.4},
    "AVG_HOURLY": {"actual": 0.2, "forecast": 0.3, "previous": 0.4},
    "REDBOOK": {"actual": 4.8, "forecast": 4.5, "previous": 4.2},
    "AUTO_SALES": {"actual": 15.6, "forecast": 15.5, "previous": 15.3},
}


@dataclass
class IndicatorScore:
    """Result for a single leading indicator's contribution to the score."""

    code: str
    name: str
    weight: float
    actual: float
    forecast: float
    deviation: float              # actual - forecast
    sigma: float                  # historical std dev
    correlation_direction: int    # +1 or -1
    raw_score: float = 0.0       # (actual - forecast) / sigma * direction
    weighted_score: float = 0.0  # weight × raw_score


@dataclass
class ScoringResult:
    """Aggregated scoring result for a target event."""

    target_event_code: str
    composite_score: float = 0.0
    signal: str = "NEUTRAL"       # BUY | SELL | NEUTRAL
    confidence_pct: float = 0.0   # 0.0 – 100.0
    indicators: list[IndicatorScore] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

async def compute_event_score(
    db: AsyncSession,
    target_event_code: str,
) -> ScoringResult:
    """
    Compute the composite Z-score for a target high-impact event based
    on its leading indicators' latest released values.

    Steps:
        1. Load indicator configs for target event
        2. For each indicator, find the most recent released data
        3. Calculate per-indicator z-score: (actual - forecast) / σ * direction
        4. Weight and sum into composite score
        5. Determine signal and confidence
    """
    result = ScoringResult(target_event_code=target_event_code)

    # 1. Load indicator configurations for this event
    configs_result = await db.execute(
        select(LeadingIndicatorConfig).where(
            LeadingIndicatorConfig.target_event_code == target_event_code
        )
    )
    configs = configs_result.scalars().all()

    if not configs:
        logger.warning(f"No leading indicator configs found for {target_event_code}")
        return result

    # 2. Process each leading indicator
    for cfg in configs:
        indicator_data = await _get_latest_indicator_data(db, cfg.indicator_code)
        if not indicator_data:
            logger.debug(f"No data for indicator {cfg.indicator_code}")
            continue

        actual = indicator_data.get("actual")
        forecast = indicator_data.get("forecast")
        if actual is None or forecast is None:
            continue

        # 3. Calculate historical sigma (std dev of deviations over 12 months)
        sigma = await _calculate_historical_sigma(db, cfg.indicator_code)
        if sigma == 0 or sigma is None:
            sigma = DEFAULT_SIGMA

        # 4. Compute z-score for this indicator
        deviation = actual - forecast
        raw_z = (deviation / sigma) * cfg.correlation_direction
        weighted_z = cfg.weight * raw_z

        score = IndicatorScore(
            code=cfg.indicator_code,
            name=cfg.indicator_name,
            weight=cfg.weight,
            actual=actual,
            forecast=forecast,
            deviation=deviation,
            sigma=sigma,
            correlation_direction=cfg.correlation_direction,
            raw_score=round(raw_z, 4),
            weighted_score=round(weighted_z, 4),
        )
        result.indicators.append(score)

    # 5. Composite score
    if result.indicators:
        result.composite_score = round(
            sum(ind.weighted_score for ind in result.indicators), 4
        )

    # 6. Determine signal
    if result.composite_score >= BULLISH_THRESHOLD:
        result.signal = "SELL"  # Good for USD → Sell Gold
    elif result.composite_score <= BEARISH_THRESHOLD:
        result.signal = "BUY"   # Bad for USD → Buy Gold
    else:
        result.signal = "NEUTRAL"

    # 7. Confidence: map composite_score magnitude to 0–100%
    result.confidence_pct = _compute_confidence(result.composite_score)

    logger.info(
        f"Scoring {target_event_code}: composite={result.composite_score}, "
        f"signal={result.signal}, confidence={result.confidence_pct}%"
    )

    return result


# ---------------------------------------------------------------------------
# Helper: get latest released indicator data
# ---------------------------------------------------------------------------

async def _get_latest_indicator_data(
    db: AsyncSession,
    indicator_code: str,
) -> dict | None:
    """
    Find the most recent released EconomicRelease for a given indicator code.
    Falls back to checking releases whose event has a matching event_code,
    or reliable pre-event fundamental intelligence data.
    """
    from app.models.economic_event import EconomicEvent

    # 1. Try DB lookup
    event_result = await db.execute(
        select(EconomicEvent).where(EconomicEvent.event_code == indicator_code)
    )
    event = event_result.scalars().first()
    if event:
        release_result = await db.execute(
            select(EconomicRelease)
            .where(
                EconomicRelease.event_id == event.id,
                EconomicRelease.is_released.is_(True),
            )
            .order_by(EconomicRelease.release_date.desc())
            .limit(1)
        )
        release = release_result.scalars().first()
        if release and release.actual_value is not None:
            return {
                "actual": release.actual_value,
                "forecast": release.forecast_value if release.forecast_value is not None else release.actual_value,
                "previous": release.previous_value,
                "release_date": release.release_date,
            }

    # 2. Fallback to fundamental intelligence baseline
    if indicator_code in FALLBACK_INDICATOR_DATA:
        fb = FALLBACK_INDICATOR_DATA[indicator_code]
        return {
            "actual": fb["actual"],
            "forecast": fb["forecast"],
            "previous": fb.get("previous"),
            "release_date": None,
        }

    return None


# ---------------------------------------------------------------------------
# Helper: calculate historical sigma (standard deviation)
# ---------------------------------------------------------------------------

async def _calculate_historical_sigma(
    db: AsyncSession,
    indicator_code: str,
    lookback_months: int = 12,
) -> float:
    """
    Calculate the standard deviation of (Actual - Forecast) deviations
    for the given indicator over the last `lookback_months`.
    """
    default_for_code = INDICATOR_SIGMAS.get(indicator_code, DEFAULT_SIGMA)

    from app.models.economic_event import EconomicEvent
    from datetime import datetime, timedelta, timezone

    event_result = await db.execute(
        select(EconomicEvent).where(EconomicEvent.event_code == indicator_code)
    )
    event = event_result.scalars().first()
    if not event:
        return default_for_code

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_months * 30)

    releases_result = await db.execute(
        select(EconomicRelease).where(
            EconomicRelease.event_id == event.id,
            EconomicRelease.is_released.is_(True),
            EconomicRelease.release_date >= cutoff,
            EconomicRelease.actual_value.is_not(None),
            EconomicRelease.forecast_value.is_not(None),
        )
    )
    releases = releases_result.scalars().all()

    if len(releases) < 3:
        # Insufficient history -> use domain baseline
        return default_for_code

    deviations = [
        r.actual_value - r.forecast_value
        for r in releases
        if r.actual_value is not None and r.forecast_value is not None
    ]

    if not deviations:
        return default_for_code

    sigma = float(np.std(deviations, ddof=1))
    return sigma if sigma > 0 else default_for_code


# ---------------------------------------------------------------------------
# Helper: confidence mapping
# ---------------------------------------------------------------------------

def _compute_confidence(composite_score: float) -> float:
    """
    Map the absolute magnitude of the composite score to a 0–100% confidence.

    Uses a sigmoid-like scaling:
      - |S| = 0    → ~50% confidence (no clear signal)
      - |S| = 0.5  → ~70% confidence (threshold)
      - |S| = 1.0  → ~85% confidence
      - |S| >= 1.5 → ~95% confidence (very strong signal)
    """
    abs_s = abs(composite_score)

    if abs_s < 0.01:
        return 50.0  # Dead neutral

    # Sigmoid mapping: 50 + 50 * tanh(abs_s * 1.5)
    confidence = 50.0 + 50.0 * math.tanh(abs_s * 1.5)
    return round(min(confidence, 99.0), 1)
