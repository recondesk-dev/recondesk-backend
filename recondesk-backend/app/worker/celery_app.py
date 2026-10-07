"""Celery application: broker and result backend from REDIS_URL."""

import logging
import os
import sys

from celery import Celery
from celery.signals import worker_init

_log = logging.getLogger(__name__)

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "recondesk",
    broker=redis_url,
    backend=redis_url,
    include=[
        "app.worker.tasks",
        "app.worker.reconciliation_task",
        "app.worker.filing_batch_task",
    ],
)

from app.worker.reliability import (
    ALL_QUEUES,
    QUEUE_IMPORTS,
    QUEUE_RECONCILIATION,
    QUEUE_FILING,
    TASK_ROUTES,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Enterprise Queue Routing: separate queues prevent starvation across functional domains
    task_routes=TASK_ROUTES,
    task_default_queue=QUEUE_RECONCILIATION,
    # Late acknowledgement: task acknowledged only after successful completion so worker crashes don't drop jobs
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


@worker_init.connect
def assert_worker_environment(**kwargs) -> None:
    """Fail-closed startup assertion: ensure required service credentials exist before worker accepts tasks."""
    from app.config import get_settings
    from app.aurora import is_aurora_enabled, get_aurora_database_url

    if is_aurora_enabled() and get_aurora_database_url():
        _log.info("Celery worker environment verified using AWS Aurora PostgreSQL.")
        return

    settings = get_settings()
    key = str(getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
    if not key:
        msg = (
            "FATAL: Celery worker startup aborted: SUPABASE_SERVICE_ROLE_KEY is missing or empty. "
            "The worker cannot execute ingestion, reconciliation, or filing jobs without service-role access."
        )
        _log.critical(msg)
        sys.stderr.write(f"\n[CRITICAL] {msg}\n\n")
        raise SystemExit(1)


import app.worker.filing_batch_task  # noqa: E402, F401
import app.worker.reconciliation_task  # noqa: E402, F401
import app.worker.tasks  # noqa: E402, F401 — register task modules


