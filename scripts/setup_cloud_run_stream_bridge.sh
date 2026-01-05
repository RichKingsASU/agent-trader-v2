#!/usr/bin/env bash
set -euo pipefail

# This script provides commands to build and deploy the Stream Bridge Cloud Run Service.
# It is intended to be run by a human who can provide the necessary environment variables.

# --- Configuration ---
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
IMAGE_TAG="gcr.io/${PROJECT_ID}/agenttrader-stream-bridge"

# --- IAM Roles Required ---
# The user running these commands needs the following roles:
# - Cloud Build Editor (roles/cloudbuild.builds.editor)
# - Cloud Run Admin (roles/run.admin)
# - IAM Service Account User (roles/iam.serviceAccountUser)

# --- Build the container image ---
echo "Building and pushing the container image: ${IMAGE_TAG}"
# gcloud builds submit --config infra/cloudbuild_stream_bridge.yaml .

# --- Deploy the Cloud Run Service ---
echo "Deploying the Cloud Run Service: agenttrader-stream-bridge"
# Note: You will need to have the following environment variables set in your shell
# when you run this command. These are the URLs and keys for the Developer Console.
# - DATABASE_URL
# - PRICE_STREAM_URL
# - OPTIONS_FLOW_URL
# - OPTIONS_FLOW_API_KEY
# - NEWS_STREAM_URL
# - NEWS_STREAM_API_KEY
# - ACCOUNT_UPDATES_URL
# - ACCOUNT_UPDATES_API_KEY

# The following is an example.
# gcloud run deploy agenttrader-stream-bridge \
#   --image "${IMAGE_TAG}" \
#   --region "${REGION}" \
#   --platform=managed \
#   --set-env-vars="DATABASE_URL=${DATABASE_URL}" \
#   --set-env-vars="PRICE_STREAM_URL=${PRICE_STREAM_URL}" \
#   --set-env-vars="OPTIONS_FLOW_URL=${OPTIONS_FLOW_URL}" \
#   --set-env-vars="OPTIONS_FLOW_API_KEY=${OPTIONS_FLOW_API_KEY}" \
#   --set-env-vars="NEWS_STREAM_URL=${NEWS_STREAM_URL}" \
#   --set-env-vars="NEWS_STREAM_API_KEY=${NEWS_STREAM_API_KEY}" \
#   --set-env-vars="ACCOUNT_UPDATES_URL=${ACCOUNT_UPDATES_URL}" \
#   --set-env-vars="ACCOUNT_UPDATES_API_KEY=${ACCOUNT_UPDATES_API_KEY}"
