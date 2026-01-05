#!/bin/bash
set -e

PROJECT_ID=$(gcloud config get-value project)
REGION="us-east1"
ZONE="us-east1-b"
INSTANCE_NAME="firecracker-sandbox-host"
# n2-standard-4 is required for Nested Virtualization performance
MACHINE_TYPE="n2-standard-4" 
SERVICE_ACCOUNT="agenttrader-runner@${PROJECT_ID}.iam.gserviceaccount.com"
TAGS="firecracker-host"

echo "🔹 Creating Firewall Rule for Internal NATS..."
# Allow traffic only from internal IPs (10.0.0.0/8) on port 4222
gcloud compute firewall-rules create allow-nats-internal \
     --network=default \
     --action=allow \
     --direction=INGRESS \
     --rules=tcp:4222 \
     --target-tags=${TAGS} \
     --source-ranges="10.0.0.0/8" \
     --description="Allow internal NATS traffic for Firecracker hosts" \
     --project=${PROJECT_ID} || echo "Rule exists, skipping."

echo "🔹 Provisioning VM '${INSTANCE_NAME}'..."
gcloud compute instances create ${INSTANCE_NAME} \
     --project=${PROJECT_ID} \
     --zone=${ZONE} \
     --machine-type=${MACHINE_TYPE} \
     --image-family="ubuntu-2204-lts" \
     --image-project="ubuntu-os-cloud" \
     --service-account=${SERVICE_ACCOUNT} \
     --scopes=cloud-platform \
     --tags=${TAGS} \
     --min-cpu-platform="Intel Cascade Lake" \
     --enable-nested-virtualization \
     --metadata-from-file=startup-script=./startup.sh

echo "✅ VM Created. It may take 2-3 minutes for the startup script to finish installing Firecracker."
