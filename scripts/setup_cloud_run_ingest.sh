#!/usr/bin/env bash
set -euo pipefail

# This script provides commands to build and deploy the Alpaca ingest Cloud Run Job.
# It is intended to be run by a human who can provide the necessary environment variables.

# --- Configuration ---
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
IMAGE_TAG="gcr.io/${PROJECT_ID}/agenttrader-alpaca-ingest"

# --- IAM Roles Required ---
# The user running these commands needs the following roles:
# - Cloud Build Editor (roles/cloudbuild.builds.editor)
# - Cloud Run Admin (roles/run.admin)
# - IAM Service Account User (roles/iam.serviceAccountUser)

# --- Build the container image ---
echo "Building and pushing the container image: ${IMAGE_TAG}"
# gcloud builds submit --config infra/cloudbuild_ingest.yaml .

# --- Deploy the Cloud Run Job ---
echo "Deploying the Cloud Run Job: alpaca-minute-ingest"
# Note: You will need to have the following environment variables set in your shell
# when you run this command:
# - DATABASE_URL
# - ALPACA_KEY_ID
# - ALPACA_SECRET_KEY
# - ALPACA_SYMBOLS
# - ALPACA_DATA_HOST
# - ALPACA_TRADING_HOST
# - ALPACA_BACKFILL_DAYS

# The following is an example. You may need to adjust the values.
# gcloud run jobs create alpaca-minute-ingest \
#   --image "${IMAGE_TAG}" \
#   --region "${REGION}" \
#   --max-retries=3 \
#   --tasks=1 \
#   --set-env-vars="DATABASE_URL=${DATABASE_URL}" \
#   --set-env-vars="ALPACA_KEY_ID=${ALPACA_KEY_ID}" \
#   --set-env-vars="ALPACA_SECRET_KEY=${ALPACA_SECRET_KEY}" \
#   --set-env-vars="ALPACA_SYMBOLS=${ALPACA_SYMBOLS}" \
#   --set-env-vars="ALPACA_DATA_HOST=${ALPACA_DATA_HOST}" \
#   --set-env-vars="ALPACA_TRADING_HOST=${ALPACA_TRADING_HOST}" \
#   --set-env-vars="ALPACA_BACKFILL_DAYS=${ALPACA_BACKFILL_DAYS}"
