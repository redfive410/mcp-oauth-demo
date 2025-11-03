#!/bin/bash

set -e

# Configuration
PROJECT_ID=area51-954-dev-1
REGION=us-west1
SERVICE_NAME=${SERVICE_NAME:-"mcp-oauth-auth-server"}
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "🚀 Starting deployment to Cloud Run..."
echo "Project ID: ${PROJECT_ID}"
echo "Service Name: ${SERVICE_NAME}"
echo "Region: ${REGION}"

# Enable required APIs
echo "🔌 Enabling required GCP APIs..."
gcloud services enable firestore.googleapis.com --project=${PROJECT_ID}
gcloud services enable run.googleapis.com --project=${PROJECT_ID}
gcloud services enable containerregistry.googleapis.com --project=${PROJECT_ID}

# Check if Firestore database exists, create if needed
echo "📊 Checking Firestore database..."
if ! gcloud firestore databases describe --project=${PROJECT_ID} 2>/dev/null; then
    echo "Creating Firestore database in Native mode..."
    gcloud firestore databases create --location=${REGION} --type=firestore-native --project=${PROJECT_ID}
fi

# Authenticate Docker with gcloud
echo "🔐 Configuring Docker authentication..."
gcloud auth configure-docker gcr.io --quiet

# Build the Docker image for linux/amd64 platform
echo "📦 Building Docker image..."
docker build --platform linux/amd64 -t ${IMAGE_NAME} .

# Push the image to Google Container Registry
echo "⬆️ Pushing image to Container Registry..."
docker push ${IMAGE_NAME}


# Check if service already exists to get the URL
echo "🔍 Checking if service already exists..."
EXISTING_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --format="value(status.url)" 2>/dev/null || echo "")

if [ -z "$EXISTING_URL" ]; then
    # First deployment - use a temporary HTTPS placeholder
    echo "📦 First deployment - using temporary HTTPS URL..."
    TEMP_ISSUER_URL="https://temp.example.com"
else
    # Service exists - use the existing URL
    echo "♻️ Updating existing service with URL: ${EXISTING_URL}"
    TEMP_ISSUER_URL="${EXISTING_URL}"
fi

# Deploy to Cloud Run with Firestore configuration
echo "🌟 Deploying to Cloud Run with Firestore..."
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME} \
    --platform managed \
    --region ${REGION} \
    --port 9000 \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 10 \
    --timeout 300 \
    --allow-unauthenticated \
    --set-env-vars GCP_PROJECT_ID=${PROJECT_ID},ISSUER_URL=${TEMP_ISSUER_URL} \
    --project ${PROJECT_ID}

# Get the actual service URL
echo "🔍 Getting actual service URL..."
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --format="value(status.url)")

# If this was a first deployment with temp URL, update with the real URL
if [ "$TEMP_ISSUER_URL" = "https://temp.example.com" ]; then
    echo "📝 Updating service with correct ISSUER_URL: ${SERVICE_URL}"
    gcloud run services update ${SERVICE_NAME} \
        --region ${REGION} \
        --project ${PROJECT_ID} \
        --set-env-vars GCP_PROJECT_ID=${PROJECT_ID},ISSUER_URL=${SERVICE_URL}
fi

echo "✅ Deployment complete!"
echo "🔗 Service URL: ${SERVICE_URL}"
echo ""
echo "📊 Firestore Collections:"
echo "  - oauth_clients: OAuth client registrations"
echo "  - oauth_tokens: Access tokens"
echo "  - auth_codes: Authorization codes"
echo "  - oauth_state: OAuth flow state"
echo "  - user_data: User session data"
echo ""
echo "🧹 Cleanup endpoint: POST ${SERVICE_URL}/cleanup"
echo "❤️ Health check: GET ${SERVICE_URL}/health"
echo ""
echo "Note: CloudRun service account has automatic Firestore permissions."
echo "Data persists across instance restarts!"
