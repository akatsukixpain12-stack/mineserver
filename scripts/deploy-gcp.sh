#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project ID}"
: "${GOOGLE_CLIENT_ID:?Set GOOGLE_CLIENT_ID to your Google OAuth Web client ID}"

REGION="${REGION:-asia-south1}"
ZONE="${ZONE:-asia-south1-a}"
REPO="mineserver"
SERVICE="mineserver-control"
SA="mineserver-control@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/control:latest"
BACKUP_BUCKET="${BACKUP_BUCKET:-mineserver-${PROJECT_ID}-backups}"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com compute.googleapis.com firestore.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com storage.googleapis.com

if ! gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION"
fi

if ! gcloud iam service-accounts describe "$SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create mineserver-control --display-name="Mineserver Cloud Run control plane"
fi

for ROLE in roles/compute.instanceAdmin.v1 roles/compute.networkAdmin roles/datastore.user; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role="$ROLE" --quiet >/dev/null
done

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$COMPUTE_SA" --member="serviceAccount:$SA" --role="roles/iam.serviceAccountUser" --quiet >/dev/null

if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --type=firestore-native
fi

if ! gcloud storage buckets describe "gs://${BACKUP_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BACKUP_BUCKET}" --location="$REGION" --uniform-bucket-level-access
fi
gcloud storage buckets add-iam-policy-binding "gs://${BACKUP_BUCKET}" \
  --member="serviceAccount:${SA}" \
  --role="roles/storage.objectAdmin" --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BACKUP_BUCKET}" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/storage.objectAdmin" --quiet >/dev/null

echo "Building real Mineserver image..."
gcloud builds submit . --tag "$IMAGE"

echo "Deploying real control plane..."
gcloud run deploy "$SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$SA" \
  --port=8080 \
  --timeout=3600 \
  --min=1 \
  --max=1 \
  --session-affinity \
  --allow-unauthenticated \
  --set-env-vars="APP_NAME=Mineserver,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID,COMPUTE_ZONE=$ZONE,COMPUTE_NETWORK=default,MINECRAFT_MACHINE_TYPE=e2-small,MINECRAFT_DISK_GB=20,BACKUP_BUCKET=$BACKUP_BUCKET,CORS_ORIGINS=http://localhost:8080"

CONTROL_URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format="value(status.url)")"

gcloud run services update "$SERVICE" \
  --region="$REGION" \
  --update-env-vars="CONTROL_URL=$CONTROL_URL,CORS_ORIGINS=$CONTROL_URL"

echo
echo "Mineserver deployed:"
echo "$CONTROL_URL"
echo "Backup bucket:"
echo "gs://${BACKUP_BUCKET}"
echo
echo "IMPORTANT: add this exact URL to the Google OAuth client Authorized JavaScript origins."
