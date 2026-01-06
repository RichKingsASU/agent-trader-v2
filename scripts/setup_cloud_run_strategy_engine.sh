#!/bin/bash

# This script provides commands to build and deploy the
# AgentTrader Strategy Engine to Google Cloud Run as a Job.

# --- Configuration ---
PROJECT_ID=$(gcloud config get-value project)
JOB_NAME="strategy-engine-job"
SCHEDULER_NAME="strategy-engine-scheduler"
REGION="us-central1"
IMAGE_URI="gcr.io/${PROJECT_ID}/${JOB_NAME}"
SERVICE_ACCOUNT="my-run-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Marketdata health contract (override as needed for your environment)
MARKETDATA_HEALTH_URL="${MARKETDATA_HEALTH_URL:-http://127.0.0.1:8080/healthz}"
MARKETDATA_MAX_AGE_SECONDS="${MARKETDATA_MAX_AGE_SECONDS:-60}"

# --- IAM policy bindings (idempotent) ---
echo "Ensuring IAM policy bindings..."
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:${SERVICE_ACCOUNT}" --role="roles/run.invoker" --condition=None > /dev/null
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:${SERVICE_ACCOUNT}" --role="roles/secretmanager.secretAccessor" --condition=None > /dev/null
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:${SERVICE_ACCOUNT}" --role="roles/run.admin" --condition=None > /dev/null


# --- Build and Push Container Image ---
echo "Building and pushing container image..."
gcloud builds submit --config infra/cloudbuild_strategy_engine.yaml . --substitutions=_JOB_NAME=$JOB_NAME

# --- Deploy to Cloud Run as a Job ---
echo "Deploying to Cloud Run as a Job..."
gcloud run jobs deploy "${JOB_NAME}" \
  --image "${IMAGE_URI}" \
  --region "${REGION}" \
  --service-account "${SERVICE_ACCOUNT}" \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest" \
  --set-env-vars="STRATEGY_NAME=naive_flow_trend,STRATEGY_SYMBOLS=SPY,IWM,QQQ,STRATEGY_BAR_LOOKBACK_MINUTES=15,STRATEGY_FLOW_LOOKBACK_MINUTES=15,MARKETDATA_HEALTH_URL=${MARKETDATA_HEALTH_URL},MARKETDATA_MAX_AGE_SECONDS=${MARKETDATA_MAX_AGE_SECONDS}" \
  --command "python" \
  --args "-m" \
  --args "backend.strategy_engine.driver" \
  --args "--execute"

# --- Delete Existing Cloud Scheduler Job (if exists) ---
echo "Deleting existing Cloud Scheduler Job to ensure clean state..."
gcloud scheduler jobs delete "${SCHEDULER_NAME}" --location="${REGION}" --quiet

# --- Create Cloud Scheduler Job ---
echo "Creating Cloud Scheduler Job..."
gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
  --schedule "*/5 13-20 * * 1-5" \
  --location "${REGION}" \
  --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method "POST" \
  --oidc-service-account-email "${SERVICE_ACCOUNT}"

# --- Manually trigger the Cloud Run job ---
echo "Manually triggering the Cloud Run job..."
gcloud run jobs execute "${JOB_NAME}" --region="${REGION}"

echo "Deployment script finished."