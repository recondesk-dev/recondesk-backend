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

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@worker_init.connect
def assert_worker_environment(**kwargs) -> None:
    """Fail-closed startup assertion: ensure required service credentials exist before worker accepts tasks."""
    from app.config import get_settings

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


