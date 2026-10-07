#!/bin/bash
# Auto-deploy watcher for ReconDesk on AWS EC2
# Automatically pulls and rebuilds web + worker containers when new commits arrive on origin/main.

set -e
cd /home/ubuntu/recondesk-backend

# Skip if git is locked
if [ -f .git/index.lock ]; then
    exit 0
fi

# Fetch remote silently
git fetch origin main --quiet 2>/dev/null || exit 0
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/main 2>/dev/null)

if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] New commit detected ($REMOTE). Auto-deploying..."
    git pull origin main
    docker compose -f docker-compose.prod.yml up -d --build web worker
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto-deploy completed successfully!"
fi
