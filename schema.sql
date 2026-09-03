-- =============================================================================
-- Info Trader — PostgreSQL Schema & Seed Data
-- =============================================================================
-- Loaded automatically by docker-compose via /docker-entrypoint-initdb.d/

-- Enable uuid-ossp extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------------
-- 1. Users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email         VARCHAR(255) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name     VARCHAR(255),
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 2. Economic Events (Master Table — 12 High Impact US News)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS economic_events (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_name    VARCHAR(255) NOT NULL,
    event_code    VARCHAR(50) UNIQUE NOT NULL,
    description   TEXT,
    impact        VARCHAR(10) NOT NULL DEFAULT 'HIGH' CHECK (impact IN ('HIGH', 'MEDIUM', 'LOW')),
    country_code  VARCHAR(10) NOT NULL DEFAULT 'US',
    source_api    VARCHAR(100) DEFAULT 'trading_economics',
    is_active     BOOLEAN DEFAULT TRUE
);

-- ---------------------------------------------------------------------------
-- 3. Economic Releases (Scheduled & Historical Data Points)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS economic_releases (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID NOT NULL REFERENCES economic_events(id) ON DELETE CASCADE,
    release_date    TIMESTAMPTZ NOT NULL,
    period_label    VARCHAR(50),
    previous_value  DOUBLE PRECISION,
    forecast_value  DOUBLE PRECISION,
    actual_value    DOUBLE PRECISION,
    deviation       DOUBLE PRECISION,
    usd_outcome     VARCHAR(20) CHECK (usd_outcome IN ('GOOD_FOR_USD', 'BAD_FOR_USD', 'NEUTRAL')),
    is_released     BOOLEAN DEFAULT FALSE,
    raw_api_data    JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_releases_event_id ON economic_releases(event_id);
CREATE INDEX idx_releases_date ON economic_releases(release_date DESC);
CREATE INDEX idx_releases_released ON economic_releases(is_released);

-- ---------------------------------------------------------------------------
-- 4. Leading Indicator Configuration (Weights & Relationships)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leading_indicator_configs (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_event_code     VARCHAR(50) NOT NULL,
    indicator_code        VARCHAR(50) NOT NULL,
    indicator_name        VARCHAR(255) NOT NULL,
    weight                DOUBLE PRECISION NOT NULL DEFAULT 0.25,
    correlation_direction INTEGER NOT NULL DEFAULT 1,  -- +1 = positive, -1 = negative
    description           TEXT,
    UNIQUE(target_event_code, indicator_code)
);

-- ---------------------------------------------------------------------------
-- 5. Prediction Logs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prediction_logs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    release_id          UUID NOT NULL REFERENCES economic_releases(id) ON DELETE CASCADE,
    signal              VARCHAR(10) NOT NULL CHECK (signal IN ('BUY', 'SELL', 'NEUTRAL')),
    signal_label        VARCHAR(50) NOT NULL,
    signal_subtitle     TEXT,
    confidence_score    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    composite_score     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    engine_metadata     JSONB,
    is_correct          BOOLEAN,
    predicted_at        TIMESTAMPTZ DEFAULT NOW(),
    accuracy_checked_at TIMESTAMPTZ
);

CREATE INDEX idx_predictions_release ON prediction_logs(release_id);
CREATE INDEX idx_predictions_signal ON prediction_logs(signal);

-- ===========================================================================
-- SEED DATA: 12 High Impact US Economic Events
-- ===========================================================================
INSERT INTO economic_events (event_name, event_code, description, impact) VALUES
('FOMC Interest Rate Decision',         'FOMC',           'Federal Funds Rate decision and monetary policy statement by the Federal Reserve.', 'HIGH'),
('Non-Farm Payrolls',                   'NFP',            'Monthly change in non-farm employment, measuring US labor market health.', 'HIGH'),
('Consumer Price Index',                'CPI',            'Measures changes in consumer prices for a basket of goods and services (inflation gauge).', 'HIGH'),
('Core PCE Price Index',                'PCE',            'The Fed''s preferred inflation measure — Personal Consumption Expenditures price changes.', 'HIGH'),
('Gross Domestic Product',              'GDP',            'Total value of goods and services produced in the US (quarterly, advance estimate has highest impact).', 'HIGH'),
('Advance Retail Sales',                'RETAIL_SALES',   'Total receipts of retail stores — key measure of consumer spending strength.', 'HIGH'),
('Unemployment Rate',                   'UNEMPLOYMENT',   'Percentage of the labor force that is unemployed and actively seeking work.', 'HIGH'),
('Initial Jobless Claims',              'JOBLESS_CLAIMS', 'Weekly count of new unemployment benefit filings — most real-time labor market indicator.', 'HIGH'),
('ISM Manufacturing PMI',               'ISM_MFG',        'Purchasing Managers'' Index for manufacturing sector. Above 50 = expansion.', 'HIGH'),
('ISM Services PMI',                    'ISM_SVC',        'Purchasing Managers'' Index for services sector. Services = 75%+ of US economy.', 'HIGH'),
('Producer Price Index',                'PPI',            'Measures wholesale/producer-level inflation — a leading indicator for CPI.', 'HIGH'),
('Fed Chair Speech & Press Conference', 'FED_SPEECH',     'Official remarks or press conference by the Federal Reserve Chair.', 'HIGH')
ON CONFLICT (event_code) DO NOTHING;

-- ===========================================================================
-- SEED DATA: Leading Indicator Configurations
-- ===========================================================================
-- NFP leading indicators (from IndicatorAnalysisFullNews.md Section 2.2)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('NFP', 'ADP',            'ADP Non-Farm Employment Change',          0.35,  1, 'Private sector employment change, released 2 days before NFP. Strong positive correlation.'),
('NFP', 'JOBLESS_4W',     'Initial Jobless Claims (4-Week Avg)',     0.25, -1, 'Rising claims indicate weakening NFP. Negative correlation.'),
('NFP', 'ISM_EMP',        'ISM Manufacturing & Services Employment', 0.20,  1, 'Sub-index above 50 indicates employment expansion across sectors.'),
('NFP', 'JOLTS',          'JOLTS Job Openings',                      0.20,  1, 'Higher job openings = higher labor absorption capacity.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- CPI leading indicators (from IndicatorAnalysisFullNews.md Section 2.3)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('CPI', 'PPI_FD',         'PPI Final Demand',                        0.35,  1, 'Producer-level inflation leads consumer inflation by 1-2 months.'),
('CPI', 'ISM_PRICES',     'ISM Manufacturing Prices Paid',           0.30,  1, 'Business input costs above 55 indicate CPI inflationary pressure.'),
('CPI', 'WTI_OIL',        'Crude Oil WTI Price (Monthly Avg)',       0.20,  1, 'Energy prices directly contribute to headline CPI.'),
('CPI', 'IMPORT_PRICES',  'Import & Export Price Index',             0.15,  1, 'Import price pressures feed into consumer goods pricing.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- PCE leading indicators (Section 2.4)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('PCE', 'CPI_MONTHLY',    'CPI Monthly Release',                     0.45,  1, '60-70% of CPI components feed into PCE calculation.'),
('PCE', 'PPI_HEALTHCARE', 'PPI Healthcare & Aviation Components',    0.30,  1, 'Specific PPI components directly converted to Core PCE by BEA.'),
('PCE', 'PERSONAL_SPEND', 'Personal Income & Spending',              0.25,  1, 'Higher spending drives demand-pull inflation into PCE.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- GDP leading indicators (Section 2.5)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('GDP', 'GDPNOW',         'Atlanta Fed GDPNow Tracking Estimate',    0.40,  1, 'Real-time quantitative GDP tracking model by Atlanta Fed.'),
('GDP', 'RETAIL_QTD',     'Retail Sales Cumulative (Quarterly)',      0.30,  1, 'Domestic consumption = ~70% of US GDP.'),
('GDP', 'TRADE_BALANCE',  'Trade Balance (Net Exports)',              0.15, -1, 'Shrinking trade deficit adds positive GDP contribution.'),
('GDP', 'DURABLE_GOODS',  'Durable Goods Orders',                    0.15,  1, 'Measures corporate capital expenditure and business investment.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- Retail Sales leading indicators (Section 2.6)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('RETAIL_SALES', 'UMICH_SENT',    'U. of Michigan Consumer Sentiment',    0.35,  1, 'Consumer optimism correlates with higher retail spending.'),
('RETAIL_SALES', 'AVG_HOURLY',    'Average Hourly Earnings (from NFP)',    0.30,  1, 'Higher real income per hour provides extra household purchasing power.'),
('RETAIL_SALES', 'REDBOOK',       'Redbook Index (Weekly Same-Store)',     0.20,  1, 'Weekly retail chain sales data — real-time retail activity proxy.'),
('RETAIL_SALES', 'AUTO_SALES',    'Auto Sales Data',                       0.15,  1, 'Vehicle sales constitute a large portion of retail sales component.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- ISM Manufacturing PMI leading indicators (Section 2.9)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('ISM_MFG', 'PHILLY_FED',   'Philadelphia Fed Manufacturing Index',     0.30,  1, 'Regional Fed index released earlier in the month, strong ISM correlation.'),
('ISM_MFG', 'EMPIRE_STATE', 'Empire State Manufacturing Index',         0.25,  1, 'NY Fed regional manufacturing survey, released mid-month.'),
('ISM_MFG', 'SP_MFG_PMI',   'S&P Global US Manufacturing PMI (Flash)', 0.25,  1, 'Flash estimate released 1-2 weeks before ISM.'),
('ISM_MFG', 'FACTORY_ORD',  'Factory Orders & Durable Goods Orders',    0.20,  1, 'New factory orders indicate future manufacturing activity.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- ISM Services PMI leading indicators (Section 2.10)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('ISM_SVC', 'SP_SVC_PMI',   'S&P Global US Services PMI (Flash)',       0.55,  1, 'Flash estimate 1-2 weeks before ISM Services. Strong positive correlation.'),
('ISM_SVC', 'CONS_CONF',    'Consumer Confidence Index (Conference Board)', 0.45, 1, 'Consumer confidence drives services sector spending.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- PPI leading indicators (Section 2.11)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('PPI', 'CRB_INDEX',     'CRB Commodity Price Index',                 0.40,  1, 'Raw material and industrial commodity prices.'),
('PPI', 'ISM_MFG_PRICES','ISM Manufacturing Prices Paid',             0.35,  1, 'Input costs paid by manufacturers for raw materials.'),
('PPI', 'FREIGHT_RATES', 'Global Freight & Shipping Rates',           0.25,  1, 'Logistics costs affecting intermediate producer prices.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- FOMC leading indicators (Section 2.1)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('FOMC', 'FEDWATCH',      'CME FedWatch Hawkish Probability',         0.40,  1, 'Market-implied probability of rate hike from Fed Funds futures.'),
('FOMC', 'CORE_PCE_3M',   'Core PCE 3-Month Trend',                   0.35,  1, 'Persistent inflation above 2% target biases Fed hawkish.'),
('FOMC', 'WAGE_GROWTH',   'Average Hourly Earnings Growth',            0.25,  1, 'Rising wages trigger second-round inflation (wage-price spiral).')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- Unemployment Rate leading indicators (Section 2.7)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('UNEMPLOYMENT', 'CONT_CLAIMS',  'Continuing Jobless Claims',              0.45,  1, 'People still receiving unemployment benefits — directly correlated.'),
('UNEMPLOYMENT', 'LABOR_PART',   'Labor Force Participation Rate',          0.30, -1, 'Rising participation with limited openings can raise unemployment.'),
('UNEMPLOYMENT', 'HOUSEHOLD_EMP','Household Survey Employment',             0.25, -1, 'Unemployment rate is derived from Household Survey, not Establishment Survey.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- Initial Jobless Claims leading indicators (Section 2.8)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('JOBLESS_CLAIMS', 'CHALLENGER_CUTS', 'Challenger Job Cuts Report',         0.50,  1, 'Mass layoff announcements precede weekly claims spikes.'),
('JOBLESS_CLAIMS', 'WARN_NOTICES',    'State-Level WARN Act Notices',       0.30,  1, 'Official mass layoff notifications at state level.'),
('JOBLESS_CLAIMS', 'SEASONAL_ADJ',    'Seasonal Adjustment Factor',         0.20,  1, 'Post-holiday periods (Jan/Jul) cause temporary claims deviations.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- Fed Chair Speech leading indicators (Section 2.12)
INSERT INTO leading_indicator_configs (target_event_code, indicator_code, indicator_name, weight, correlation_direction, description) VALUES
('FED_SPEECH', 'RECENT_INFLATION', 'Recent Inflation Deviation (30-Day)', 0.40,  1, 'Declining inflation in last 30 days biases dovish speech tone.'),
('FED_SPEECH', 'FCI',              'Financial Conditions Index (Chicago Fed)', 0.35, -1, 'Loose financial conditions may trigger hawkish jawboning by Fed Chair.'),
('FED_SPEECH', 'FEDSPEAK',         'Recent Fed Governor Comments (Pre-Blackout)', 0.25, 1, 'Committee member tone reflects internal consensus before speech.')
ON CONFLICT (target_event_code, indicator_code) DO NOTHING;

-- ===========================================================================
-- SEED DATA: Baseline Upcoming Releases & Active Hero Prediction
-- ===========================================================================
DO $$
DECLARE
    v_cpi_id UUID;
    v_nfp_id UUID;
    v_unemp_id UUID;
    v_claims_id UUID;
    v_ppi_id UUID;
    v_retail_id UUID;
    v_fomc_id UUID;
    v_gdp_id UUID;
    v_cpi_release_id UUID := uuid_generate_v4();
    v_hist_release_id UUID;
BEGIN
    SELECT id INTO v_cpi_id FROM economic_events WHERE event_code = 'CPI';
    SELECT id INTO v_nfp_id FROM economic_events WHERE event_code = 'NFP';
    SELECT id INTO v_unemp_id FROM economic_events WHERE event_code = 'UNEMPLOYMENT';
    SELECT id INTO v_claims_id FROM economic_events WHERE event_code = 'JOBLESS_CLAIMS';
    SELECT id INTO v_ppi_id FROM economic_events WHERE event_code = 'PPI';
    SELECT id INTO v_retail_id FROM economic_events WHERE event_code = 'RETAIL_SALES';
    SELECT id INTO v_fomc_id FROM economic_events WHERE event_code = 'FOMC';
    SELECT id INTO v_gdp_id FROM economic_events WHERE event_code = 'GDP';

    -- Only seed releases if table is empty
    IF NOT EXISTS (SELECT 1 FROM economic_releases LIMIT 1) THEN
        -- 1. Upcoming CPI (Tomorrow at 13:30 UTC)
        INSERT INTO economic_releases (id, event_id, release_date, period_label, previous_value, forecast_value, is_released)
        VALUES (v_cpi_release_id, v_cpi_id, NOW() + INTERVAL '1 day', TO_CHAR(NOW(), 'Mon YYYY'), 3.1, 2.9, FALSE);

        -- Active Hero Prediction for CPI (BUY XAUUSD - 78% Confidence)
        INSERT INTO prediction_logs (release_id, signal, signal_label, signal_subtitle, confidence_score, composite_score, engine_metadata, predicted_at)
        VALUES (
            v_cpi_release_id,
            'BUY',
            'BUY XAUUSD',
            'Predicted Bias: BAD FOR USD (Dovish CPI)',
            78.4,
            -0.68,
            '{"indicators": [
                {"code": "PPI_FD", "weight": 0.35, "actual": 0.20, "forecast": 0.30, "deviation": -0.10, "raw_score": -0.80, "weighted_score": -0.28},
                {"code": "ISM_PRICES", "weight": 0.30, "actual": 52.4, "forecast": 54.0, "deviation": -1.60, "raw_score": -0.75, "weighted_score": -0.225},
                {"code": "WTI_OIL", "weight": 0.20, "actual": 74.20, "forecast": 76.50, "deviation": -2.30, "raw_score": -0.65, "weighted_score": -0.13},
                {"code": "IMPORT_PRICES", "weight": 0.15, "actual": 0.10, "forecast": 0.20, "deviation": -0.10, "raw_score": -0.30, "weighted_score": -0.045}
            ]}',
            NOW() - INTERVAL '2 hours'
        );

        -- 2. Upcoming NFP (This Friday)
        INSERT INTO economic_releases (event_id, release_date, period_label, previous_value, forecast_value, is_released)
        VALUES (v_nfp_id, NOW() + INTERVAL '2 days', TO_CHAR(NOW(), 'Mon YYYY'), 175.0, 160.0, FALSE);

        -- 3. Upcoming Unemployment Rate
        INSERT INTO economic_releases (event_id, release_date, period_label, previous_value, forecast_value, is_released)
        VALUES (v_unemp_id, NOW() + INTERVAL '2 days', TO_CHAR(NOW(), 'Mon YYYY'), 4.1, 4.1, FALSE);

        -- 4. Initial Jobless Claims
        INSERT INTO economic_releases (event_id, release_date, period_label, previous_value, forecast_value, is_released)
        VALUES (v_claims_id, NOW() + INTERVAL '1 day 2 hours', 'Weekly', 228.0, 225.0, FALSE);

        -- 5. Upcoming PPI
        INSERT INTO economic_releases (event_id, release_date, period_label, previous_value, forecast_value, is_released)
        VALUES (v_ppi_id, NOW() + INTERVAL '5 days', TO_CHAR(NOW(), 'Mon YYYY'), 0.2, 0.3, FALSE);

        -- 6. Retail Sales
        INSERT INTO economic_releases (event_id, release_date, period_label, previous_value, forecast_value, is_released)
        VALUES (v_retail_id, NOW() + INTERVAL '7 days', TO_CHAR(NOW(), 'Mon YYYY'), 0.4, 0.3, FALSE);

        -- 7. FOMC
        INSERT INTO economic_releases (event_id, release_date, period_label, previous_value, forecast_value, is_released)
        VALUES (v_fomc_id, NOW() + INTERVAL '10 days', 'Rate Decision', 5.50, 5.25, FALSE);

        -- 8. Historical Releases & Prediction Accuracy Logs
        -- Sample 1: CPI Hit
        v_hist_release_id := uuid_generate_v4();
        INSERT INTO economic_releases (id, event_id, release_date, period_label, previous_value, forecast_value, actual_value, deviation, usd_outcome, is_released)
        VALUES (v_hist_release_id, v_cpi_id, NOW() - INTERVAL '30 days', 'Jan 2026', 3.2, 3.1, 2.9, -0.2, 'BAD_FOR_USD', TRUE);
        INSERT INTO prediction_logs (release_id, signal, signal_label, signal_subtitle, confidence_score, composite_score, is_correct, predicted_at, accuracy_checked_at)
        VALUES (v_hist_release_id, 'BUY', 'BUY XAUUSD', 'Predicted Bias: BAD_FOR_USD', 74.0, -0.72, TRUE, NOW() - INTERVAL '30 days 3 hours', NOW() - INTERVAL '30 days');

        -- Sample 2: NFP Hit
        v_hist_release_id := uuid_generate_v4();
        INSERT INTO economic_releases (id, event_id, release_date, period_label, previous_value, forecast_value, actual_value, deviation, usd_outcome, is_released)
        VALUES (v_hist_release_id, v_nfp_id, NOW() - INTERVAL '35 days', 'Jan 2026', 185.0, 170.0, 142.0, -28.0, 'BAD_FOR_USD', TRUE);
        INSERT INTO prediction_logs (release_id, signal, signal_label, signal_subtitle, confidence_score, composite_score, is_correct, predicted_at, accuracy_checked_at)
        VALUES (v_hist_release_id, 'BUY', 'BUY XAUUSD', 'Predicted Bias: BAD_FOR_USD', 81.5, -0.80, TRUE, NOW() - INTERVAL '35 days 3 hours', NOW() - INTERVAL '35 days');

        -- Sample 3: Retail Sales Hit
        v_hist_release_id := uuid_generate_v4();
        INSERT INTO economic_releases (id, event_id, release_date, period_label, previous_value, forecast_value, actual_value, deviation, usd_outcome, is_released)
        VALUES (v_hist_release_id, v_retail_id, NOW() - INTERVAL '45 days', 'Dec 2025', 0.3, 0.2, 0.5, 0.3, 'GOOD_FOR_USD', TRUE);
        INSERT INTO prediction_logs (release_id, signal, signal_label, signal_subtitle, confidence_score, composite_score, is_correct, predicted_at, accuracy_checked_at)
        VALUES (v_hist_release_id, 'SELL', 'SELL XAUUSD', 'Predicted Bias: GOOD_FOR_USD', 68.0, 0.65, TRUE, NOW() - INTERVAL '45 days 3 hours', NOW() - INTERVAL '45 days');

        -- Sample 4: CPI Miss
        v_hist_release_id := uuid_generate_v4();
        INSERT INTO economic_releases (id, event_id, release_date, period_label, previous_value, forecast_value, actual_value, deviation, usd_outcome, is_released)
        VALUES (v_hist_release_id, v_cpi_id, NOW() - INTERVAL '62 days', 'Dec 2025', 3.4, 3.2, 3.3, 0.1, 'GOOD_FOR_USD', TRUE);
        INSERT INTO prediction_logs (release_id, signal, signal_label, signal_subtitle, confidence_score, composite_score, is_correct, predicted_at, accuracy_checked_at)
        VALUES (v_hist_release_id, 'SELL', 'SELL XAUUSD', 'Predicted Bias: GOOD_FOR_USD', 65.0, 0.60, TRUE, NOW() - INTERVAL '62 days 3 hours', NOW() - INTERVAL '62 days');

        -- Sample 5: GDP Hit
        v_hist_release_id := uuid_generate_v4();
        INSERT INTO economic_releases (id, event_id, release_date, period_label, previous_value, forecast_value, actual_value, deviation, usd_outcome, is_released)
        VALUES (v_hist_release_id, v_gdp_id, NOW() - INTERVAL '75 days', 'Q4 2025', 2.1, 2.5, 2.8, 0.3, 'GOOD_FOR_USD', TRUE);
        INSERT INTO prediction_logs (release_id, signal, signal_label, signal_subtitle, confidence_score, composite_score, is_correct, predicted_at, accuracy_checked_at)
        VALUES (v_hist_release_id, 'SELL', 'SELL XAUUSD', 'Predicted Bias: GOOD_FOR_USD', 85.0, 0.88, TRUE, NOW() - INTERVAL '75 days 3 hours', NOW() - INTERVAL '75 days');

        -- Sample 6: CPI Neutral / Miss
        v_hist_release_id := uuid_generate_v4();
        INSERT INTO economic_releases (id, event_id, release_date, period_label, previous_value, forecast_value, actual_value, deviation, usd_outcome, is_released)
        VALUES (v_hist_release_id, v_cpi_id, NOW() - INTERVAL '122 days', 'Oct 2025', 3.7, 3.6, 3.8, 0.2, 'GOOD_FOR_USD', TRUE);
        INSERT INTO prediction_logs (release_id, signal, signal_label, signal_subtitle, confidence_score, composite_score, is_correct, predicted_at, accuracy_checked_at)
        VALUES (v_hist_release_id, 'BUY', 'BUY XAUUSD', 'Predicted Bias: BAD_FOR_USD', 69.0, -0.65, FALSE, NOW() - INTERVAL '122 days 3 hours', NOW() - INTERVAL '122 days');
    END IF;
END $$;
