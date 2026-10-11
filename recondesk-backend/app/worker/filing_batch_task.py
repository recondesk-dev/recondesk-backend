"""Celery task for Bulk GSTR-1 Return Processing."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.database import get_supabase
from app.filing import filing_store
from app.filing.gstr1_orchestrator import (
    map_sales_register_to_gstr1,
    serialize_gstr1_readiness,
)
from app.filing.sandbox_filing_client import (
    FilingClientError,
    build_save_body,
    get_filing_client,
)
from app.worker.celery_app import celery_app
from app.utils.crypto import decrypt_secret
from app.worker.reliability import (
    QUEUE_FILING,
    JobHeartbeat,
    classify_error,
    log_task_event,
    record_failed_job,
)

_log = logging.getLogger(__name__)

RATE_LIMIT_DELAY_SEC = 0.3  # 300ms delay between GSTN API calls
POLL_MAX_RETRIES = 10
POLL_INITIAL_DELAY_SEC = 2.0
POLL_BACKOFF_FACTOR = 1.5
POLL_MAX_DELAY_SEC = 10.0


def fetch_sales_register_records(sb, client_gstin_id: str, period: str) -> list[dict[str, Any]]:
    """Fetch parsed sales register records from sr_records table."""
    res = (
        sb.table("sr_records")
        .select("record_data")
        .eq("client_gstin_id", str(client_gstin_id).strip())
        .eq("period", period.strip())
        .execute()
    )
    if res.data:
        records = [r.get("record_data") for r in res.data if isinstance(r.get("record_data"), dict)]
        if records:
            return records

    return []


@celery_app.task(
    bind=True,
    name="worker.process_filing_batch",
    max_retries=0,  # Irreversible statutory submission: NEVER blindly retry at the task envelope level
    acks_late=True,
    soft_time_limit=600,
    time_limit=900,
)
def process_filing_batch(self, batch_id: str) -> dict[str, Any]:
    """Orchestrate Bulk GSTR-1 Filing for a batch of GSTINs.
    
    Processes batch items sequentially (or within safe rate limits), reusing 
    the single-GSTIN filing orchestrator and Sandbox client.
    """
    t_start = time.perf_counter()
    task_id = getattr(self.request, "id", None) or "local"
    log_task_event("started", task_id, "worker.process_filing_batch", queue=QUEUE_FILING, run_id=batch_id, attempt=1)
    _log.info("[BATCH_WORKER] START batch_id=%s task_id=%s", batch_id, task_id)
    sb = get_supabase()

    batch = filing_store.get_batch(sb, batch_id)
    if not batch:
        _log.error("[BATCH_WORKER] Batch %s not found", batch_id)
        return {"error": "batch_not_found"}

    current_status = str(batch.get("status") or "").strip().lower()
    # Idempotency guard: do not re-process completed batches
    if current_status in ("completed", "partially_completed"):
        _log.warning("[BATCH_WORKER] Batch %s is already terminal (%s); skipping", batch_id, current_status)
        return batch

    firm_id = str(batch["firm_id"])
    created_by = str(batch.get("created_by") or "")
    period = str(batch["period"])
    items = batch.get("items") or []


    # Update overall batch status to in_progress
    sb.table(filing_store.BATCHES).update({
        "status": "in_progress",
        "updated_at": filing_store._iso(filing_store.datetime.now(filing_store.timezone.utc)),
    }).eq("id", batch_id).execute()

    for item in items:
        item_id = str(item.get("id") or "")
        client_gstin_id = str(item.get("client_gstin_id") or "")
        gstin = str(item.get("gstin") or "").strip().upper()
        current_status = str(item.get("status") or "")

        # Skip items that are already completed or past evc_pending/filed
        if current_status in ("filed", "evc_pending", "saved", "proceeded", "skipped"):
            _log.info("[BATCH_WORKER] Item %s (%s) already at %s — skipping", item_id, gstin, current_status)
            continue

        _log.info("[BATCH_WORKER] Processing item %s for gstin=%s", item_id, gstin)
        filing_store.update_batch_item(sb, item_id, status="in_progress")

        try:
            # Tenant Scoping Verification: Guarantee client belongs to firm
            from app.services.firm_access import assert_client_gstin_in_firm
            try:
                assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
            except Exception as exc:
                _log.warning("[BATCH_WORKER] Unauthorized client %s for firm %s: %s", client_gstin_id, firm_id, exc)
                filing_store.update_batch_item(
                    sb,
                    item_id,
                    status="failed",
                    error_code="UNAUTHORIZED_TENANT",
                    error_detail="Client GSTIN does not belong to the authorized firm.",
                )
                continue

            # 1. Resolve Session Token
            try:
                session_token, session_row = filing_store.get_active_session(sb, firm_id=firm_id, gstin=gstin), None
                if session_token:
                    stoken = str(session_token["session_token"])
                    session_row = session_token
                else:
                    # Check client_gstins fallback token
                    cg_res = sb.table("client_gstins").select("gstn_access_token, gstn_token_expiry").eq("id", client_gstin_id).limit(1).execute()
                    if cg_res.data and cg_res.data[0].get("gstn_access_token"):
                        stoken = str(decrypt_secret(cg_res.data[0]["gstn_access_token"]) or "")
                        session_row = {"id": None}
                    else:
                        raise RuntimeError("No active GSTN session token found for GSTIN")
            except Exception as exc:
                _log.warning("[BATCH_WORKER] Session missing for %s: %s", gstin, exc)
                filing_store.update_batch_item(
                    sb,
                    item_id,
                    status="failed",
                    error_code="NO_SESSION",
                    error_detail="No active GSTN filing session token. Please verify OTP for this GSTIN first.",
                )
                continue

            # 2. Fetch Sales Register Records
            records = fetch_sales_register_records(sb, client_gstin_id, period)
            if not records:
                _log.warning("[BATCH_WORKER] No sales register records for %s period=%s", gstin, period)
                filing_store.update_batch_item(
                    sb,
                    item_id,
                    status="failed",
                    error_code="NO_RECORDS",
                    error_detail=f"No Sales Register records found for period {period}. Upload Sales Register first.",
                )
                continue

            # 3. GSTR-1 Orchestration Readiness
            mapped = map_sales_register_to_gstr1(
                records,
                filer_state=gstin[:2],
                filing_period=period,
            )
            readiness = serialize_gstr1_readiness(mapped)
            pending_review_count = int(readiness.get("pending_review_count") or 0)

            if pending_review_count > 0:
                _log.info("[BATCH_WORKER] GSTIN %s requires review (%d pending issues)", gstin, pending_review_count)
                filing_store.update_batch_item(
                    sb,
                    item_id,
                    status="needs_review",
                    error_code="PENDING_REVIEW",
                    error_detail=f"{pending_review_count} records require manual review (mismatches or validation errors).",
                )
                continue

            # 3b. Pre-Filing Validation and Governance Gate (Phase 2 & 3.1)
            from app.services.pre_filing_validator import validate_gstr1_pre_filing
            from app.services.filing_override_service import (
                verify_filing_governance_gate,
                consume_override_on_file_sync,
            )

            save_payload = getattr(mapped, "save_payload", mapped if isinstance(mapped, dict) else {})
            val_result = validate_gstr1_pre_filing(
                sb,
                client_gstin_id=client_gstin_id,
                gstin=gstin,
                period=period,
                mapped_readiness=readiness,
                save_payload=save_payload,
            )


            active_override = None
            try:
                active_override = verify_filing_governance_gate(
                    sb,
                    firm_id=firm_id,
                    client_gstin_id=client_gstin_id,
                    gstin=gstin,
                    period=period,
                    return_type="GSTR1",
                    validation_result=val_result,
                    user={"id": created_by, "role": "admin"},
                )

            except HTTPException as exc:
                detail_msg = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
                _log.warning("[BATCH_WORKER] Pre-filing governance blocked for %s: %s", gstin, detail_msg)
                filing_store.update_batch_item(
                    sb,
                    item_id,
                    status="blocked",
                    error_code="GOVERNANCE_BLOCKED",
                    error_detail=detail_msg or "Blocked by firm filing governance policy",
                )
                continue

            active_override_id = getattr(active_override, "id", None) if active_override else None

            # 3c. Pre-Filing Maker-Checker Approval Gate (Phase 3.2)
            from app.services.maker_checker_service import (
                assert_maker_checker_gate,
                transition_approval_status,
                ApprovalStatus,
                ApprovalAction,
            )
            try:
                assert_maker_checker_gate(
                    sb,
                    firm_id=firm_id,
                    client_gstin_id=client_gstin_id,
                    gstin=gstin,
                    period=period,
                    return_type="GSTR-1",
                    current_figures_payload=save_payload,
                    operation="SAVE",
                )
            except HTTPException as exc:
                detail_msg = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
                err_code = exc.detail.get("code") if isinstance(exc.detail, dict) else "MAKER_CHECKER_APPROVAL_REQUIRED"
                _log.warning("[BATCH_WORKER] Maker-checker approval blocked for %s: %s", gstin, detail_msg)
                filing_store.update_batch_item(
                    sb,
                    item_id,
                    status="blocked",
                    error_code=err_code,
                    error_detail=detail_msg or "Blocked: Maker-checker approval required or stale figures.",
                )
                continue

            # 3d. Pre-Filing Client Authorization Gate (Phase 3.3)
            from app.services.client_authorization_service import (
                assert_client_authorization_gate,
            )
            try:
                assert_client_authorization_gate(
                    sb,
                    firm_id=firm_id,
                    client_gstin_id=client_gstin_id,
                    gstin=gstin,
                    period=period,
                    return_type="GSTR-1",
                    current_figures_payload=save_payload,
                )
            except HTTPException as exc:
                detail_msg = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
                err_code = exc.detail.get("code") if isinstance(exc.detail, dict) else "CLIENT_AUTHORIZATION_REQUIRED"
                _log.warning("[BATCH_WORKER] Client authorization blocked for %s: %s", gstin, detail_msg)
                filing_store.update_batch_item(
                    sb,
                    item_id,
                    status="blocked",
                    error_code=err_code,
                    error_detail=detail_msg or "Blocked: Client authorization required or figures altered.",
                )
                continue

            # Rate limit delay before GSTN API call
            time.sleep(RATE_LIMIT_DELAY_SEC)

            # 4. Save GSTR-1 to Sandbox
            save_body = build_save_body(
                save_payload,
                gstin=gstin,
                period=period,
                gt=0.0,
                cur_gt=0.0,
            )
            run = filing_store.create_run(
                sb,
                firm_id=firm_id,
                gstin=gstin,
                period=period,
                filing_session_id=str(session_row["id"]) if session_row and session_row.get("id") else None,
                client_gstin_id=client_gstin_id,
                save_payload=save_body,
                status="draft",
            )
            run_id = run["id"]
            filing_store.update_batch_item(sb, item_id, filing_run_id=run_id)

            with get_filing_client() as client:
                save_result = client.save_gstr1(
                    stoken, period=period, save_body=save_body,
                )

            reference_id = save_result.reference_id
            filing_store.update_run(
                sb,
                run_id,
                status="save_pending",
                reference_id=reference_id,
                raw_response=save_result.envelope,
                clear_error=True,
            )

            try:
                transition_approval_status(
                    sb,
                    firm_id=firm_id,
                    client_gstin_id=client_gstin_id,
                    period=period,
                    return_type="GSTR-1",
                    to_status=ApprovalStatus.SAVED,
                    action=ApprovalAction.SAVED.value,
                    actor={"id": created_by, "role": "admin"},
                    filing_run_id=run_id,
                    notes=f"Bulk batch save initiated by task {task_id}",
                )
            except Exception as exc:
                _log.warning("[BATCH_WORKER] Failed to transition approval status to SAVED: %s", exc)

            # 5. Poll Return Status until inner status_cd P or failure
            poll_delay = POLL_INITIAL_DELAY_SEC
            save_confirmed = False

            for attempt in range(POLL_MAX_RETRIES):
                time.sleep(poll_delay)
                poll_delay = min(poll_delay * POLL_BACKOFF_FACTOR, POLL_MAX_DELAY_SEC)

                with get_filing_client() as client:
                    status_res = client.get_return_status(
                        stoken, period=period, reference_id=reference_id,
                    )

                info = status_res.return_status
                if info is not None:
                    updated_run = filing_store.apply_save_status_to_run(
                        sb, run_id, return_status=info, envelope=status_res.envelope,
                    )
                    run_st = updated_run.get("status")
                    if run_st == "saved":
                        save_confirmed = True
                        break
                    elif run_st == "save_failed":
                        err_msg = updated_run.get("error_message") or "Save failed on GSTN"
                        filing_store.update_batch_item(
                            sb,
                            item_id,
                            status="failed",
                            error_code=updated_run.get("error_code") or "SAVE_FAILED",
                            error_detail=err_msg,
                        )
                        break

            if not save_confirmed:
                if item.get("status") != "failed":
                    filing_store.update_batch_item(
                        sb,
                        item_id,
                        status="failed",
                        error_code="SAVE_TIMEOUT",
                        error_detail="Save request timed out waiting for GSTN confirmation.",
                    )
                continue

            # Rate limit delay before Proceed
            time.sleep(RATE_LIMIT_DELAY_SEC)

            # 6. Proceed to File
            with get_filing_client() as client:
                proceed_res = client.proceed_to_file(
                    stoken, period=period, is_nil="N",
                )

            filing_store.update_run(
                sb,
                run_id,
                status="proceeded",
                reference_id=proceed_res.reference_id,
                raw_response=proceed_res.envelope,
                clear_error=True,
            )

            # If an active partner override was utilized, consume it atomically
            if active_override_id:
                try:
                    consume_override_on_file_sync(sb, active_override_id, run_id=run_id)
                    _log.info("[BATCH_WORKER] Successfully consumed override %s for run %s", active_override_id, run_id)
                except Exception as cov_exc:
                    _log.warning("[BATCH_WORKER] Failed to consume override %s: %s", active_override_id, cov_exc)

            # Item reaches evc_pending (ready for EVC OTP submission by CA)
            filing_store.update_batch_item(
                sb,
                item_id,
                status="evc_pending",
                error_code=None,
                error_detail=None,
            )
            _log.info("[BATCH_WORKER] GSTIN %s successfully reached evc_pending", gstin)

        except FilingClientError as exc:
            _log.exception("[BATCH_WORKER] Sandbox filing error for gstin=%s", gstin)
            err_cd = getattr(exc, "error_cd", None) or "FILING_CLIENT_ERROR"
            filing_store.update_batch_item(
                sb,
                item_id,
                status="failed",
                error_code=str(err_cd),
                error_detail=str(exc),
            )
        except Exception as exc:
            _log.exception("[BATCH_WORKER] Unexpected error for gstin=%s", gstin)
            filing_store.update_batch_item(
                sb,
                item_id,
                status="failed",
                error_code="UNEXPECTED_ERROR",
                error_detail=str(exc),
            )

    # Recalculate and persist overall batch status
    final_batch = filing_store.recalculate_batch_status(sb, batch_id)
    duration_ms = (time.perf_counter() - t_start) * 1000
    log_task_event("completed", task_id, "worker.process_filing_batch", queue=QUEUE_FILING, run_id=batch_id, attempt=1, duration_ms=duration_ms)
    _log.info("[BATCH_WORKER] FINISH batch_id=%s status=%s duration_ms=%.1f", batch_id, final_batch.get("status"), duration_ms)
    return final_batch
