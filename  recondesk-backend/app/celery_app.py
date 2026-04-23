"""Celery app re-export (canonical import path: ``app.celery_app:celery_app``)."""

from app.worker.celery_app import celery_app  # noqa: F401

__all__ = ["celery_app"]
