#!/usr/bin/env bash
set -euo pipefail

# This script provides a template for creating a Cloud Scheduler job to trigger the
# Alpaca ingest Cloud Run Job.

# --- Configuration ---
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"

# --- IAM Roles Required ---
# The service account used by the scheduler needs the following roles:
# - Cloud Run Invoker (roles/run.invoker)
# - Cloud Run Admin (roles/run.admin) - to execute jobs

# You may need to create a dedicated service account for this purpose.
# For example:
# gcloud iam service-accounts create alpaca-ingest-scheduler --display-name "Alpaca Ingest Scheduler"
#
# And then grant it the necessary permissions on the project and Cloud Run Job.

# --- Create the Cloud Scheduler Job ---
echo "Creating the Cloud Scheduler Job: alpaca-minute-ingest-scheduler"
# Note: Directly triggering a Cloud Run Job from Cloud Scheduler via HTTP requires an
# intermediary. The simplest direct way to trigger a Cloud Run Job from Scheduler is
# via Pub/Sub. The following is a template for an HTTP trigger, which would require
# a Cloud Run Service to act as an intermediary.

# The URI below is a placeholder. You would typically create a Cloud Run Service that listens for HTTP
# requests and then triggers the Cloud Run Job via its API.
# For a direct API call (more complex), you'd point to the Cloud Run Admin API for job execution.
# CLOUD_RUN_JOB_URI="https://<YOUR_CLOUD_RUN_SERVICE_OR_API_ENDPOINT>"

# gcloud scheduler jobs create http alpaca-minute-ingest-scheduler \
#   --schedule="*/5 * * * 1-5" \
#   --uri="${CLOUD_RUN_JOB_URI}" \
#   --http-method=POST \
#   --oauth-service-account-email="<YOUR_SERVICE_ACCOUNT_EMAIL>" \
#   --location="${REGION}" \
#   --project="${PROJECT_ID}" \
#   --headers="Content-Type=application/json" \
#   --message-body='{ "jobName": "alpaca-minute-ingest" }'
