# Operator Control Plane - Deployment Guide

## Prerequisites

1. **Google Cloud Project** with:
   - Cloud Run API enabled
   - Artifact Registry API enabled
   - Firestore database created
   
2. **Google OAuth Credentials**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   - Create OAuth 2.0 Client ID (Web application)
   - Add authorized redirect URI: `https://YOUR_DOMAIN/auth/callback`
   - Save Client ID and Client Secret

3. **Operator Email Allowlist**:
   - List of authorized operator emails (comma-separated)

## Step 1: Build and Push Docker Image

The Dockerfile now uses a **multi-stage build**:
1.  **Frontend Builder**: Uses Node.js to build the React UI.
2.  **Runtime**: Uses Python to serve the API + Static UI files.

```bash
# Set your project ID
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export SERVICE_NAME=operator-control-plane

# Build the image (This will invoke npm install & npm run build inside Docker)
cd /home/richkings/Documents/Agent-Trader_V2/agent-trader-v2
docker build -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/agent-trader/${SERVICE_NAME}:latest -f control_plane/Dockerfile .

# Push to Artifact Registry
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/agent-trader/${SERVICE_NAME}:latest
```

## Step 2: Deploy to Cloud Run

```bash
gcloud run deploy ${SERVICE_NAME} \
  --image ${REGION}-docker.pkg.dev/${PROJECT_ID}/agent-trader/${SERVICE_NAME}:latest \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLIENT_ID=YOUR_CLIENT_ID" \
  --set-env-vars "GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET" \
  --set-env-vars "GOOGLE_REDIRECT_URI=https://YOUR_DOMAIN/auth/callback" \
  --set-env-vars "OPERATOR_EMAILS=operator1@example.com,operator2@example.com" \
  --set-env-vars "SESSION_SECRET=$(openssl rand -hex 32)" \
  --set-env-vars "FIRESTORE_PROJECT_ID=${PROJECT_ID}" \
  --set-env-vars "TRADING_MODE=shadow" \
  --set-env-vars "OPTIONS_EXECUTION_MODE=shadow" \
  --set-env-vars "EXECUTION_ENABLED=0" \
  --set-env-vars "EXECUTION_HALTED=0" \
  --set-env-vars "EXEC_GUARD_UNLOCK=0" \
  --set-env-vars "APCA_API_BASE_URL=https://paper-api.alpaca.markets" \
  --set-env-vars "APCA_API_KEY_ID=YOUR_PAPER_KEY" \
  --set-env-vars "APCA_API_SECRET_KEY=YOUR_PAPER_SECRET" \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 1 \
  --min-instances 0 \
  --timeout 60s
```

## Step 3: Configure Custom Domain

```bash
# Map custom domain to Cloud Run service
gcloud run domain-mappings create \
  --service ${SERVICE_NAME} \
  --domain operator.yourdomain.com \
  --region ${REGION}

# Follow instructions to update DNS records
```

## Step 4: Enable Execution (When Ready)

**CRITICAL**: These steps enable PAPER TRADING execution.

```bash
# Update service with execution flags
gcloud run services update ${SERVICE_NAME} \
  --region ${REGION} \
  --update-env-vars "TRADING_MODE=paper" \
  --update-env-vars "OPTIONS_EXECUTION_MODE=paper" \
  --update-env-vars "EXECUTION_ENABLED=1" \
  --update-env-vars "EXEC_GUARD_UNLOCK=1" \
  --update-env-vars "EXECUTION_CONFIRM_TOKEN=$(openssl rand -hex 16)"

# Save the EXECUTION_CONFIRM_TOKEN - you'll need it to submit intents
```

## Step 5: Verify Deployment

```bash
# Get service URL
gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)'

# Test health endpoint
curl https://YOUR_SERVICE_URL/health

# Test status endpoint (requires OAuth)
# Visit https://YOUR_SERVICE_URL/auth/login in browser
```

## Security Checklist

- [ ] OAuth credentials configured
- [ ] Operator emails allowlist set
- [ ] Session secret is random and secure
- [ ] HTTPS only (Cloud Run enforces this)
- [ ] Alpaca API URL is paper-api.alpaca.markets
- [ ] Execution flags default to safe values
- [ ] Max instances set to 1 (prevents concurrent executions)
- [ ] Custom domain configured with SSL

## Operator Workflow

1. **Login**: Navigate to `https://YOUR_DOMAIN/auth/login`
2. **Check Status**: GET `/api/status` to verify system state
3. **Enable Execution**: Update environment variables (see Step 4)
4. **Submit Intent**: POST `/api/intent/submit` with confirmation token
5. **System Auto-Locks**: `EXECUTION_HALTED` set to 1 immediately
6. **Disable Execution**: Set `EXECUTION_HALTED=0` and clear flags

## Monitoring

```bash
# View logs
gcloud run services logs read ${SERVICE_NAME} --region ${REGION} --limit 100

# Watch logs in real-time
gcloud run services logs tail ${SERVICE_NAME} --region ${REGION}
```

## Rollback

```bash
# List revisions
gcloud run revisions list --service ${SERVICE_NAME} --region ${REGION}

# Rollback to previous revision
gcloud run services update-traffic ${SERVICE_NAME} \
  --region ${REGION} \
  --to-revisions REVISION_NAME=100
```

## Troubleshooting

### OAuth Not Working
- Verify `GOOGLE_REDIRECT_URI` matches OAuth console
- Check authorized redirect URIs in Google Cloud Console
- Ensure domain is using HTTPS

### Execution Blocked
- Check `/api/status` for current safety flags
- Verify all 5 execution requirements are met
- Check Cloud Run logs for detailed error messages

### Firestore Connection Failed
- Verify `FIRESTORE_PROJECT_ID` is correct
- Check Cloud Run service account has Firestore permissions
- Enable Firestore API in GCP project
