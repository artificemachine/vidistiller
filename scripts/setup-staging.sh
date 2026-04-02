#!/usr/bin/env bash
# setup-staging.sh — Provision a staging environment on the current LXC host.
#
# Staging runs alongside production on offset ports:
#   API:      http://<host>:8001
#   Frontend: http://<host>:3001
#   pgAdmin:  http://<host>:5051
#
# For a fully isolated staging LXC, create a second container on Proxmox
# and run this script there instead.
#
# Usage:
#   bash scripts/setup-staging.sh [--branch staging] [--host youtube-model-feeder-lxc]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="${BRANCH:-staging}"
LXC_HOST="${LXC_HOST:-youtube-model-feeder-lxc}"
REMOTE_USER="${REMOTE_USER:-appuser}"
LXC_PROJECT_DIR="${LXC_PROJECT_DIR:-/home/${REMOTE_USER}/youtube-model-feeder}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "\n${BLUE}=== Staging Environment Setup ===${NC}\n"
echo -e "Host:    $LXC_HOST"
echo -e "Branch:  $BRANCH"
echo -e "Dir:     $LXC_PROJECT_DIR\n"

# ── 1. Ensure staging branch exists ─────────────────────────────────────────
cd "$ROOT"
if ! git show-ref --quiet "refs/heads/$BRANCH"; then
  echo -e "${YELLOW}Creating branch '$BRANCH' from main...${NC}"
  git checkout -b "$BRANCH"
  git push -u origin "$BRANCH"
  git checkout main
  echo -e "${GREEN}Branch '$BRANCH' created and pushed.${NC}"
else
  echo -e "${GREEN}Branch '$BRANCH' already exists.${NC}"
fi

# ── 2. SSH pre-flight ────────────────────────────────────────────────────────
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$LXC_HOST" true 2>/dev/null; then
  echo -e "${RED}Cannot reach $LXC_HOST. Check SSH config.${NC}"
  exit 1
fi

# ── 3. Ensure .env.staging exists on remote ──────────────────────────────────
ssh "$LXC_HOST" bash -s -- "$LXC_PROJECT_DIR" "$BRANCH" << 'REMOTE'
  set -e
  DIR="$1"; BRANCH="$2"
  cd "$DIR"

  if [ ! -f .env.staging ]; then
    echo "Creating .env.staging from .env..."
    cp .env .env.staging
    # Offset DB port so staging postgres gets its own port binding
    sed -i 's/^DB_PORT=.*/DB_PORT=5433/' .env.staging
    sed -i 's/^REDIS_PORT=.*/REDIS_PORT=6380/' .env.staging
    sed -i 's/^API_PORT=.*/API_PORT=8001/' .env.staging
    sed -i 's/^FRONTEND_PORT=.*/FRONTEND_PORT=3001/' .env.staging
    sed -i 's/^PGADMIN_PORT=.*/PGADMIN_PORT=5051/' .env.staging
    sed -i 's/^ENVIRONMENT=.*/ENVIRONMENT=staging/' .env.staging
    echo "Created .env.staging — review and customise before starting staging."
  else
    echo ".env.staging already exists, skipping."
  fi

  echo "Checking out staging branch..."
  git fetch origin
  git checkout "$BRANCH" || git checkout -b "$BRANCH" origin/"$BRANCH"

  echo "Building staging images..."
  docker compose -f docker-compose.yml -f docker-compose.staging.yml \
    --env-file .env.staging build

  echo "Starting staging services..."
  docker compose -f docker-compose.yml -f docker-compose.staging.yml \
    --env-file .env.staging up -d

  sleep 8
  echo "Running staging migrations..."
  docker compose -f docker-compose.yml -f docker-compose.staging.yml \
    --env-file .env.staging exec -T api alembic upgrade head

  sleep 10
  curl -sf http://localhost:8001/health && echo "Staging API healthy."
REMOTE

LXC_IP=$(ssh "$LXC_HOST" "hostname -I 2>/dev/null | awk '{print \$1}'" || echo "$LXC_HOST")

echo ""
echo -e "${GREEN}=== Staging ready ===${NC}"
echo ""
echo "  Frontend: http://$LXC_IP:3001"
echo "  API Docs: http://$LXC_IP:8001/docs"
echo "  pgAdmin:  http://$LXC_IP:5051"
echo ""
echo "Deploy staging branch:"
echo "  git checkout staging && git merge main && git push"
echo "  or: push to the 'staging' branch to trigger CI auto-deploy"
echo ""
echo "Tear down staging:"
echo "  ssh $LXC_HOST 'cd $LXC_PROJECT_DIR && docker compose -f docker-compose.yml -f docker-compose.staging.yml --env-file .env.staging down -v'"
echo ""
