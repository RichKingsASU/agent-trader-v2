# Template for Cloud Scheduler Job to trigger Cloud Run Job
# Replace <PROJECT_ID>, <REGION>, <SERVICE_ACCOUNT_EMAIL>, and <CLOUD_RUN_JOB_URI> (see notes below).

PROJECT_ID="$(gcloud config get-value project)"
REGION="us-central1" # Or the region where your Cloud Run Job is deployed
SERVICE_ACCOUNT_EMAIL="12638678866-compute@developer.gserviceaccount.com" # Default compute service account. Ensure it has roles/run.invoker and roles/run.admin

# NOTE: Directly triggering a Cloud Run Job from Cloud Scheduler via HTTP requires an intermediary. 
# The simplest direct way to trigger a Cloud Run Job from Scheduler is via Pub/Sub.
# However, the prompt specifically asks for `gcloud scheduler jobs create http`.
# The URI below is a placeholder. You would typically create a Cloud Run Service that listens for HTTP 
# requests and then triggers the Cloud Run Job via its API.
# For a direct API trigger, you'd call the Cloud Run Admin API endpoint.

# Placeholder URI: This needs to be replaced with the actual endpoint that triggers your Cloud Run Job.
# If you create a Cloud Run Service to act as an intermediary, this would be the service's URL.
# For a direct API call (more complex), you'd point to the Cloud Run Admin API for job execution.
CLOUD_RUN_JOB_URI="https://<YOUR_CLOUD_RUN_SERVICE_OR_API_ENDPOINT>"

gcloud scheduler jobs create http alpaca-minute-ingest-scheduler \
  --schedule="*/5 * * * 1-5" \
  --uri="${CLOUD_RUN_JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --headers="Content-Type=application/json" \
  --message-body='{ "jobName": "alpaca-minute-ingest" }' 
