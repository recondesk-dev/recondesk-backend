#!/usr/bin/env bash
# Run the Celery background worker.
# Optional argument: QUEUES (comma-separated, e.g. "reconciliation" or "imports")
# Requires: REDIS_URL, same .env as the API. Set IMPORT_USE_CELERY=true in .env.
set -euo pipefail
cd "$(dirname "$0")/.."

QUEUES="${1:-reconciliation,imports,gstn,filing,exports,notifications,maintenance}"
exec celery -A app.worker.celery_app worker -Q "$QUEUES" --loglevel=info
