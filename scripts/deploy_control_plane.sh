#!/bin/bash
set -e

# Deployment Script for AgentTrader v2 Operator Control Plane
# Usage: ./scripts/deploy_control_plane.sh [GCP_PROJECT] [REGION]

PROJECT_ID=${1:-${GOOGLE_CLOUD_PROJECT}}
REGION=${2:-"us-central1"}
SERVICE_NAME="agenttrader-control-plane"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: GCP Project ID is required.${NC}"
    echo "Usage: ./scripts/deploy_control_plane.sh [GCP_PROJECT] [REGION]"
    exit 1
fi

echo -e "${GREEN}Deploying to Project: ${PROJECT_ID}, Region: ${REGION}${NC}"

# Check for required secrets (Prompt if missing env vars)
if [ -z "$GOOGLE_CLIENT_ID" ]; then
    read -p "Enter Google OAuth Client ID: " GOOGLE_CLIENT_ID
fi

if [ -z "$GOOGLE_CLIENT_SECRET" ]; then
    read -s -p "Enter Google OAuth Client Secret: " GOOGLE_CLIENT_SECRET
    echo ""
fi

if [ -z "$OPERATOR_EMAILS" ]; then
    read -p "Enter Operator Email Allowlist (comma-separated): " OPERATOR_EMAILS
fi

# Auto-fetch Session Secret from Secret Manager if available
if [ -z "$SESSION_SECRET" ]; then
    echo "Attempting to fetch SESSION_SECRET from Secret Manager..."
    if gcloud secrets describe SESSION_SECRET &>/dev/null; then
        SESSION_SECRET=$(gcloud secrets versions access latest --secret="SESSION_SECRET")
        echo "Loaded stable SESSION_SECRET."
    else
        SESSION_SECRET=$(openssl rand -hex 32)
        echo "Generated NEW temporary Session Secret."
    fi
fi

# Auto-fetch Alpaca Keys from Secret Manager if available
if [ -z "$APCA_API_KEY_ID" ]; then
    echo "Attempting to fetch APCA_API_KEY_ID from Secret Manager..."
    if gcloud secrets describe APCA_API_KEY_ID &>/dev/null; then
        APCA_API_KEY_ID=$(gcloud secrets versions access latest --secret="APCA_API_KEY_ID")
        echo "Loaded APCA_API_KEY_ID."
    else
        read -p "Enter Alpaca Paper API Key ID: " APCA_API_KEY_ID
    fi
fi

if [ -z "$APCA_API_SECRET_KEY" ]; then
    echo "Attempting to fetch APCA_API_SECRET_KEY from Secret Manager..."
    if gcloud secrets describe APCA_API_SECRET_KEY &>/dev/null; then
        APCA_API_SECRET_KEY=$(gcloud secrets versions access latest --secret="APCA_API_SECRET_KEY")
        echo "Loaded APCA_API_SECRET_KEY."
    else
        read -s -p "Enter Alpaca Paper Secret Key: " APCA_API_SECRET_KEY
        echo ""
    fi
fi

# Build & Push
echo -e "${GREEN}Step 1: Building Container Image...${NC}"
IMAGE_TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/agent-trader/${SERVICE_NAME}:latest"

docker build -t ${IMAGE_TAG} -f control_plane/Dockerfile .
docker push ${IMAGE_TAG}

# Deploy
echo -e "${GREEN}Step 2: Deploying to Cloud Run...${NC}"

gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_TAG} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}" \
  --set-env-vars "GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}" \
  --set-env-vars "GOOGLE_REDIRECT_URI=https://agenttrader-control-plane-7hddidcorq-uc.a.run.app/auth/callback" \
  --set-env-vars "OPERATOR_EMAILS=${OPERATOR_EMAILS}" \
  --set-env-vars "SESSION_SECRET=${SESSION_SECRET}" \
  --set-env-vars "FIRESTORE_PROJECT_ID=${PROJECT_ID}" \
  --set-env-vars "TRADING_MODE=shadow" \
  --set-env-vars "OPTIONS_EXECUTION_MODE=shadow" \
  --set-env-vars "EXECUTION_ENABLED=0" \
  --set-env-vars "EXECUTION_HALTED=0" \
  --set-env-vars "EXEC_GUARD_UNLOCK=0" \
  --set-env-vars "APCA_API_BASE_URL=https://paper-api.alpaca.markets" \
  --set-env-vars "APCA_API_KEY_ID=${APCA_API_KEY_ID}" \
  --set-env-vars "APCA_API_SECRET_KEY=${APCA_API_SECRET_KEY}" \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 1 \
  --min-instances 0 \
  --timeout 60s

echo -e "${GREEN}Deployment Complete!${NC}"
echo "Verify status at: $(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')/api/status"
