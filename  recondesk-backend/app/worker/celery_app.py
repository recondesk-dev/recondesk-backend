"""Celery application: broker and result backend from REDIS_URL."""

import os

from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "recondesk",
    broker=redis_url,
    backend=redis_url,
    include=["app.worker.tasks", "app.worker.reconciliation_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

import app.worker.reconciliation_task  # noqa: E402, F401
import app.worker.tasks  # noqa: E402, F401 — register task modules
