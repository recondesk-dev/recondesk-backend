"""Multi-Period Reconciliation Wizard Service.

Orchestrates multi-period (up to 12 months) GSTR-2B auto-fetching,
PR availability auto-detection (Tally Bridge or prior uploads) with manual fallback,
sequential chronological batch reconciliation, and aggregated FY summaries.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from supabase import Client

from app.database import get_supabase
from app.integrations.gstr2b_autofetch import SandboxGstnError, get_gstr2b
from app.parsers.gstr2b_parser import parse_gstr2b
from app.parsers.purchase_register_parser import parse_purchase_register
from app.routers.gstr2b_autofetch_routes import (
    _assert_gstn_token_fresh,
    _gstr2b_payload_for_parser,
    _load_client_gstin,
)
from app.services.gstr9c_itc_fy_rollup import assemble_fy_rollup, parse_fy_label
from app.services.r2_service import upload_file_to_r2
from app.worker.reconciliation_task import execute_reconciliation
from app.worker.tasks import run_import_job
from app.repositories.return_reconciliation import AuroraReturnReconciliationRepository

logger = logging.getLogger(__name__)

_return_recon_repo = AuroraReturnReconciliationRepository()


def _db_insert_batch(sb: Optional[Client], batch_row: dict[str, Any]) -> None:
    try:
        _return_recon_repo.create_batch(
            client_gstin_id=batch_row["client_gstin_id"],
            financial_year=batch_row["financial_year"],
            status=batch_row.get("status", "pending"),
            created_by=batch_row.get("created_by"),
            batch_id=batch_row.get("id"),
        )
        return
    except Exception as exc:
        logger.warning("Aurora create_batch failed, falling back to Supabase: %s", exc)
        if sb:
            sb.table("multi_period_recon_batches").insert(batch_row).execute()
        else:
            raise


def _db_insert_batch_items(sb: Optional[Client], batch_id: str, items: list[dict[str, Any]]) -> None:
    try:
        _return_recon_repo.create_batch_items(batch_id=batch_id, items=items)
        return
    except Exception as exc:
        logger.warning("Aurora create_batch_items failed, falling back to Supabase: %s", exc)
        if sb:
            sb.table("multi_period_recon_batch_items").insert(items).execute()
        else:
            raise


def _db_get_batch(sb: Optional[Client], batch_id: str) -> Optional[dict[str, Any]]:
    try:
        batch = _return_recon_repo.get_batch(batch_id)
        if batch:
            return batch
    except Exception as exc:
        logger.warning("Aurora get_batch failed, falling back to Supabase: %s", exc)
    if sb:
        res = sb.table("multi_period_recon_batches").select("*").eq("id", batch_id).limit(1).execute()
        return res.data[0] if res.data else None
    return None


def _db_get_batch_items(sb: Optional[Client], batch_id: str) -> list[dict[str, Any]]:
    try:
        items = _return_recon_repo.list_batch_items(batch_id)
        if items:
            return items
    except Exception as exc:
        logger.warning("Aurora list_batch_items failed, falling back to Supabase: %s", exc)
    if sb:
        res = (
            sb.table("multi_period_recon_batch_items")
            .select("*")
            .eq("batch_id", batch_id)
            .order("period", desc=False)
            .execute()
        )
        return res.data or []
    return []


def _db_update_batch(sb: Optional[Client], batch_id: str, updates: dict[str, Any]) -> None:
    updated = False
    try:
        res = _return_recon_repo.update_batch(batch_id, updates)
        if res:
            updated = True
    except Exception as exc:
        logger.warning("Aurora update_batch failed, falling back to Supabase: %s", exc)
    if not updated and sb:
        sb.table("multi_period_recon_batches").update(updates).eq("id", batch_id).execute()


def _db_update_batch_item(sb: Optional[Client], item_id: str, updates: dict[str, Any]) -> None:
    updated = False
    try:
        res = _return_recon_repo.update_batch_item(item_id, updates)
        if res:
            updated = True
    except Exception as exc:
        logger.warning("Aurora update_batch_item failed, falling back to Supabase: %s", exc)
    if not updated and sb:
        sb.table("multi_period_recon_batch_items").update(updates).eq("id", item_id).execute()


def _db_update_batch_item_by_period(sb: Optional[Client], batch_id: str, period: str, updates: dict[str, Any]) -> None:
    updated = False
    try:
        res = _return_recon_repo.update_batch_item_by_period(batch_id, period, updates)
        if res:
            updated = True
    except Exception as exc:
        logger.warning("Aurora update_batch_item_by_period failed, falling back to Supabase: %s", exc)
    if not updated and sb:
        sb.table("multi_period_recon_batch_items").update(updates).eq("batch_id", batch_id).eq("period", period).execute()



def is_gstr1_due_in_period(period: str, filing_frequency: str) -> bool:
    """Return True if GSTR-1 filing is mandatory for *period*.

    Monthly filers: mandatory every month.
    QRMP filers: mandatory in quarter-end months (06, 09, 12, 03).
    Non-quarter-end months under QRMP use optional Invoice Furnishing Facility (IFF).
    """
    if (filing_frequency or "").lower().strip() != "qrmp":
        return True
    try:
        month = period.split("-")[1]
        return month in ("06", "09", "12", "03")
    except Exception:
        return True


def is_gstr3b_due_in_period(period: str, filing_frequency: str) -> bool:
    """Return True if GSTR-3B return filing is mandatory for *period*.

    Monthly filers: mandatory every month.
    QRMP filers: mandatory in quarter-end months (06, 09, 12, 03).
    Non-quarter-end months under QRMP are cash deposit months (PMT-06 challan).
    """
    if (filing_frequency or "").lower().strip() != "qrmp":
        return True
    try:
        month = period.split("-")[1]
        return month in ("06", "09", "12", "03")
    except Exception:
        return True


def create_batch(
    sb: Client,
    client_id: str,
    financial_year: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create a new multi-period batch for a client and FY with 12 period slots (Apr–Mar)."""
    cg_res = (
        sb.table("client_gstins")
        .select("filing_frequency, scheme_type")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    filing_freq = "monthly"
    if cg_res.data:
        filing_freq = str(cg_res.data[0].get("filing_frequency") or "monthly").lower().strip()

    start_year, end_year = parse_fy_label(financial_year)
    
    # 12 periods: Apr-Dec of start_year, Jan-Mar of end_year
    periods = [f"{start_year}-{m:02d}" for m in range(4, 13)] + [
        f"{end_year}-{m:02d}" for m in range(1, 4)
    ]

    batch_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    batch_row = {
        "id": batch_id,
        "client_gstin_id": client_id,
        "financial_year": financial_year,
        "status": "pending",
        "created_by": user_id,
        "created_at": now,
        "updated_at": now,
    }

    _db_insert_batch(sb, batch_row)

    items_to_insert = []
    for period in periods:
        pr_avail = check_pr_availability(sb, client_id, period)
        pr_src = pr_avail.get("pr_source", "missing")
        pr_path = pr_avail.get("pr_file_path")
        run_id = pr_avail.get("reconciliation_run_id")

        g3b_req = is_gstr3b_due_in_period(period, filing_freq)
        init_note = None
        if filing_freq == "qrmp" and not g3b_req:
            init_note = "QRMP: PMT-06 cash challan payment due (GSTR-3B not filed in months 1-2)"

        items_to_insert.append({
            "id": str(uuid4()),
            "batch_id": batch_id,
            "period": period,
            "gstr2b_source": None,
            "gstr2b_file_path": None,
            "pr_source": pr_src,
            "pr_file_path": pr_path,
            "reconciliation_run_id": run_id,
            "status": "pending",
            "error_message": init_note,
            "created_at": now,
            "updated_at": now,
        })

    _db_insert_batch_items(sb, batch_id, items_to_insert)

    return get_batch_with_items(sb, batch_id)


def check_pr_availability(sb: Client, client_id: str, period: str) -> dict[str, Any]:
    """Check if PR data already exists for a client and period.

    Returns:
      - pr_source: 'tally_bridge_existing' | 'already_uploaded' | 'missing'
      - pr_file_path: R2 key if available
      - reconciliation_run_id: UUID of run if available
    """
    res = (
        sb.table("reconciliation_run")
        .select("*")
        .eq("client_gstin_id", client_id)
        .eq("period", period)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    rows = res.data or []
    for r in rows:
        pr_records_n = int(r.get("pr_records_imported") or 0)
        pr_key = r.get("pr_r2_key") or r.get("r2_key") or ""
        file_type = str(r.get("file_type") or "").lower()

        if pr_records_n > 0 or pr_key:
            if "tally_pr" in pr_key or file_type == "purchase_register":
                return {
                    "pr_source": "tally_bridge_existing",
                    "pr_file_path": pr_key,
                    "reconciliation_run_id": r["id"],
                }
            return {
                "pr_source": "already_uploaded",
                "pr_file_path": pr_key,
                "reconciliation_run_id": r["id"],
            }

    return {
        "pr_source": "missing",
        "pr_file_path": None,
        "reconciliation_run_id": None,
    }


def get_batch_with_items(sb: Client, batch_id: str) -> dict[str, Any]:
    """Fetch batch details and all 12 items sorted by period."""
    batch = _db_get_batch(sb, batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    client_id = batch.get("client_gstin_id")
    filing_freq = "monthly"
    if client_id:
        try:
            cg = sb.table("client_gstins").select("filing_frequency").eq("id", client_id).limit(1).execute()
            if cg.data:
                filing_freq = str(cg.data[0].get("filing_frequency") or "monthly").lower().strip()
        except Exception:
            pass

    raw_items = _db_get_batch_items(sb, batch_id)
    enriched_items = []
    for item in raw_items:
        p = str(item.get("period") or "")
        g1_req = is_gstr1_due_in_period(p, filing_freq)
        g3b_req = is_gstr3b_due_in_period(p, filing_freq)
        is_qrmp = filing_freq == "qrmp"
        g3b_slot_type = "monthly_return" if not is_qrmp else ("quarterly_return" if g3b_req else "pmt06_challan")
        pmt06_indicator = "PMT-06 payment due" if (is_qrmp and not g3b_req) else None

        enriched_items.append({
            **item,
            "filing_frequency": filing_freq,
            "gstr1_required": g1_req,
            "gstr3b_required": g3b_req,
            "gstr3b_slot_type": g3b_slot_type,
            "pmt06_indicator": pmt06_indicator,
        })
    batch["filing_frequency"] = filing_freq
    batch["items"] = enriched_items
    return batch


def fetch_gstr2b_for_batch(batch_id: str, user_id: str | None = None) -> None:
    """Async background worker task to auto-fetch GSTR-2B for all 12 periods.

    Isolates failures per period so OTP/portal errors on one month do not abort others.
    """
    sb = get_supabase()
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]
    filing_freq = str(batch.get("filing_frequency") or "monthly").lower().strip()

    _db_update_batch(sb, batch_id, {
        "status": "fetching",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    client_row = _load_client_gstin(sb, client_id)
    access_token = client_row.get("gstn_access_token")
    gstin = str(client_row.get("gstin") or "").strip()

    has_token = bool(access_token)
    if has_token:
        try:
            _assert_gstn_token_fresh(client_row)
        except Exception:
            has_token = False

    items = batch["items"]
    failed_count = 0
    completed_count = 0

    for item in items:
        item_id = item["id"]
        period = item["period"]
        year, month = int(period[:4]), int(period[5:7])

        if item.get("gstr2b_file_path") and item.get("status") == "uploaded":
            completed_count += 1
            continue

        is_qrmp = filing_freq == "qrmp"
        is_q_end = is_gstr1_due_in_period(period, filing_freq)

        if not has_token or not access_token or not gstin:
            if is_qrmp and not is_q_end:
                _db_update_batch_item(sb, item_id, {
                    "status": "not_available",
                    "error_message": "GSTR-2B not generated by GSTN for QRMP months 1-2 (combined quarterly statement in month 3)",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            else:
                _db_update_batch_item(sb, item_id, {
                    "status": "failed",
                    "error_message": "GSTN not connected or OTP session expired for this client",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                failed_count += 1
            continue

        _db_update_batch_item(sb, item_id, {
            "status": "fetching",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

        try:
            raw_data = get_gstr2b(access_token, gstin, year, month)
            payload = _gstr2b_payload_for_parser(
                raw_data,
                fallback_gstin=gstin,
                year=year,
                month=month,
            )
            parse_gstr2b(payload)  # Sanity validation

            payload_bytes = json.dumps(payload).encode("utf-8")
            r2_key = f"multi-period/{client_id}/{batch_id}/gstr2b_{period}.json"
            upload_file_to_r2(payload_bytes, r2_key, content_type="application/json")

            _db_update_batch_item(sb, item_id, {
                "gstr2b_source": "auto_fetch",
                "gstr2b_file_path": r2_key,
                "status": "uploaded",
                "error_message": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            completed_count += 1

        except (SandboxGstnError, ValueError, Exception) as exc:
            logger.warning(
                "GSTR-2B fetch failed for batch %s period %s: %s", batch_id, period, exc
            )
            err_msg = exc.message if hasattr(exc, "message") else str(exc)
            if is_qrmp and not is_q_end:
                _db_update_batch_item(sb, item_id, {
                    "gstr2b_source": "not_available",
                    "status": "not_available",
                    "error_message": "GSTR-2B not generated by GSTN for QRMP months 1-2 (combined quarterly statement in month 3)",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            else:
                _db_update_batch_item(sb, item_id, {
                    "status": "failed",
                    "error_message": err_msg[:500],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                failed_count += 1

    final_status = (
        "queued" if failed_count == 0
        else ("partially_failed" if completed_count > 0 else "failed")
    )
    _db_update_batch(sb, batch_id, {
        "status": final_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def attach_manual_pr(
    sb: Client,
    batch_id: str,
    period: str,
    file_bytes: bytes,
    filename: str,
) -> dict[str, Any]:
    """Upload a manual PR file for a missing month in a batch."""
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]

    parse_purchase_register(file_bytes, filename)  # Validate format

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "xlsx"
    r2_key = f"multi-period/{client_id}/{batch_id}/manual_pr_{period}.{ext}"
    upload_file_to_r2(file_bytes, r2_key)

    _db_update_batch_item_by_period(sb, batch_id, period, {
        "pr_source": "manual_upload",
        "pr_file_path": r2_key,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    return get_batch_with_items(sb, batch_id)


def run_batch(batch_id: str, user_id: str | None = None) -> None:
    """Async background worker task to run batch reconciliation.

    Executes items in strict chronological order (Apr->Mar) to maintain carry-forward integrity.
    """
    sb = get_supabase()
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]

    _db_update_batch(sb, batch_id, {
        "status": "running",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    items = batch["items"]
    # Sort items chronologically by period
    items.sort(key=lambda x: x["period"])

    failed_count = 0
    completed_count = 0

    for item in items:
        item_id = item["id"]
        period = item["period"]
        gstr2b_key = item.get("gstr2b_file_path")
        pr_key = item.get("pr_file_path")

        if not gstr2b_key or not pr_key or item.get("pr_source") == "missing":
            _db_update_batch_item(sb, item_id, {
                "status": "failed",
                "error_message": "Missing GSTR-2B or Purchase Register file",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            failed_count += 1
            continue

        _db_update_batch_item(sb, item_id, {
            "status": "running",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

        run_id = item.get("reconciliation_run_id") or str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        try:
            # Ensure reconciliation_run row exists
            existing_run = (
                sb.table("reconciliation_run")
                .select("id")
                .eq("id", run_id)
                .limit(1)
                .execute()
            )
            if not existing_run.data:
                sb.table("reconciliation_run").insert({
                    "id": run_id,
                    "client_gstin_id": client_id,
                    "period": period,
                    "status": "uploading",
                    "gstr2b_r2_key": gstr2b_key,
                    "r2_key": pr_key,
                    "created_at": now,
                    "updated_at": now,
                }).execute()
            else:
                sb.table("reconciliation_run").update({
                    "gstr2b_r2_key": gstr2b_key,
                    "r2_key": pr_key,
                    "status": "uploading",
                    "updated_at": now,
                }).eq("id", run_id).execute()

            # Execute import & matching tasks in-process
            run_import_job.apply(args=[run_id, "gstr2b", gstr2b_key])
            run_import_job.apply(args=[run_id, "purchase_register", pr_key])
            execute_reconciliation.apply(args=[run_id])

            _db_update_batch_item(sb, item_id, {
                "reconciliation_run_id": run_id,
                "status": "completed",
                "error_message": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            completed_count += 1

        except Exception as exc:
            logger.exception("Batch reconciliation failed for period %s: %s", period, exc)
            _db_update_batch_item(sb, item_id, {
                "reconciliation_run_id": run_id,
                "status": "failed",
                "error_message": str(exc)[:500],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            failed_count += 1

    final_status = (
        "completed" if failed_count == 0
        else ("partially_failed" if completed_count > 0 else "failed")
    )
    _db_update_batch(sb, batch_id, {
        "status": final_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def get_batch_summary(sb: Client, batch_id: str) -> dict[str, Any]:
    """Return aggregated FY summary metrics and monthly trend array."""
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]
    fy = batch["financial_year"]

    rollup = assemble_fy_rollup(sb, client_gstin_id=client_id, fy=fy)
    batch["summary"] = rollup
    return batch
