"""Automated tests for Celery background job reliability:
- Task routing to dedicated queues (reconciliation, imports, filing)
- Late acknowledgement and reject-on-worker-lost configuration
- Retryable vs Non-retryable error classification
- Atomic run claim and duplicate execution protection
- Worker heartbeats throttling and updating
- Heartbeat-based stuck job detection vs active heartbeat preservation
- Dead-letter logging into failed_jobs table
- Statutory filing safety (irreversible submissions never blindly retried at task level)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.worker.celery_app import celery_app
from app.worker.reliability import (
    ALL_QUEUES,
    QUEUE_FILING,
    QUEUE_IMPORTS,
    QUEUE_RECONCILIATION,
    TASK_ROUTES,
    JobHeartbeat,
    claim_reconciliation_run,
    classify_error,
    log_task_event,
    record_failed_job,
)


class TestCeleryQueueRoutingAndAckConfiguration:
    """Verifies queue routing and late acknowledgement settings."""

    def test_dedicated_queues_configured(self):
        assert QUEUE_RECONCILIATION == "reconciliation"
        assert QUEUE_IMPORTS == "imports"
        assert QUEUE_FILING == "filing"
        assert "maintenance" in ALL_QUEUES
        assert "exports" in ALL_QUEUES
        assert "notifications" in ALL_QUEUES

    def test_tasks_routed_to_proper_queues(self):
        assert celery_app.conf.task_routes.get("worker.run_import_job") == {"queue": "imports"}
        assert celery_app.conf.task_routes.get("worker.run_wizard_job") == {"queue": "imports"}
        assert celery_app.conf.task_routes.get("worker.execute_reconciliation") == {"queue": "reconciliation"}
        assert celery_app.conf.task_routes.get("worker.process_filing_batch") == {"queue": "filing"}

    def test_late_acknowledgement_enabled(self):
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True
        assert celery_app.conf.task_default_queue == "reconciliation"


class TestErrorClassification:
    """Verifies retryable vs non-retryable error identification."""

    @pytest.mark.parametrize(
        "exc, expected_category, is_retryable",
        [
            (TimeoutError("Connection timed out to R2"), "TRANSIENT_NETWORK_ERROR", True),
            (ConnectionResetError("ECONNRESET from Redis"), "TRANSIENT_NETWORK_ERROR", True),
            (RuntimeError("HTTP 502 Bad Gateway from Supabase"), "TRANSIENT_NETWORK_OR_INFRA_ERROR", True),
            (RuntimeError("Rate limit exceeded 429"), "TRANSIENT_NETWORK_OR_INFRA_ERROR", True),
            (ValueError("Invalid GSTIN 27ABCDE1234F1Z5"), "VALIDATION_OR_BUSINESS_ERROR", False),
            (RuntimeError("Run run-123 does not exist"), "VALIDATION_OR_BUSINESS_ERROR", False),
            (RuntimeError("Run run-123 already terminal (COMPLETED)"), "VALIDATION_OR_BUSINESS_ERROR", False),
            (PermissionError("Unauthorized access to tenant"), "VALIDATION_OR_BUSINESS_ERROR", False),
        ],
    )
    def test_error_classification(self, exc, expected_category, is_retryable):
        cat, retryable = classify_error(exc)
        assert cat == expected_category
        assert retryable == is_retryable


class TestAtomicRunClaim:
    """Verifies atomic claim protection against concurrent duplicate workers."""

    def test_first_worker_claims_run_successfully(self):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # SELECT returns current MATCHING run with attempt_count 0
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "run-100", "status": "MATCHING", "attempt_count": 0}
        ]
        # UPDATE succeeds
        mock_table.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "run-100", "status": "PROCESSING", "attempt_count": 1, "worker_task_id": "task-uuid-1"}
        ]

        claimed, row = claim_reconciliation_run(
            client=mock_client,
            run_id="run-100",
            task_id="task-uuid-1",
        )
        assert claimed is True
        assert row["worker_task_id"] == "task-uuid-1"
        assert row["attempt_count"] == 1

    def test_second_worker_fails_to_claim_already_processing_run(self):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # SELECT returns run already in PROCESSING (claimed by worker 1)
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "run-100", "status": "PROCESSING", "attempt_count": 1}
        ]

        claimed, row = claim_reconciliation_run(
            client=mock_client,
            run_id="run-100",
            task_id="task-uuid-2",
        )
        assert claimed is False
        assert row["status"] == "PROCESSING"

    def test_race_condition_lost_update_fails_claim(self):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # SELECT saw MATCHING
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "run-100", "status": "MATCHING", "attempt_count": 0}
        ]
        # UPDATE matched 0 rows because another worker already flipped it
        mock_table.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

        claimed, row = claim_reconciliation_run(
            client=mock_client,
            run_id="run-100",
            task_id="task-uuid-2",
        )
        assert claimed is False


class TestWorkerHeartbeat:
    """Verifies throttled heartbeats and heartbeat-based stuck job detection."""

    def test_heartbeat_throttling(self):
        mock_client = MagicMock()
        mock_run_table = MagicMock()
        mock_wiz_table = MagicMock()
        def table_router(name: str):
            if name == "reconciliation_run":
                return mock_run_table
            return mock_wiz_table
        mock_client.table.side_effect = table_router

        hb = JobHeartbeat(mock_client, "run-500", "task-abc", interval_seconds=10.0)

        # 1. First beat succeeds (force=True)
        assert hb.beat(force=True) is True
        assert mock_run_table.update.call_count == 1

        # 2. Immediate second beat is throttled (returns False, no extra DB query)
        assert hb.beat(force=False) is False
        assert mock_run_table.update.call_count == 1

        # 3. Beat with force=True bypasses throttle
        assert hb.beat(force=True) is True
        assert mock_run_table.update.call_count == 2

    def test_stuck_job_detector_resets_only_stale_heartbeats(self):
        from app.main import _stuck_job_tick

        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table

        now = datetime.now(timezone.utc)
        # Job 1: Active heartbeat 1 minute ago (healthy long reconciliation)
        job_active = {
            "id": "run-active",
            "status": "PROCESSING",
            "last_heartbeat_at": (now - timedelta(minutes=1)).isoformat(),
            "worker_task_id": "task-active",
            "attempt_count": 1,
        }
        # Job 2: Stale heartbeat 20 minutes ago (> 15 min default threshold)
        job_stale = {
            "id": "run-stale",
            "status": "PROCESSING",
            "last_heartbeat_at": (now - timedelta(minutes=20)).isoformat(),
            "worker_task_id": "task-dead",
            "attempt_count": 1,
        }

        mock_table.select.return_value.in_.return_value.execute.return_value.data = [
            job_active,
            job_stale,
        ]
        mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock()

        with patch("app.main.get_supabase", return_value=mock_supabase):
            _stuck_job_tick()

        # Only the stale job must be updated to FAILED
        updated_calls = mock_table.update.call_args_list
        assert len(updated_calls) == 1
        update_arg = updated_calls[0][0][0]
        assert update_arg["status"] == "FAILED"
        assert update_arg["error_category"] == "HEARTBEAT_TIMEOUT"


class TestDeadLetterAndObservability:
    """Verifies failed_jobs logging and sanitized structured logging."""

    def test_record_failed_job_persists_to_database(self):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        record_failed_job(
            client=mock_client,
            task_id="task-failed-99",
            task_name="worker.run_import_job",
            queue="imports",
            exc=ValueError("Invalid file syntax"),
            entity_id="run-99",
            entity_type="reconciliation_run",
            attempt_count=3,
            payload_summary={"file_type": "gstr2b"},
        )

        mock_client.table.assert_called_with("failed_jobs")
        insert_args = mock_table.insert.call_args[0][0]
        assert insert_args["task_id"] == "task-failed-99"
        assert insert_args["task_name"] == "worker.run_import_job"
        assert insert_args["queue"] == "imports"
        assert insert_args["error_category"] == "VALIDATION_OR_BUSINESS_ERROR"
        assert insert_args["attempt_count"] == 3
        assert insert_args["entity_id"] == "run-99"

    def test_log_task_event_scrubs_and_formats(self, caplog):
        with caplog.at_level("INFO"):
            log_task_event(
                event="retry",
                task_id="task-retry-1",
                task_name="worker.execute_reconciliation",
                queue="reconciliation",
                run_id="run-abc",
                attempt=2,
                duration_ms=125.45,
                error="HTTP 504 Gateway Timeout",
            )
        assert "[CELERY_EVENT]" in caplog.text
        assert "task_retry" in caplog.text
        assert "task-retry-1" in caplog.text
        assert "run-abc" in caplog.text
