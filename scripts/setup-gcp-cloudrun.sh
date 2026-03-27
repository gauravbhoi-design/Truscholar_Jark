#!/bin/bash
# ─── GCP Cloud Run + Cloud SQL Setup ─────────────────────────────────────
# Run this ONCE to create all infrastructure.
# Project: project-tai-aiinterviewer
# ─────────────────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT_ID="project-tai-aiinterviewer"
REGION="us-central1"
SA_EMAIL="claude-vscode-key@project-tai-aiinterviewer.iam.gserviceaccount.com"

DB_INSTANCE="copilot-db"
DB_NAME="devops_copilot"
DB_USER="copilot"
DB_PASSWORD="$(openssl rand -base64 24)"

REDIS_INSTANCE="copilot-redis"

echo "============================================================"
echo "  TruScholar Co-Pilot — GCP Infrastructure Setup"
echo "  Project: $PROJECT_ID | Region: $REGION"
echo "============================================================"
echo ""

gcloud config set project "$PROJECT_ID"

# ─── 1. Enable APIs ────────────────────────────────────────────────────
echo ">>> Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com \
  vpcaccess.googleapis.com \
  --quiet

# ─── 2. Artifact Registry ─────────────────────────────────────────────
echo ">>> Creating Artifact Registry..."
gcloud artifacts repositories create copilot \
  --repository-format=docker \
  --location="$REGION" \
  2>/dev/null || echo "  Already exists"

# ─── 3. Grant SA roles ────────────────────────────────────────────────
echo ">>> Granting roles to service account..."
for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/secretmanager.secretAccessor \
  roles/iam.serviceAccountUser \
  roles/cloudsql.client \
  roles/redis.editor \
  roles/vpcaccess.user; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE" --quiet 2>/dev/null
done

# ─── 4. Create Cloud SQL PostgreSQL ───────────────────────────────────
echo ""
echo ">>> Creating Cloud SQL PostgreSQL instance..."
echo "  (This takes 5-10 minutes)"

# Check if instance exists
if gcloud sql instances describe "$DB_INSTANCE" --quiet 2>/dev/null; then
  echo "  Instance $DB_INSTANCE already exists"
else
  gcloud sql instances create "$DB_INSTANCE" \
    --database-version=POSTGRES_16 \
    --tier=db-f1-micro \
    --region="$REGION" \
    --storage-size=10GB \
    --storage-auto-increase \
    --availability-type=zonal \
    --no-assign-ip \
    --network=default \
    --quiet

  echo "  Instance created!"
fi

# Create database
echo ">>> Creating database '$DB_NAME'..."
gcloud sql databases create "$DB_NAME" --instance="$DB_INSTANCE" 2>/dev/null || echo "  Database already exists"

# Create user
echo ">>> Creating database user '$DB_USER'..."
gcloud sql users create "$DB_USER" \
  --instance="$DB_INSTANCE" \
  --password="$DB_PASSWORD" \
  2>/dev/null || echo "  User already exists (password NOT changed)"

# Get connection name
DB_CONNECTION_NAME=$(gcloud sql instances describe "$DB_INSTANCE" --format='value(connectionName)')
echo "  Connection name: $DB_CONNECTION_NAME"

# ─── 5. Create Memorystore Redis ──────────────────────────────────────
echo ""
echo ">>> Creating Memorystore Redis instance..."

if gcloud redis instances describe "$REDIS_INSTANCE" --region="$REGION" --quiet 2>/dev/null; then
  echo "  Redis instance already exists"
else
  gcloud redis instances create "$REDIS_INSTANCE" \
    --size=1 \
    --region="$REGION" \
    --redis-version=redis_7_0 \
    --tier=basic \
    --quiet

  echo "  Redis instance created!"
fi

REDIS_HOST=$(gcloud redis instances describe "$REDIS_INSTANCE" --region="$REGION" --format='value(host)' 2>/dev/null || echo "")
REDIS_PORT=$(gcloud redis instances describe "$REDIS_INSTANCE" --region="$REGION" --format='value(port)' 2>/dev/null || echo "6379")

# ─── 6. Create VPC Connector (Cloud Run → Cloud SQL/Redis) ───────────
echo ""
echo ">>> Creating Serverless VPC Connector..."
gcloud compute networks vpc-access connectors create copilot-vpc \
  --region="$REGION" \
  --range="10.8.0.0/28" \
  --quiet 2>/dev/null || echo "  VPC connector already exists"

echo ""
echo "============================================================"
echo "  INFRASTRUCTURE CREATED!"
echo "============================================================"
echo ""
echo "Cloud SQL instance:  $DB_INSTANCE"
echo "Connection name:     $DB_CONNECTION_NAME"
echo "Database:            $DB_NAME"
echo "DB User:             $DB_USER"
echo "DB Password:         $DB_PASSWORD"
echo ""
if [ -n "$REDIS_HOST" ]; then
echo "Redis Host:          $REDIS_HOST"
echo "Redis Port:          $REDIS_PORT"
fi
echo ""
echo "============================================================"
echo "  ADD THESE GITHUB SECRETS"
echo "============================================================"
echo ""
echo "Go to: https://github.com/gauravbhoi-design/Truscholar_Jark/settings/secrets/actions"
echo ""
echo "Secret Name                    | Value"
echo "-------------------------------|----------------------------------------"
echo "GCP_SA_KEY                     | <paste project-tai-aiinterviewer SA JSON>"
echo "GCP_VERTEX_SA_KEY              | <paste project-pallavi-tarke SA JSON>"
echo "API_URL                        | https://copilot-api (update after 1st deploy)"
echo "POSTGRES_CONNECTION_NAME       | $DB_CONNECTION_NAME"
echo "POSTGRES_DB                    | $DB_NAME"
echo "POSTGRES_USER                  | $DB_USER"
echo "POSTGRES_PASSWORD              | $DB_PASSWORD"
echo "REDIS_HOST                     | $REDIS_HOST"
echo "REDIS_PORT                     | $REDIS_PORT"
echo "APP_GITHUB_CLIENT_ID           | <your GitHub OAuth Client ID>"
echo "APP_GITHUB_CLIENT_SECRET       | <your GitHub OAuth Client Secret>"
echo "APP_GITHUB_TOKEN               | <your GitHub PAT>"
echo "JWT_SECRET                     | $(openssl rand -hex 32)"
echo "GCP_OAUTH_CLIENT_ID            | <your GCP OAuth Client ID>"
echo "GCP_OAUTH_CLIENT_SECRET        | <your GCP OAuth Client Secret>"
echo "CREDENTIALS_ENCRYPTION_KEY     | $(openssl rand -base64 32)"
echo "ZOHO_CLIENT_ID                 | <your Zoho Client ID>"
echo "ZOHO_CLIENT_SECRET             | <your Zoho Client Secret>"
echo ""
echo "SAVE THE DB PASSWORD ABOVE — it won't be shown again!"
echo "============================================================"
