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

logger = logging.getLogger(__name__)


def create_batch(
    sb: Client,
    client_id: str,
    financial_year: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create a new multi-period batch for a client and FY with 12 period slots (Apr–Mar)."""
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

    sb.table("multi_period_recon_batches").insert(batch_row).execute()

    items_to_insert = []
    for period in periods:
        pr_avail = check_pr_availability(sb, client_id, period)
        pr_src = pr_avail.get("pr_source", "missing")
        pr_path = pr_avail.get("pr_file_path")
        run_id = pr_avail.get("reconciliation_run_id")

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
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        })

    sb.table("multi_period_recon_batch_items").insert(items_to_insert).execute()

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
        .select("id, status, r2_key, pr_r2_key, file_type, pr_records_imported, created_at")
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
    batch_res = (
        sb.table("multi_period_recon_batches")
        .select("*")
        .eq("id", batch_id)
        .limit(1)
        .execute()
    )
    if not batch_res.data:
        raise ValueError(f"Batch {batch_id} not found")

    batch = batch_res.data[0]
    items_res = (
        sb.table("multi_period_recon_batch_items")
        .select("*")
        .eq("batch_id", batch_id)
        .order("period", desc=False)
        .execute()
    )
    batch["items"] = items_res.data or []
    return batch


def fetch_gstr2b_for_batch(batch_id: str, user_id: str | None = None) -> None:
    """Async background worker task to auto-fetch GSTR-2B for all 12 periods.

    Isolates failures per period so OTP/portal errors on one month do not abort others.
    """
    sb = get_supabase()
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]

    sb.table("multi_period_recon_batches").update({
        "status": "fetching",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch_id).execute()

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

        if not has_token or not access_token or not gstin:
            sb.table("multi_period_recon_batch_items").update({
                "status": "failed",
                "error_message": "GSTN not connected or OTP session expired for this client",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).execute()
            failed_count += 1
            continue

        sb.table("multi_period_recon_batch_items").update({
            "status": "fetching",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", item_id).execute()

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

            sb.table("multi_period_recon_batch_items").update({
                "gstr2b_source": "auto_fetch",
                "gstr2b_file_path": r2_key,
                "status": "uploaded",
                "error_message": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).execute()
            completed_count += 1

        except (SandboxGstnError, ValueError, Exception) as exc:
            logger.warning(
                "GSTR-2B fetch failed for batch %s period %s: %s", batch_id, period, exc
            )
            err_msg = exc.message if hasattr(exc, "message") else str(exc)
            sb.table("multi_period_recon_batch_items").update({
                "status": "failed",
                "error_message": err_msg[:500],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).execute()
            failed_count += 1

    final_status = (
        "queued" if failed_count == 0
        else ("partially_failed" if completed_count > 0 else "failed")
    )
    sb.table("multi_period_recon_batches").update({
        "status": final_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch_id).execute()


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

    res = (
        sb.table("multi_period_recon_batch_items")
        .update({
            "pr_source": "manual_upload",
            "pr_file_path": r2_key,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("batch_id", batch_id)
        .eq("period", period)
        .execute()
    )

    return get_batch_with_items(sb, batch_id)


def run_batch(batch_id: str, user_id: str | None = None) -> None:
    """Async background worker task to run batch reconciliation.

    Executes items in strict chronological order (Apr->Mar) to maintain carry-forward integrity.
    """
    sb = get_supabase()
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]

    sb.table("multi_period_recon_batches").update({
        "status": "running",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch_id).execute()

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
            sb.table("multi_period_recon_batch_items").update({
                "status": "failed",
                "error_message": "Missing GSTR-2B or Purchase Register file",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).execute()
            failed_count += 1
            continue

        sb.table("multi_period_recon_batch_items").update({
            "status": "running",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", item_id).execute()

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
                    "pr_r2_key": pr_key,
                    "r2_key": pr_key,
                    "created_at": now,
                    "updated_at": now,
                }).execute()
            else:
                sb.table("reconciliation_run").update({
                    "gstr2b_r2_key": gstr2b_key,
                    "pr_r2_key": pr_key,
                    "status": "uploading",
                    "updated_at": now,
                }).eq("id", run_id).execute()

            # Execute import & matching tasks in-process
            run_import_job.apply(args=[run_id, "gstr2b", gstr2b_key])
            run_import_job.apply(args=[run_id, "purchase_register", pr_key])
            execute_reconciliation.apply(args=[run_id])

            sb.table("multi_period_recon_batch_items").update({
                "reconciliation_run_id": run_id,
                "status": "completed",
                "error_message": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).execute()
            completed_count += 1

        except Exception as exc:
            logger.exception("Batch reconciliation failed for period %s: %s", period, exc)
            sb.table("multi_period_recon_batch_items").update({
                "reconciliation_run_id": run_id,
                "status": "failed",
                "error_message": str(exc)[:500],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", item_id).execute()
            failed_count += 1

    final_status = (
        "completed" if failed_count == 0
        else ("partially_failed" if completed_count > 0 else "failed")
    )
    sb.table("multi_period_recon_batches").update({
        "status": final_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch_id).execute()


def get_batch_summary(sb: Client, batch_id: str) -> dict[str, Any]:
    """Return aggregated FY summary metrics and monthly trend array."""
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]
    fy = batch["financial_year"]

    rollup = assemble_fy_rollup(sb, client_gstin_id=client_id, fy=fy)
    batch["summary"] = rollup
    return batch
