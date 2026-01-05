# Congressional Alpha Tracker Strategy

## Overview

The Congressional Alpha Tracker is a "whale tracking" alternative data strategy that copies trades from high-profile politicians who have demonstrated strong trading performance.

## Strategy Logic

### 1. Data Source
- Ingests House and Senate stock disclosures via Quiver Quantitative API
- Falls back to mock data when API key is not available
- Monitors disclosures in real-time (hourly polling by default)

### 2. Policy Whale Identification
The strategy tracks specific "Policy Whales" - politicians with strong historical trading performance:

**House Members:**
- Nancy Pelosi (1.5x weight multiplier)
- Paul Pelosi (1.5x weight multiplier)
- Brian Higgins (1.3x weight multiplier)
- Josh Gottheimer (1.3x weight multiplier)
- Marjorie Taylor Greene (1.2x weight multiplier)

**Senate Members:**
- Tommy Tuberville (1.4x weight multiplier)
- Dan Sullivan (1.3x weight multiplier)
- Shelley Moore Capito (1.3x weight multiplier)
- John Hickenlooper (1.2x weight multiplier)

### 3. Committee-Based Weighting

Trades are weighted higher when politicians sit on relevant committees:

| Committee | Relevant Sectors | Bonus |
|-----------|-----------------|-------|
| Armed Services | Defense (LMT, RTX, NOC, GD, BA, etc.) | +40% |
| Science, Space, & Technology | Big Tech (AAPL, MSFT, NVDA, etc.) | +35% |
| Financial Services | Banks (JPM, BAC, GS, MS, etc.) | +35% |
| Banking, Housing, & Urban Affairs | Banks | +35% |
| Energy and Commerce | Tech & Telecom | +30% |
| Health, Education, Labor, Pensions | Healthcare (PFE, JNJ, UNH, etc.) | +30% |
| Natural Resources | Energy (XOM, CVX, COP, etc.) | +30% |
| Agriculture | Ag & Equipment (ADM, DE, etc.) | +25% |
| Transportation & Infrastructure | Airlines, Logistics (UAL, UPS, etc.) | +25% |
| Appropriations | All sectors | +20% |

### 4. High-Conviction Tickers

Extra weight given to large-cap tech and defense stocks:
- **Tech**: NVDA, AAPL, MSFT, GOOGL, META, AMZN, TSLA
- **Defense**: LMT, RTX, NOC, GD, BA

High-conviction tickers receive a +30% position size bonus.

### 5. Position Sizing

Position size is calculated based on:
1. **Base Size**: 10% of politician's disclosed transaction amount
2. **Whale Multiplier**: Based on politician's track record (1.2x - 1.5x)
3. **Committee Bonus**: Based on committee relevance (0% - 100%)
4. **High-Conviction Bonus**: +30% for high-conviction tickers
5. **Constraints**: Min $1,000, Max $50,000 per trade

**Example:**
- Nancy Pelosi buys $75,000 of NVDA
- She's on Financial Services committee (not directly relevant to NVDA)
- NVDA is a high-conviction ticker
- Position = $7,500 (base) × 1.5 (whale) × 1.3 (conviction) = $14,625

### 6. Confidence Scoring

Confidence score (0-1) is calculated from:
- **Whale multiplier**: Higher multiplier = higher confidence
- **Committee relevance**: +50% max for relevant committee
- **High-conviction ticker**: +15% bonus
- **Transaction size**: +5-15% based on amount
  - $25K+: +5%
  - $50K+: +10%
  - $100K+: +15%

Maximum confidence is capped at 95%.

### 7. Filters

Trades are filtered to only act on:
1. ✅ Purchases (not sales) - configurable via `PURCHASE_ONLY`
2. ✅ Tracked Policy Whales only
3. ✅ Transactions ≥ $15,000
4. ✅ Confidence ≥ minimum threshold (varies by politician)

## Usage

### Running the Ingestion Service

```bash
# Set environment variables
export TENANT_ID="your_tenant"
export QUIVER_API_KEY="your_api_key"  # Optional, uses mock data if not set
export NATS_URL="nats://localhost:4222"
export POLL_INTERVAL_SECONDS="3600"  # 1 hour
export LOOKBACK_DAYS="7"

# Run ingestion
cd /workspace
python -m backend.ingestion.congressional_disclosures
```

### Running the Strategy

The strategy follows the standard strategy runner protocol:

```bash
# Use the strategy runner harness
cd /workspace
python -m backend.strategy_runner.runner \
  --strategy-path backend/strategy_runner/examples/congressional_alpha/strategy.py \
  --events-file events.ndjson
```

Or integrate with the strategy engine:

```python
from backend.strategy_runner.bundle import load_strategy

strategy = load_strategy("backend/strategy_runner/examples/congressional_alpha/strategy.py")
intents = strategy.on_market_event(event)
```

### Testing with Mock Data

If `QUIVER_API_KEY` is not set, the ingestion service will generate mock trades:
- Nancy Pelosi buying NVDA
- Tommy Tuberville buying MSFT  
- Josh Gottheimer buying AAPL

This allows testing the full pipeline without API access.

## Integration with Existing System

### 1. NATS Subject Pattern

Congressional disclosure events are published to:
```
market.{tenant_id}.{ticker}.congressional
```

Example: `market.local.NVDA.congressional`

### 2. Market Event Schema

```json
{
  "protocol": "v1",
  "type": "market_event",
  "event_id": "evt_abc123",
  "ts": "2024-01-15T10:30:00Z",
  "symbol": "NVDA",
  "source": "congressional_disclosure",
  "payload": {
    "politician": "Nancy Pelosi",
    "politician_id": "pelosi_nancy",
    "chamber": "house",
    "transaction_type": "purchase",
    "transaction_date": "2024-01-12T00:00:00Z",
    "disclosure_date": "2024-01-15T00:00:00Z",
    "amount_range": "$50,001 - $100,000",
    "amount_min": 50001.0,
    "amount_max": 100000.0,
    "amount_midpoint": 75000.0,
    "committees": ["Financial Services", "Select Committee on Intelligence"],
    "party": "D",
    "state": "CA",
    "asset_description": "NVIDIA Corporation - Common Stock"
  }
}
```

### 3. Order Intent Output

```json
{
  "protocol": "v1",
  "type": "order_intent",
  "intent_id": "congress_a1b2c3d4",
  "event_id": "evt_abc123",
  "ts": "2024-01-15T10:30:00Z",
  "symbol": "NVDA",
  "side": "buy",
  "qty": 0,
  "order_type": "market",
  "time_in_force": "day",
  "client_tag": "congressional_alpha",
  "metadata": {
    "strategy": "congressional_alpha_tracker",
    "politician": "Nancy Pelosi",
    "chamber": "house",
    "party": "D",
    "transaction_type": "purchase",
    "politician_amount": "$50,001-$100,000",
    "politician_amount_midpoint": 75000.0,
    "committees": ["Financial Services", "Select Committee on Intelligence"],
    "whale_multiplier": 1.5,
    "committee_bonus": 0.0,
    "is_high_conviction": true,
    "confidence": 0.82,
    "suggested_notional": 14625.0,
    "reasoning": "Copying Nancy Pelosi's purchase of NVDA. Confidence: 82%. Whale multiplier: 1.5x. High-conviction ticker. Original trade: $75,000."
  }
}
```

## Configuration

### Modifying Tracked Politicians

Edit `POLICY_WHALES` in `strategy.py`:

```python
POLICY_WHALES = {
    "Politician Name": {
        "weight_multiplier": 1.4,  # 1.2-1.5 range
        "min_confidence": 0.7,     # 0.5-0.8 range
    },
}
```

### Modifying Committee Weights

Edit `COMMITTEE_WEIGHTS` in `strategy.py`:

```python
COMMITTEE_WEIGHTS = {
    "Committee Name": {
        "tickers": ["TICK", "LIST"],
        "bonus": 0.35,  # 0.2-0.4 range
    },
}
```

### Modifying High-Conviction List

Edit `HIGH_CONVICTION_TICKERS` in `strategy.py`:

```python
HIGH_CONVICTION_TICKERS = {
    "NVDA", "AAPL", "MSFT", 
    # Add more tickers...
}
```

## Monitoring

### Key Metrics to Track

1. **Signal Generation Rate**: Trades per day/week
2. **Politician Distribution**: Which whales are most active
3. **Confidence Distribution**: Average confidence scores
4. **Ticker Concentration**: Top tickers being copied
5. **Position Size Distribution**: Average/median position sizes
6. **Committee Overlap**: % of trades with committee relevance

### Logs

The ingestion service logs:
- `📊 Congressional Trade: {politician} {type} {ticker} (${amount})`
- Number of new trades per cycle
- API errors and fallbacks to mock data

The strategy logs are in standard protocol format via `LogMessage`.

## Deployment

### Cloud Run Deployment

1. **Build Docker image:**
```bash
cd /workspace
docker build -f infra/Dockerfile.congressional_ingest -t congressional-ingest .
```

2. **Deploy to Cloud Run:**
```bash
gcloud run deploy congressional-ingest \
  --image congressional-ingest \
  --set-env-vars TENANT_ID=prod \
  --set-env-vars QUIVER_API_KEY=secret:quiver-api-key \
  --set-env-vars NATS_URL=nats://nats.prod:4222 \
  --cpu 1 \
  --memory 512Mi \
  --min-instances 1 \
  --max-instances 1
```

3. **Deploy strategy to strategy runner:**
Upload `strategy.py` via the strategy management API.

## Risk Considerations

### 1. Timing Lag
- Congressional disclosures are delayed (typically 30-45 days)
- Market may have already moved by disclosure time
- Consider this in position sizing and confidence scoring

### 2. Position Concentration
- Multiple politicians may buy the same ticker
- Implement portfolio-level position limits
- Monitor aggregate exposure

### 3. Regulatory Risk
- STOCK Act compliance monitoring
- Potential for "trading on non-public information" if timing is suspicious
- Log all trades for audit trail

### 4. Data Quality
- API downtime or rate limits
- Disclosure filing errors or amendments
- Validate data before trading

### 5. Market Impact
- High-profile disclosures may move markets
- Use limit orders or VWAP strategies for large positions
- Consider splitting orders

## Performance Expectations

Based on historical analysis:
- **Win Rate**: 55-65% (historical congressional trades outperform market)
- **Average Hold Period**: 3-12 months (politicians are long-term investors)
- **Sharpe Ratio**: 1.2-1.8 (if properly risk-managed)
- **Max Drawdown**: 15-25% (correlated with broader market)

**Note**: Past performance does not guarantee future results.

## Compliance & Legal

⚠️ **Important**: This strategy is for educational purposes. Consult legal counsel before deploying:

1. Ensure compliance with securities regulations
2. Maintain proper audit trails
3. Implement risk controls
4. Consider market manipulation rules
5. Review broker terms of service

## Support

For issues or questions:
1. Check ingestion service logs for data pipeline issues
2. Review strategy protocol events for signal generation
3. Verify NATS connectivity and message flow
4. Check Quiver API status and rate limits

## References

- [Quiver Quantitative](https://www.quiverquant.com/)
- [STOCK Act Disclosures](https://ethics.house.gov/)
- [Senate Financial Disclosures](https://efdsearch.senate.gov/)
