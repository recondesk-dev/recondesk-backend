#!/usr/bin/env bash
# Run the import pipeline worker (consumes Redis queue).
# Requires: REDIS_URL, same .env as the API. Set IMPORT_USE_CELERY=true in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
exec celery -A app.worker.celery_app worker --loglevel=info
