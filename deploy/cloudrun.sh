#!/usr/bin/env bash
# deploy/cloudrun.sh — reproducible Cloud Run deployment for MedSentry.
#
# Participants are not required to deploy live for judging (per the
# competition rules) — this script is provided so the "Deployability"
# concept is real and reproducible, not just claimed. No secrets are
# embedded: GOOGLE_API_KEY / MEDSENTRY_SECRET_KEY are pushed to Secret
# Manager and mounted as env vars at deploy time, never baked into the image.
#
# Usage:
#   export GCP_PROJECT=your-project-id
#   export GCP_REGION=asia-south1
#   ./deploy/cloudrun.sh

set -euo pipefail

: "${GCP_PROJECT:?Set GCP_PROJECT first}"
: "${GCP_REGION:=asia-south1}"
SERVICE_NAME="medsentry"

echo "Building and pushing container image..."
gcloud builds submit --tag "gcr.io/${GCP_PROJECT}/${SERVICE_NAME}" .

echo "Deploying to Cloud Run in demo mode (no secrets required)..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "gcr.io/${GCP_PROJECT}/${SERVICE_NAME}" \
  --project "${GCP_PROJECT}" \
  --region "${GCP_REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "MEDSENTRY_DEMO_MODE=true" \
  --port 8080

cat <<'EOF'

To switch this service to live Gemini mode afterwards, WITHOUT ever putting
a key in source control:

  gcloud secrets create medsentry-google-api-key --data-file=- <<< "$GOOGLE_API_KEY"
  gcloud secrets create medsentry-secret-key --data-file=- <<< "$MEDSENTRY_SECRET_KEY"

  gcloud run services update medsentry \
    --update-secrets=GOOGLE_API_KEY=medsentry-google-api-key:latest \
    --update-secrets=MEDSENTRY_SECRET_KEY=medsentry-secret-key:latest \
    --update-env-vars=MEDSENTRY_DEMO_MODE=false
EOF
