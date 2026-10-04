"""Celery task for Bulk GSTR-1 Return Processing."""

from __future__ import annotations

import logging
import time
from typing import Any

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

_log = logging.getLogger(__name__)

RATE_LIMIT_DELAY_SEC = 0.3  # 300ms delay between GSTN API calls
POLL_MAX_RETRIES = 10
POLL_INITIAL_DELAY_SEC = 2.0
POLL_BACKOFF_FACTOR = 1.5
POLL_MAX_DELAY_SEC = 10.0


def fetch_sales_register_records(sb, client_gstin_id: str, period: str) -> list[dict[str, Any]]:
    """Fetch parsed sales register records from sr_records (Aurora PRIMARY with Supabase fallback)."""
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        records = get_filing_automation_repository().fetch_sales_register_records(
            client_gstin_id=client_gstin_id,
            period=period,
        )
        if records:
            return records
    except Exception as exc:
        _log.warning("Aurora sr_records fetch failed: %s; falling back to Supabase", exc)

    try:
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
    except Exception as exc:
        _log.warning("Supabase fallback sr_records fetch failed: %s", exc)

    return []


@celery_app.task(
    name="worker.process_filing_batch",
    max_retries=0,
    soft_time_limit=600,
    time_limit=900,
)
def process_filing_batch(batch_id: str) -> dict[str, Any]:
    """Orchestrate Bulk GSTR-1 Filing for a batch of GSTINs.
    
    Processes batch items sequentially (or within safe rate limits), reusing 
    the single-GSTIN filing orchestrator and Sandbox client.
    """
    _log.info("[BATCH_WORKER] START batch_id=%s", batch_id)
    sb = get_supabase()

    batch = filing_store.get_batch(sb, batch_id)
    if not batch:
        _log.error("[BATCH_WORKER] Batch %s not found", batch_id)
        return {"error": "batch_not_found"}

    firm_id = str(batch["firm_id"])
    period = str(batch["period"])
    items = batch.get("items") or []

    # Update overall batch status to in_progress
    filing_store.update_batch_status(sb, batch_id=batch_id, status="in_progress")

    for item in items:
        item_id = str(item["id"])
        client_gstin_id = str(item["client_gstin_id"])
        gstin = str(item["gstin"]).strip().upper()
        current_status = str(item.get("status") or "")

        # Skip items that are already completed or past evc_pending/filed
        if current_status in ("filed", "evc_pending", "saved", "proceeded", "skipped"):
            _log.info("[BATCH_WORKER] Item %s (%s) already at %s — skipping", item_id, gstin, current_status)
            continue

        _log.info("[BATCH_WORKER] Processing item %s for gstin=%s", item_id, gstin)
        filing_store.update_batch_item(sb, item_id, status="in_progress")

        try:
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
                        stoken = str(cg_res.data[0]["gstn_access_token"])
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

            # Rate limit delay before GSTN API call
            time.sleep(RATE_LIMIT_DELAY_SEC)

            # 4. Save GSTR-1 to Sandbox
            save_body = build_save_body(
                mapped.save_payload,
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
    _log.info("[BATCH_WORKER] FINISH batch_id=%s status=%s", batch_id, final_batch.get("status"))
    return final_batch
