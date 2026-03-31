#!/bin/bash
set -e

echo "🔧 Setting up worker environment..."

# ── GCP Authentication ────────────────────────────────────────
if [ -n "$GCP_SERVICE_ACCOUNT_KEY" ]; then
    echo "$GCP_SERVICE_ACCOUNT_KEY" | base64 -d > /tmp/gcp-key.json
    export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-key.json
    gcloud auth activate-service-account --key-file=/tmp/gcp-key.json 2>/dev/null || true
    [ -n "$GCP_PROJECT_ID" ] && gcloud config set project "$GCP_PROJECT_ID" 2>/dev/null || true
    echo "✅ GCP authenticated"
elif [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    gcloud auth activate-service-account --key-file="$GOOGLE_APPLICATION_CREDENTIALS" 2>/dev/null || true
    [ -n "$GCP_PROJECT_ID" ] && gcloud config set project "$GCP_PROJECT_ID" 2>/dev/null || true
    echo "✅ GCP authenticated via mounted key"
fi

# ── GitHub Authentication ─────────────────────────────────────
if [ -n "$GITHUB_TOKEN" ]; then
    echo "$GITHUB_TOKEN" | gh auth login --with-token 2>/dev/null || true
    git config --global credential.helper '!f() { echo "password=$GITHUB_TOKEN"; }; f'
    echo "✅ GitHub authenticated"
fi

# ── Git Config ────────────────────────────────────────────────
git config --global user.email "ai-agent@devops.local"
git config --global user.name "AI DevOps Agent"
git config --global init.defaultBranch main

echo "🚀 Worker ready"

exec "$@"
