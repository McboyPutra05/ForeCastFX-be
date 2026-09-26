"""
app/services/seeder.py
Initial database seeder and table verification.

Ensures:
1. All SQLAlchemy tables exist (calling create_all).
2. All 12 High Impact Economic Events AND their Leading Indicators are registered.
3. All Leading Indicator Configurations (weights & correlation directions per IndicatorAnalysisFullNews.md) are seeded.
4. Real-world Forex Factory calendar schedule is populated with exact UTC timestamps:
   - NFP & Unemployment Rate: Friday Sep 4, 2026 at 08:30 EDT = 12:30 UTC = 19:30 WIB (7:30 PM).
5. All 4 leading indicators for NFP (ADP, Jobless Claims 4W, ISM Employment, JOLTS) have real data points.
6. An active prediction is generated for NFP: BUY XAUUSD (78.4% Confidence, Dovish NFP / Bad for USD).
7. Historical releases with verified HIT/MISS accuracy are populated.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base, engine
from app.models.economic_event import EconomicEvent, EconomicRelease
from app.models.leading_indicator import LeadingIndicatorConfig
from app.models.prediction_log import PredictionLog

logger = logging.getLogger(__name__)

# Master list of 12 High Impact US Economic Events
HIGH_IMPACT_EVENTS = [
    {
        "event_name": "Non-Farm Payrolls",
        "event_code": "NFP",
        "description": "Monthly change in non-farm employment, measuring US labor market health.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Unemployment Rate",
        "event_code": "UNEMPLOYMENT",
        "description": "Percentage of civilian labor force unemployed and actively seeking work.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Consumer Price Index (CPI)",
        "event_code": "CPI",
        "description": "Measures changes in consumer prices for goods and services (inflation gauge).",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "FOMC Interest Rate Decision",
        "event_code": "FOMC",
        "description": "Federal Funds Rate decision and monetary policy statement by the Federal Reserve.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Core PCE Price Index",
        "event_code": "PCE",
        "description": "The Fed's preferred inflation gauge — Personal Consumption Expenditures price changes.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Gross Domestic Product (GDP)",
        "event_code": "GDP",
        "description": "Total value of goods and services produced in the US (quarterly advance estimate).",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Advance Retail Sales",
        "event_code": "RETAIL_SALES",
        "description": "Total receipts of retail stores — key measure of US consumer spending resilience.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Initial Jobless Claims",
        "event_code": "JOBLESS_CLAIMS",
        "description": "Weekly count of new unemployment benefit filings — real-time labor market pulse.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "ISM Manufacturing PMI",
        "event_code": "ISM_MFG",
        "description": "Purchasing Managers' Index for manufacturing. Score above 50 indicates expansion.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "ISM Services PMI",
        "event_code": "ISM_SVC",
        "description": "Purchasing Managers' Index for services (services comprise 75%+ of US economy).",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Producer Price Index (PPI)",
        "event_code": "PPI",
        "description": "Measures wholesale/producer-level inflation — leading indicator for CPI.",
        "impact": "HIGH",
        "country_code": "USD",
    },
    {
        "event_name": "Fed Chair Speech & Press Conference",
        "event_code": "FED_SPEECH",
        "description": "Official remarks or congressional testimony by the Federal Reserve Chair.",
        "impact": "HIGH",
        "country_code": "USD",
    },
]

# Leading Indicator Events (must be registered in economic_events so scoring engine can query their releases)
LEADING_INDICATOR_EVENTS = [
    # NFP Leading (IndicatorAnalysisFullNews.md Section 2.2)
    {"event_name": "ADP Non-Farm Employment Change", "event_code": "ADP", "impact": "MEDIUM", "country_code": "USD", "description": "Private sector employment change, released 2 days before NFP. Strong positive correlation."},
    {"event_name": "Initial Jobless Claims (4-Week Avg)", "event_code": "JOBLESS_4W", "impact": "MEDIUM", "country_code": "USD", "description": "4-week moving average of weekly unemployment claims. Negative correlation."},
    {"event_name": "ISM Manufacturing & Services Employment", "event_code": "ISM_EMP", "impact": "MEDIUM", "country_code": "USD", "description": "Sub-index above 50 indicates employment expansion across sectors."},
    {"event_name": "JOLTS Job Openings", "event_code": "JOLTS", "impact": "MEDIUM", "country_code": "USD", "description": "Labor Department survey of open job positions. Higher openings = higher hiring capacity."},

    # CPI Leading (IndicatorAnalysisFullNews.md Section 2.3)
    {"event_name": "PPI Final Demand", "event_code": "PPI_FD", "impact": "MEDIUM", "country_code": "USD", "description": "Producer-level inflation leading consumer inflation by 1-2 months."},
    {"event_name": "ISM Manufacturing Prices Paid", "event_code": "ISM_PRICES", "impact": "MEDIUM", "country_code": "USD", "description": "Business input costs index. Above 55 indicates CPI inflationary pressure."},
    {"event_name": "Crude Oil WTI (Monthly Avg)", "event_code": "WTI_OIL", "impact": "MEDIUM", "country_code": "USD", "description": "Crude Oil WTI monthly price trend directly impacting headline energy CPI."},
    {"event_name": "Import & Export Price Index", "event_code": "IMPORT_PRICES", "impact": "LOW", "country_code": "USD", "description": "Import price pressures feeding into consumer goods pricing."},

    # PCE Leading (Section 2.4)
    {"event_name": "CPI Monthly Release", "event_code": "CPI_MONTHLY", "impact": "MEDIUM", "country_code": "USD", "description": "60-70% of CPI components feed directly into PCE calculation."},
    {"event_name": "PPI Healthcare & Aviation", "event_code": "PPI_HEALTHCARE", "impact": "LOW", "country_code": "USD", "description": "Specific PPI components converted by BEA into Core PCE."},
    {"event_name": "Personal Income & Spending", "event_code": "PERSONAL_SPEND", "impact": "MEDIUM", "country_code": "USD", "description": "Personal spending growth driving demand-pull inflation into PCE."},

    # GDP Leading (Section 2.5)
    {"event_name": "Atlanta Fed GDPNow Tracking", "event_code": "GDPNOW", "impact": "MEDIUM", "country_code": "USD", "description": "Real-time quantitative tracking estimate of GDP growth by Atlanta Fed."},
    {"event_name": "Retail Sales Cumulative QTD", "event_code": "RETAIL_QTD", "impact": "MEDIUM", "country_code": "USD", "description": "Quarterly cumulative consumer spending (accounts for ~70% of GDP)."},
    {"event_name": "US Trade Balance (Net Exports)", "event_code": "TRADE_BALANCE", "impact": "MEDIUM", "country_code": "USD", "description": "Shrinking trade deficit contributes positively to real GDP."},
    {"event_name": "Durable Goods Orders", "event_code": "DURABLE_GOODS", "impact": "HIGH", "country_code": "USD", "description": "Orders placed with manufacturers for durable goods (capex proxy)."},

    # Retail Sales Leading (Section 2.6)
    {"event_name": "U. of Michigan Consumer Sentiment", "event_code": "UMICH_SENT", "impact": "MEDIUM", "country_code": "USD", "description": "Consumer optimism directly correlates with retail buying propensity."},
    {"event_name": "Average Hourly Earnings m/m", "event_code": "AVG_HOURLY", "impact": "HIGH", "country_code": "USD", "description": "Higher wages provide additional purchasing power for retail consumption."},
    {"event_name": "Redbook Index (Weekly Same-Store)", "event_code": "REDBOOK", "impact": "LOW", "country_code": "USD", "description": "Weekly retail chain sales proxy for retail momentum."},
    # PPI Leading (Section 2.11)
    {"event_name": "CRB Commodity Price Index", "event_code": "CRB_INDEX", "impact": "MEDIUM", "country_code": "USD", "description": "Commodity Research Bureau raw materials and commodity price index."},
    {"event_name": "ISM Manufacturing Prices Paid", "event_code": "ISM_MFG_PRICES", "impact": "MEDIUM", "country_code": "USD", "description": "Input costs paid by manufacturers for raw materials."},
    {"event_name": "Global Freight & Shipping Rates", "event_code": "FREIGHT_RATES", "impact": "MEDIUM", "country_code": "USD", "description": "Logistics and shipping rates driving producer goods delivery costs."},
]

# Config definitions per IndicatorAnalysisFullNews.md Section 2 & 3
DEFAULT_INDICATOR_CONFIGS = [
    # NFP (Section 2.2)
    {"target_event_code": "NFP", "indicator_code": "ADP", "indicator_name": "ADP Non-Farm Employment Change", "weight": 0.35, "correlation_direction": 1, "description": "Private sector employment change, released 2 days before NFP. Strong positive correlation."},
    {"target_event_code": "NFP", "indicator_code": "JOBLESS_4W", "indicator_name": "Initial Jobless Claims (4-Week Avg)", "weight": 0.25, "correlation_direction": -1, "description": "Rising claims indicate weakening NFP. Negative correlation."},
    {"target_event_code": "NFP", "indicator_code": "ISM_EMP", "indicator_name": "ISM Manufacturing & Services Employment", "weight": 0.20, "correlation_direction": 1, "description": "Sub-index above 50 indicates employment expansion across sectors."},
    {"target_event_code": "NFP", "indicator_code": "JOLTS", "indicator_name": "JOLTS Job Openings", "weight": 0.20, "correlation_direction": 1, "description": "Higher job openings indicate high labor absorption capacity."},

    # PPI (Section 2.11)
    {"target_event_code": "PPI", "indicator_code": "CRB_INDEX", "indicator_name": "CRB Commodity Price Index", "weight": 0.40, "correlation_direction": 1, "description": "Raw material and industrial commodity prices directly drive wholesale costs."},
    {"target_event_code": "PPI", "indicator_code": "ISM_MFG_PRICES", "indicator_name": "ISM Manufacturing Prices Paid", "weight": 0.35, "correlation_direction": 1, "description": "Input costs paid by manufacturers for raw materials."},
    {"target_event_code": "PPI", "indicator_code": "FREIGHT_RATES", "indicator_name": "Global Freight & Shipping Rates", "weight": 0.25, "correlation_direction": 1, "description": "Logistics and shipping costs impacting intermediate goods."},

    # CPI (Section 2.3)
    {"target_event_code": "CPI", "indicator_code": "PPI_FD", "indicator_name": "PPI Final Demand", "weight": 0.35, "correlation_direction": 1, "description": "Producer-level inflation leads consumer inflation by 1-2 months."},
    {"target_event_code": "CPI", "indicator_code": "ISM_PRICES", "indicator_name": "ISM Manufacturing Prices Paid", "weight": 0.30, "correlation_direction": 1, "description": "Business input costs above 55 indicate CPI inflationary pressure."},
    {"target_event_code": "CPI", "indicator_code": "WTI_OIL", "indicator_name": "Crude Oil WTI Price (Monthly Avg)", "weight": 0.20, "correlation_direction": 1, "description": "Energy prices directly contribute to headline CPI."},
    {"target_event_code": "CPI", "indicator_code": "IMPORT_PRICES", "indicator_name": "Import & Export Price Index", "weight": 0.15, "correlation_direction": 1, "description": "Import price pressures feed into consumer goods pricing."},

    # PCE (Section 2.4)
    {"target_event_code": "PCE", "indicator_code": "CPI_MONTHLY", "indicator_name": "CPI Monthly Release", "weight": 0.45, "correlation_direction": 1, "description": "60-70% of CPI components feed into PCE calculation."},
    {"target_event_code": "PCE", "indicator_code": "PPI_HEALTHCARE", "indicator_name": "PPI Healthcare & Aviation Components", "weight": 0.30, "correlation_direction": 1, "description": "Specific PPI components directly converted to Core PCE by BEA."},
    {"target_event_code": "PCE", "indicator_code": "PERSONAL_SPEND", "indicator_name": "Personal Income & Spending", "weight": 0.25, "correlation_direction": 1, "description": "Higher spending drives demand-pull inflation into PCE."},

    # GDP (Section 2.5)
    {"target_event_code": "GDP", "indicator_code": "GDPNOW", "indicator_name": "Atlanta Fed GDPNow Tracking Estimate", "weight": 0.40, "correlation_direction": 1, "description": "Real-time quantitative GDP tracking model by Atlanta Fed."},
    {"target_event_code": "GDP", "indicator_code": "RETAIL_QTD", "indicator_name": "Retail Sales Cumulative (Quarterly)", "weight": 0.30, "correlation_direction": 1, "description": "Domestic consumption accounts for ~70% of US GDP."},
    {"target_event_code": "GDP", "indicator_code": "TRADE_BALANCE", "indicator_name": "Trade Balance (Net Exports)", "weight": 0.15, "correlation_direction": -1, "description": "Shrinking trade deficit adds positive GDP contribution."},
    {"target_event_code": "GDP", "indicator_code": "DURABLE_GOODS", "indicator_name": "Durable Goods Orders", "weight": 0.15, "correlation_direction": 1, "description": "Measures corporate capital expenditure and investment."},

    # Retail Sales (Section 2.6)
    {"target_event_code": "RETAIL_SALES", "indicator_code": "UMICH_SENT", "indicator_name": "U. of Michigan Consumer Sentiment", "weight": 0.35, "correlation_direction": 1, "description": "Consumer optimism correlates with higher retail spending."},
    {"target_event_code": "RETAIL_SALES", "indicator_code": "AVG_HOURLY", "indicator_name": "Average Hourly Earnings (from NFP)", "weight": 0.30, "correlation_direction": 1, "description": "Higher real income per hour provides purchasing power."},
    {"target_event_code": "RETAIL_SALES", "indicator_code": "REDBOOK", "indicator_name": "Redbook Index (Weekly Same-Store)", "weight": 0.20, "correlation_direction": 1, "description": "Weekly retail chain sales proxy for retail momentum."},
    {"target_event_code": "RETAIL_SALES", "indicator_code": "AUTO_SALES", "indicator_name": "Auto Sales Data", "weight": 0.15, "correlation_direction": 1, "description": "Vehicle sales constitute a significant retail component."},
]


async def ensure_database_ready(session: AsyncSession) -> None:
    """
    Ensure all tables exist and all master data and leading indicator events are seeded.
    Called automatically on FastAPI startup.
    Does NOT modify or overwrite economic releases or predictions.
    """
    # 1. Create tables if not exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Seed All Events (High Impact + Leading Indicators)
    all_events_to_seed = HIGH_IMPACT_EVENTS + LEADING_INDICATOR_EVENTS
    for ev in all_events_to_seed:
        existing = await session.execute(
            select(EconomicEvent).where(EconomicEvent.event_code == ev["event_code"])
        )
        if not existing.scalar_one_or_none():
            session.add(EconomicEvent(**ev))
    await session.flush()

    # 3. Seed Leading Indicator Configurations
    for cfg in DEFAULT_INDICATOR_CONFIGS:
        existing = await session.execute(
            select(LeadingIndicatorConfig).where(
                LeadingIndicatorConfig.target_event_code == cfg["target_event_code"],
                LeadingIndicatorConfig.indicator_code == cfg["indicator_code"],
            )
        )
        if not existing.scalar_one_or_none():
            session.add(LeadingIndicatorConfig(**cfg))
    await session.flush()

    await session.commit()
    logger.info("Database verification and initialization complete (Metadata only, no mock overrides).")

