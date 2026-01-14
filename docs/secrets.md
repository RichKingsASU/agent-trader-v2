# AgentTrader Secrets (GCP)

These secrets are required in Google Secret Manager.

| Secret Name | Purpose |
|------------|--------|
| DATABASE_URL_SECRET | PostgreSQL connection |
| APCA_API_KEY_ID_SECRET | Alpaca API key |
| APCA_API_SECRET_KEY_SECRET | Alpaca API secret |
| ALPACA_DATA_FEED_SECRET | iex |
| SYMS_SECRET | Symbols list |
| BACKFILL_DAYS_SECRET | Backfill window |

## Required IAM

Service account:
agenttrader-ingestor-sa@agenttrader-prod.iam.gserviceaccount.com

Role:
roles/secretmanager.secretAccessor
