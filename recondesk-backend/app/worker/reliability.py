"""Enterprise background job reliability utilities:
- Queue definitions & centralized task routing
- Atomic run claiming & duplicate execution protection
- Worker heartbeats & attempt counting
- Error classification (retryable vs non-retryable)
- Dead letter / terminal failure recording
- Structured event logging (sanitized, zero secret leakage)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.utils.context import get_correlation_id

_log = logging.getLogger("app.worker.reliability")

# ── Centralized Queue Definitions ─────────────────────────────────────────────
QUEUE_RECONCILIATION = "reconciliation"
QUEUE_IMPORTS = "imports"
QUEUE_GSTN = "gstn"
QUEUE_FILING = "filing"
QUEUE_EXPORTS = "exports"
QUEUE_NOTIFICATIONS = "notifications"
QUEUE_MAINTENANCE = "maintenance"

ALL_QUEUES = [
    QUEUE_RECONCILIATION,
    QUEUE_IMPORTS,
    QUEUE_GSTN,
    QUEUE_FILING,
    QUEUE_EXPORTS,
    QUEUE_NOTIFICATIONS,
    QUEUE_MAINTENANCE,
]

# Task-to-queue routing map
TASK_ROUTES = {
    # Ingestion & file parsing
    "worker.run_import_job": {"queue": QUEUE_IMPORTS},
    # Wizard pipeline (orchestrates import + reconciliation)
    "worker.run_wizard_job": {"queue": QUEUE_IMPORTS},
    # Reconciliation engine
    "worker.execute_reconciliation": {"queue": QUEUE_RECONCILIATION},
    # Bulk Filing (statutory GSTR-1 sandbox/live submission)
    "worker.process_filing_batch": {"queue": QUEUE_FILING},
}


# ── Error Classification ──────────────────────────────────────────────────────
# Errors that indicate transient infrastructure/network issues and are safe to retry
RETRYABLE_ERROR_SUBSTRINGS = (
    "timeout",
    "timed out",
    "connection refused",
    "connection reset",
    "connection error",
    "endpointconnectionerror",
    "nosuchbucket",
    "serviceunavailable",
    "slowdown",
    "toomanyrequests",
    "rate limit",
    "ratelimit",
    "502",
    "503",
    "504",
    "temporarily unavailable",
    "temporary failure",
    "network error",
    "econnreset",
)

# Errors that indicate fundamental logic/validation bugs or irreversible business violations
NON_RETRYABLE_ERROR_SUBSTRINGS = (
    "invalid gstin",
    "does not exist",
    "not found",
    "unauthorized",
    "forbidden",
    "validation error",
    "parse error",
    "syntax",
    "cannot import into run",
    "already terminal",
    "already finalized",
    "missing required",
    "invalid format",
    "integrityerror",
    "foreign key",
    "unique constraint",
    "check constraint",
)


def classify_error(exc: BaseException) -> tuple[str, bool]:
    """Classifies an exception into an error_category and whether it is retryable.
    
    Returns:
        (category: str, is_retryable: bool)
    """
    msg = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    # Check non-retryable first
    for non_ret in NON_RETRYABLE_ERROR_SUBSTRINGS:
        if non_ret in msg or non_ret in exc_type:
            return ("VALIDATION_OR_BUSINESS_ERROR", False)

    # Standard python socket/network errors
    import socket
    if isinstance(exc, (socket.timeout, ConnectionResetError, ConnectionRefusedError, TimeoutError)):
        return ("TRANSIENT_NETWORK_ERROR", True)

    # Check retryable substrings
    for ret in RETRYABLE_ERROR_SUBSTRINGS:
        if ret in msg or ret in exc_type:
            return ("TRANSIENT_NETWORK_OR_INFRA_ERROR", True)

    return ("UNCLASSIFIED_ERROR", False)


# ── Structured Observability Logging ──────────────────────────────────────────
def log_task_event(
    event: str,
    task_id: str,
    task_name: str,
    queue: Optional[str] = None,
    run_id: Optional[str] = None,
    attempt: int = 1,
    duration_ms: Optional[float] = None,
    error: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Emit structured log event without exposing secrets, tokens, or credentials."""
    cid = get_correlation_id()
    log_data: dict[str, Any] = {
        "event": f"task_{event}",
        "task_id": task_id,
        "task_name": task_name,
        "queue": queue or "default",
        "attempt": attempt,
        "correlation_id": cid,
    }
    if run_id:
        log_data["run_id"] = str(run_id)
    if duration_ms is not None:
        log_data["duration_ms"] = round(duration_ms, 2)
    if error:
        # Sanitize error message to prevent accidental token leakage
        sanitized_err = str(error)[:500].replace("\n", " ")
        log_data["error"] = sanitized_err
    if extra:
        log_data.update(extra)

    _log.info("[CELERY_EVENT] %s", log_data)


# ── Atomic Run Claim & Duplicate Execution Protection ─────────────────────────
def claim_reconciliation_run(
    client: Any,
    run_id: str,
    task_id: str,
    target_status: str = "PROCESSING",
    expected_status: str = "MATCHING",
    status_message: str = "Initializing reconciliation worker",
) -> tuple[bool, dict[str, Any]]:
    """Atomically claim a reconciliation run to prevent concurrent/duplicate execution.
    
    Uses Postgres UPDATE ... WHERE id = run_id AND status = expected_status.
    If another worker already claimed or started the run, returns (False, current_run_data).
    """
    now = datetime.now(timezone.utc).isoformat()
    cid = get_correlation_id()

    # Fetch current attempt count
    run_res = (
        client.table("reconciliation_run")
        .select("id, status, retry_count, client_gstin_id, period")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not run_res.data:
        return False, {}

    current_row = run_res.data[0]
    curr_status = str(current_row.get("status") or "").strip().upper()
    if curr_status != expected_status.upper():
        _log.warning(
            "claim_reconciliation_run: run %s has status '%s', expected '%s'",
            run_id,
            curr_status,
            expected_status,
        )
        return False, current_row

    current_attempt = int(current_row.get("retry_count") or 0)
    new_attempt = current_attempt + 1

    update_payload: dict[str, Any] = {
        "status": target_status,
        "status_message": status_message,
        "retry_count": new_attempt,
        "processing_started_at": now,
        "updated_at": now,
    }

    claim_query = (
        client.table("reconciliation_run")
        .update(update_payload)
        .eq("id", run_id)
        .eq("status", expected_status)
        .execute()
    )

    if claim_query.data:
        # Also best-effort mirror to reconciliation_import_runs
        try:
            client.table("reconciliation_import_runs").update({
                "status_message": status_message,
                "updated_at": now,
            }).eq("id", run_id).execute()
        except Exception as exc:
            _log.debug("Mirror claim to reconciliation_import_runs ignored: %s", exc)

        return True, claim_query.data[0]

    return False, current_row


# ── Heartbeat Manager ─────────────────────────────────────────────────────────
class JobHeartbeat:
    """Throttled heartbeat manager for long-running Celery worker tasks.
    
    Emits an update to the database at most once every `interval_seconds` (default 30s)
    to prevent hammering the database during row-by-row matching loops.
    """

    def __init__(
        self,
        client: Any,
        run_id: str,
        task_id: str,
        table_name: str = "reconciliation_run",
        interval_seconds: float = 30.0,
    ) -> None:
        self.client = client
        self.run_id = str(run_id)
        self.task_id = str(task_id)
        self.table_name = table_name
        self.interval_seconds = interval_seconds
        self._last_beat_time: float = 0.0

    def beat(
        self,
        force: bool = False,
        status_message: Optional[str] = None,
        progress_percent: Optional[int] = None,
    ) -> bool:
        """Sends a heartbeat if `interval_seconds` has elapsed since the last beat or `force=True`."""
        now_mono = time.monotonic()
        if not force and (now_mono - self._last_beat_time) < self.interval_seconds:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "updated_at": now_iso,
        }
        if self.table_name != "reconciliation_run":
            payload["last_heartbeat_at"] = now_iso
            payload["worker_task_id"] = self.task_id
        if status_message is not None:
            payload["status_message"] = status_message
        if progress_percent is not None:
            payload["progress_percent"] = progress_percent

        try:
            self.client.table(self.table_name).update(payload).eq("id", self.run_id).execute()
            if self.table_name == "reconciliation_run":
                # Mirror to import wizard table
                try:
                    wiz_patch: dict[str, Any] = {"updated_at": now_iso}
                    if progress_percent is not None:
                        wiz_patch["progress_pct"] = progress_percent
                    if status_message is not None:
                        wiz_patch["status_message"] = status_message
                    self.client.table("reconciliation_import_runs").update(wiz_patch).eq("id", self.run_id).execute()
                except Exception:
                    pass
            self._last_beat_time = now_mono
            return True
        except Exception as exc:
            _log.warning("JobHeartbeat: failed to persist heartbeat for run %s: %s", self.run_id, exc)
            return False


# ── Dead-Letter / Terminal Failure Recording ──────────────────────────────────
def record_failed_job(
    client: Any,
    task_id: str,
    task_name: str,
    queue: str,
    exc: BaseException,
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    attempt_count: int = 1,
    payload_summary: Optional[dict[str, Any]] = None,
) -> None:
    """Record an unrecoverable or exhausted job failure to the database dead-letter log."""
    cid = get_correlation_id()
    err_cat, _ = classify_error(exc)
    sanitized_msg = str(exc)[:2000].replace("\x00", "")

    record: dict[str, Any] = {
        "task_id": str(task_id),
        "task_name": str(task_name),
        "queue": str(queue),
        "entity_id": str(entity_id) if entity_id else None,
        "entity_type": str(entity_type) if entity_type else None,
        "attempt_count": attempt_count,
        "error_category": err_cat,
        "error_message": sanitized_msg,
        "correlation_id": cid,
        "payload_summary": payload_summary or {},
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        client.table("failed_jobs").insert(record).execute()
        _log.info(
            "[DEAD_LETTER] Recorded failed job task_id=%s task_name=%s error_category=%s entity_id=%s",
            task_id,
            task_name,
            err_cat,
            entity_id,
        )
    except Exception as record_exc:
        _log.exception("Failed to write to failed_jobs table: %s", record_exc)
