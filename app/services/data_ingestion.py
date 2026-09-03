"""
app/services/data_ingestion.py
Alpha Vantage API client for fetching US macroeconomic indicator data.

Replaces the previous Trading Economics approach.
Alpha Vantage provides historical time-series for economic indicators.
Docs: https://www.alphavantage.co/documentation/

Available economic indicator functions:
    REAL_GDP, CPI, INFLATION, RETAIL_SALES, DURABLES, UNEMPLOYMENT,
    NONFARM_PAYROLL, TREASURY_YIELD, FEDERAL_FUNDS_RATE

Note: Alpha Vantage does NOT provide:
    - Future release schedules (we generate these from known patterns)
    - Consensus forecast values (we estimate from trend/previous values)
    - Impact ratings (we define these in our seed data)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.economic_event import EconomicEvent, EconomicRelease

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alpha Vantage API Base URL
# ---------------------------------------------------------------------------
AV_BASE_URL = "https://www.alphavantage.co/query"

# ---------------------------------------------------------------------------
# Mapping: Our event codes → Alpha Vantage function names + parameters
# ---------------------------------------------------------------------------
EVENT_TO_AV_FUNCTION: dict[str, dict[str, str]] = {
    "CPI":            {"function": "CPI",              "interval": "monthly"},
    "NFP":            {"function": "NONFARM_PAYROLL",   "interval": "monthly"},
    "GDP":            {"function": "REAL_GDP",          "interval": "quarterly"},
    "RETAIL_SALES":   {"function": "RETAIL_SALES",      "interval": "monthly"},
    "UNEMPLOYMENT":   {"function": "UNEMPLOYMENT",      "interval": "monthly"},
    "PPI":            {"function": "CPI",              "interval": "monthly"},  # AV lacks PPI; use CPI as proxy
    "FOMC":           {"function": "FEDERAL_FUNDS_RATE", "interval": "monthly"},
    "PCE":            {"function": "INFLATION",         "interval": "monthly"},
    "JOBLESS_CLAIMS": {"function": "UNEMPLOYMENT",      "interval": "monthly"},  # proxy
    "ISM_MFG":        {"function": "DURABLES",          "interval": "monthly"},  # proxy
    "ISM_SVC":        {"function": "RETAIL_SALES",      "interval": "monthly"},  # proxy
    "FED_SPEECH":     {"function": "FEDERAL_FUNDS_RATE", "interval": "monthly"},
}

# Leading indicators that can also be fetched from Alpha Vantage
LEADING_INDICATOR_AV: dict[str, dict[str, str]] = {
    "ADP":            {"function": "NONFARM_PAYROLL",   "interval": "monthly"},
    "DURABLE_GOODS":  {"function": "DURABLES",          "interval": "monthly"},
    "UMICH_SENT":     {"function": "RETAIL_SALES",      "interval": "monthly"},  # proxy
    "WAGE_GROWTH":    {"function": "CPI",              "interval": "monthly"},  # proxy
}

# ---------------------------------------------------------------------------
# Known release schedule patterns (day-of-month approximations)
# Used to generate upcoming release dates since Alpha Vantage doesn't
# provide a calendar of future releases.
# ---------------------------------------------------------------------------
EVENT_RELEASE_SCHEDULE: dict[str, dict[str, Any]] = {
    "NFP":            {"day_of_month": 3,  "description": "First Friday of month"},
    "CPI":            {"day_of_month": 12, "description": "~12th of month"},
    "PPI":            {"day_of_month": 14, "description": "~14th of month"},
    "RETAIL_SALES":   {"day_of_month": 15, "description": "~15th of month"},
    "FOMC":           {"day_of_month": 18, "description": "~Mid-month (8 times/year)"},
    "GDP":            {"day_of_month": 28, "description": "~End of month (quarterly)"},
    "UNEMPLOYMENT":   {"day_of_month": 3,  "description": "Same day as NFP"},
    "JOBLESS_CLAIMS": {"day_of_month": 0,  "description": "Every Thursday"},
    "ISM_MFG":        {"day_of_month": 1,  "description": "First business day"},
    "ISM_SVC":        {"day_of_month": 3,  "description": "~3rd business day"},
    "PCE":            {"day_of_month": 28, "description": "Last week of month"},
    "FED_SPEECH":     {"day_of_month": 15, "description": "Variable schedule"},
}


class AlphaVantageClient:
    """
    HTTP client for the Alpha Vantage REST API.

    Usage:
        client = AlphaVantageClient()
        data = await client.fetch_economic_indicator("CPI", "monthly")
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.ALPHA_VANTAGE_API_KEY
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    async def close(self):
        await self._client.aclose()

    async def fetch_economic_indicator(
        self,
        function: str,
        interval: str = "monthly",
    ) -> list[dict[str, Any]]:
        """
        Fetch economic indicator time series from Alpha Vantage.

        Example:
            GET https://www.alphavantage.co/query?function=CPI&interval=monthly&apikey=KEY

        Returns list of {"date": "YYYY-MM-DD", "value": float} sorted by date asc.
        """
        params = {
            "function": function,
            "interval": interval,
            "apikey": self.api_key,
        }

        try:
            response = await self._client.get(AV_BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

            # Alpha Vantage returns data in {"data": [...]} format
            raw_list = data.get("data", [])
            if not raw_list:
                # Check for error message
                if "Error Message" in data:
                    logger.error(f"AV API error: {data['Error Message']}")
                elif "Note" in data:
                    logger.warning(f"AV API rate limit: {data['Note']}")
                return []

            records = []
            for item in raw_list:
                value = _parse_float(item.get("value"))
                if value is None:
                    continue
                records.append({
                    "date": item.get("date", ""),
                    "value": value,
                })

            # Sort oldest → newest
            records.sort(key=lambda r: r.get("date", ""))
            return records

        except httpx.HTTPStatusError as e:
            logger.error(f"AV API HTTP error {e.response.status_code}: {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"AV API request failed: {e}")
            return []

    async def fetch_treasury_yield(
        self,
        interval: str = "monthly",
        maturity: str = "10year",
    ) -> list[dict[str, Any]]:
        """Fetch US Treasury Yield data (2year, 5year, 10year, 30year)."""
        params = {
            "function": "TREASURY_YIELD",
            "interval": interval,
            "maturity": maturity,
            "apikey": self.api_key,
        }

        try:
            response = await self._client.get(AV_BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            raw_list = data.get("data", [])

            records = []
            for item in raw_list:
                value = _parse_float(item.get("value"))
                if value is not None:
                    records.append({"date": item.get("date", ""), "value": value})

            records.sort(key=lambda r: r.get("date", ""))
            return records
        except Exception as e:
            logger.error(f"AV Treasury Yield request failed: {e}")
            return []


# ---------------------------------------------------------------------------
# Data ingestion — fetch & store calendar data
# ---------------------------------------------------------------------------

async def ingest_calendar_data(db: AsyncSession) -> int:
    """
    Generate upcoming release schedule + fetch latest actual values
    from Alpha Vantage and upsert into DB.

    Since Alpha Vantage doesn't provide a future calendar, we:
    1. Generate upcoming release dates from known schedule patterns
    2. Fetch the latest historical values to populate Previous values
    3. Estimate Forecast from recent trend

    Returns the number of releases created or updated.
    """
    client = AlphaVantageClient()
    count = 0

    try:
        # Get all active tracked events
        result = await db.execute(
            select(EconomicEvent).where(EconomicEvent.is_active.is_(True))
        )
        events = result.scalars().all()

        for event in events:
            av_config = EVENT_TO_AV_FUNCTION.get(event.event_code)
            if not av_config:
                continue

            # Fetch latest data from Alpha Vantage
            records = await client.fetch_economic_indicator(
                function=av_config["function"],
                interval=av_config["interval"],
            )

            # Store historical releases that we don't have yet
            for record in records[-24:]:  # Last 24 data points
                date_str = record.get("date")
                value = record.get("value")
                if not date_str or value is None:
                    continue

                try:
                    release_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    continue

                # Check if release exists
                existing = await db.execute(
                    select(EconomicRelease).where(
                        EconomicRelease.event_id == event.id,
                        EconomicRelease.release_date == release_date,
                    )
                )
                release = existing.scalar_one_or_none()

                if release:
                    # Update with actual value if missing
                    if release.actual_value is None and value is not None:
                        release.actual_value = value
                        release.is_released = True
                else:
                    # Find previous value (prior record)
                    idx = next(
                        (i for i, r in enumerate(records) if r["date"] == date_str),
                        -1,
                    )
                    prev_value = records[idx - 1]["value"] if idx > 0 else None

                    release = EconomicRelease(
                        event_id=event.id,
                        release_date=release_date,
                        period_label=_build_period_label(release_date),
                        previous_value=prev_value,
                        forecast_value=prev_value,  # Use previous as forecast estimate
                        actual_value=value,
                        deviation=(
                            round(value - prev_value, 4) if prev_value else None
                        ),
                        is_released=True,
                        raw_api_data=record,
                    )
                    db.add(release)
                    count += 1

            # Generate upcoming (future) releases for the next 2 months
            generated = await _generate_upcoming_releases(db, event, records)
            count += generated

    finally:
        await client.close()

    await db.commit()
    logger.info(f"Ingested {count} releases from Alpha Vantage.")
    return count


async def _generate_upcoming_releases(
    db: AsyncSession,
    event: EconomicEvent,
    historical_records: list[dict],
) -> int:
    """
    Generate placeholder upcoming releases for the next 2 months based
    on known schedule patterns. Sets Previous from latest actual and
    Forecast from recent average.
    """
    schedule = EVENT_RELEASE_SCHEDULE.get(event.event_code)
    if not schedule:
        return 0

    now = datetime.now(timezone.utc)
    day = schedule["day_of_month"]
    count = 0

    # Get latest 3 values for trend-based forecast
    recent_values = [r["value"] for r in historical_records[-3:] if r.get("value")]
    avg_forecast = sum(recent_values) / len(recent_values) if recent_values else None
    latest_value = recent_values[-1] if recent_values else None

    # If an upcoming unreleased release already exists for this event, do NOT generate duplicate placeholders
    existing_unreleased = await db.execute(
        select(EconomicRelease).where(
            EconomicRelease.event_id == event.id,
            EconomicRelease.is_released.is_(False),
        )
    )
    if existing_unreleased.scalars().first():
        return 0

    # Generate for next 2 months
    for month_offset in range(1, 3):
        target_month = now.month + month_offset
        target_year = now.year
        if target_month > 12:
            target_month -= 12
            target_year += 1

        if day == 0:
            # Weekly event (e.g., Jobless Claims) — generate next Thursday at 12:30 UTC
            release_date = _next_weekday(now + timedelta(days=7 * month_offset), 3)
        else:
            try:
                release_date = datetime(
                    target_year, target_month, min(day, 28),
                    12, 30, 0, tzinfo=timezone.utc  # 8:30 AM EDT default = 12:30 UTC = 19:30 WIB
                )
            except ValueError:
                continue

        # Skip past dates
        if release_date <= now:
            continue

        # Skip if already exists
        existing = await db.execute(
            select(EconomicRelease).where(
                EconomicRelease.event_id == event.id,
                EconomicRelease.release_date == release_date,
            )
        )
        if existing.scalar_one_or_none():
            continue

        release = EconomicRelease(
            event_id=event.id,
            release_date=release_date,
            period_label=_build_period_label(release_date),
            previous_value=latest_value,
            forecast_value=round(avg_forecast, 2) if avg_forecast else None,
            is_released=False,
        )
        db.add(release)
        count += 1

    return count


# ---------------------------------------------------------------------------
# Historical data ingestion (for initial seeding)
# ---------------------------------------------------------------------------

async def ingest_historical_data(
    db: AsyncSession,
    months: int = 12,
) -> int:
    """
    Fetch historical data for all tracked events from Alpha Vantage.
    Alpha Vantage returns full history by default, we filter to `months`.
    """
    client = AlphaVantageClient()
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

    result = await db.execute(
        select(EconomicEvent).where(EconomicEvent.is_active.is_(True))
    )
    events = result.scalars().all()

    total = 0
    for event in events:
        av_config = EVENT_TO_AV_FUNCTION.get(event.event_code)
        if not av_config:
            continue

        try:
            records = await client.fetch_economic_indicator(
                function=av_config["function"],
                interval=av_config["interval"],
            )
        except Exception as e:
            logger.error(f"Failed to fetch history for {event.event_code}: {e}")
            continue

        prev_value = None
        for record in records:
            date_str = record.get("date")
            value = record.get("value")
            if not date_str or value is None:
                prev_value = value
                continue

            try:
                release_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                prev_value = value
                continue

            # Filter by cutoff
            if release_date < cutoff:
                prev_value = value
                continue

            # Skip if already exists
            existing = await db.execute(
                select(EconomicRelease).where(
                    EconomicRelease.event_id == event.id,
                    EconomicRelease.release_date == release_date,
                )
            )
            if existing.scalar_one_or_none():
                prev_value = value
                continue

            deviation = round(value - prev_value, 4) if prev_value else None

            release = EconomicRelease(
                event_id=event.id,
                release_date=release_date,
                period_label=_build_period_label(release_date),
                previous_value=prev_value,
                forecast_value=prev_value,  # Estimate: use previous as forecast
                actual_value=value,
                deviation=deviation,
                is_released=True,
            )
            db.add(release)
            total += 1
            prev_value = value

    await client.close()
    await db.commit()
    logger.info(f"Ingested {total} historical records from Alpha Vantage.")
    return total


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _parse_float(val: Any) -> float | None:
    """Safely parse a value to float, returning None on failure."""
    if val is None or val == "" or val == "None" or val == ".":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _build_period_label(dt: datetime) -> str:
    """Build a human-readable period label like 'Aug 2026'."""
    return dt.strftime("%b %Y")


def _next_weekday(dt: datetime, weekday: int) -> datetime:
    """
    Find the next occurrence of a given weekday (0=Mon, 3=Thu, etc).
    """
    days_ahead = weekday - dt.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    target = dt + timedelta(days=days_ahead)
    return target.replace(hour=12, minute=30, second=0, microsecond=0, tzinfo=timezone.utc)
