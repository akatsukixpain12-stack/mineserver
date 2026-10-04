#!/usr/bin/env bash
set -euo pipefail
if [ -z "$PROJECT_ID" ]; then echo "Set PROJECT_ID"; exit 1; fi
REGION="asia-south1"; REPO="minehub"; SERVICE="minehub-control"
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com compute.googleapis.com firestore.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then gcloud firestore databases create --location="$REGION" --type=firestore-native; fi
if ! gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1; then gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION"; fi
gcloud builds submit backend --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/control:latest"
echo "Build complete. Deploy with Cloud Run --timeout=3600 --session-affinity."
