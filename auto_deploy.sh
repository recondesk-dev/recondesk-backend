#!/bin/bash
# Auto-deploy watcher for ReconDesk on AWS EC2
# Automatically pulls and rebuilds web + worker containers when new commits arrive on origin/main.

set -e
cd /home/ubuntu/recondesk-backend

# Skip if git is locked
if [ -f .git/index.lock ]; then
    exit 0
fi

# Fetch remote
git fetch origin --quiet 2>/dev/null || git fetch origin main --quiet 2>/dev/null || true
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse FETCH_HEAD 2>/dev/null || git rev-parse origin/main 2>/dev/null)

if [ "$1" = "--force" ] || ( [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ] ); then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploying ($LOCAL -> $REMOTE)..."
    git pull origin main
    docker compose -f docker-compose.prod.yml up -d --build --force-recreate web worker
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto-deploy completed successfully!"
else
    if [ -t 1 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Already up to date on commit ${LOCAL:0:8}. Use --force to rebuild anyway."
    fi
fi
