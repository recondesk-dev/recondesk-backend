"""Celery tasks for import pipeline (R2 + Supabase)."""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

import boto3
from botocore.config import Config
from supabase import Client, create_client

from app.config import get_r2_s3_endpoint_url, get_settings
from app.parsers.gstr2b_parser import parse_gstr2b
from app.parsers.purchase_register_parser import parse_purchase_register
from app.services import client_import_mapping as cim
from app.services.sanity import SanityCheck, run_import_sanity
from app.worker.celery_app import celery_app

_log = logging.getLogger(__name__)

CHUNK_SIZE = 500


def _task_error_detail(exc: BaseException) -> str:
    """Append hints for common Supabase/Postgres errors (visible in status_message)."""
    msg = str(exc)
    low = msg.lower()
    if (
        "22001" in msg
        or "too long" in low
        or "character varying" in low
        or "value too long" in low
    ):
        msg += (
            " Hint: `client_gstin_id` must store UUIDs (36 chars). "
            "Run `scripts/fix_client_gstin_id.sql` in the Supabase SQL editor."
        )
    if "does not exist" in low and "relation" in low:
        msg += (
            " Hint: run `scripts/setup_gstr_pr_tables.sql` in Supabase SQL Editor "
            "(creates gstr_records / pr_records)."
        )
    if "permission denied" in low or "rls" in low:
        msg += " Hint: use SUPABASE_SERVICE_ROLE_KEY in the API (bypasses RLS)."
    return msg


def _supabase() -> Client:
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)


def _s3():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=get_r2_s3_endpoint_url(),
        aws_access_key_id=s.R2_ACCESS_KEY_ID,
        aws_secret_access_key=s.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _json_safe(obj: Any) -> Any:
    """JSONB-safe values: no NaN/Inf (Postgres JSON rejects them), no raw Decimal."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, Decimal):
        try:
            f = float(obj)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except Exception:
            return str(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def _sanity_failure_message(checks: list[SanityCheck]) -> str:
    bad = [c for c in checks if c.severity == "error" and not c.passed]
    if not bad:
        return "Sanity checks failed"
    parts: list[str] = []
    for c in bad[:8]:
        d = (c.detail or "")[:200]
        parts.append(f"{c.name}: {d}")
    return "Sanity checks failed — " + " | ".join(parts)


def _sanity_checks_to_json(checks: list[SanityCheck]) -> list[dict[str, Any]]:
    return [
        {
            "name": c.name,
            "passed": c.passed,
            "detail": c.detail,
            "severity": c.severity,
            "affected_records": _json_safe(c.affected_records),
        }
        for c in checks
    ]


def _gstr_records_for_sanity(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        items = rec.get("items") or []
        taxable = sum(int(i.get("taxable_value_paise") or 0) for i in items)
        if not taxable:
            taxable = int(rec.get("invoice_value_paise") or 0)
        cgst = sum(int(i.get("cgst_paise") or 0) for i in items)
        sgst = sum(int(i.get("sgst_paise") or 0) for i in items)
        igst = sum(int(i.get("igst_paise") or 0) for i in items)
        total_tax = cgst + sgst + igst
        tr = None
        if items:
            tr = items[0].get("tax_rate")
        out.append(
            {
                "gstin": rec.get("supplier_gstin_norm") or rec.get("supplier_gstin") or "",
                "invoice_number": rec.get("invoice_number"),
                "invoice_number_normalized": rec.get("invoice_number_norm")
                or rec.get("invoice_number"),
                "invoice_date": rec.get("invoice_date_norm"),
                "taxable_amount_paise": taxable,
                "tax_rate": tr,
                "total_tax_paise": total_tax,
                "cgst_paise": cgst,
                "sgst_paise": sgst,
                "igst_paise": igst,
            }
        )
    return out


def _load_and_normalize_gstr2b_body_for_parse(
    body: bytes,
    *,
    filename: str | None = None,
    fallback_buyer_gstin: str | None = None,
    fallback_period: str | None = None,
) -> dict[str, Any]:
    from app.parsers.gstr2b_excel import load_gstr2b_upload_payload
    from app.parsers.gstr2b_parser import (
        _UNSUPPORTED_GSTR2B_SCHEMA,
        is_alt_gstr2b_schema,
        normalize_alt_2b_schema,
        normalize_gstr2b_payload,
    )

    data = load_gstr2b_upload_payload(
        body,
        filename,
        fallback_buyer_gstin=fallback_buyer_gstin,
        fallback_period=fallback_period,
    )
    if "data" not in data:
        if is_alt_gstr2b_schema(data):
            data = normalize_alt_2b_schema(
                data,
                fallback_buyer_gstin=fallback_buyer_gstin,
                fallback_period=fallback_period,
            )
        else:
            raise ValueError(_UNSUPPORTED_GSTR2B_SCHEMA)
    data = normalize_gstr2b_payload(data)
    root = data.get("data")
    if not isinstance(root, dict):
        raise ValueError("invalid_data_structure")
    if not root.get("rtnprd"):
        raise ValueError("Invalid GSTR2B: missing rtnprd")
    return data


def _update_run(
    client: Client,
    run_id: str,
    fields: dict[str, Any],
) -> None:
    client.table("reconciliation_run").update(fields).eq("id", run_id).execute()
    # Mirror engine progress into reconciliation_import_runs so the poll endpoint stays live.
    # reconciliation_import_runs uses the same run_id; this is a best-effort write (non-fatal).
    if "progress_percent" in fields or "status_message" in fields:
        try:
            wiz: dict[str, Any] = {}
            if "progress_percent" in fields:
                wiz["progress_pct"] = int(fields["progress_percent"])
            if "status_message" in fields:
                wiz["status_message"] = fields["status_message"]
            if "updated_at" in fields:
                wiz["updated_at"] = fields["updated_at"]
            if wiz:
                client.table("reconciliation_import_runs").update(wiz).eq("id", run_id).execute()
        except Exception as exc:
            _log.warning(
                "Failed to mirror progress to reconciliation_import_runs for run_id=%s: %s",
                run_id,
                exc,
            )


class ImportCancelledException(Exception):
    """Raised when a running import is cancelled by the user."""
    pass


def _bulk_insert(
    client: Client,
    table: str,
    rows: list[dict[str, Any]],
    on_progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    total = len(rows)
    if total == 0:
        if on_progress:
            try:
                on_progress(0, 0)
            except Exception as exc:
                _log.warning("Progress callback failed on empty insert (non-fatal): %s", exc)
        return

    FLUSH_ROW_THRESHOLD = 5000
    FLUSH_TIME_THRESHOLD_SEC = 3.0

    last_flush_count = 0
    last_flush_time = time.monotonic()

    # Initial check before any batch
    if is_cancelled and is_cancelled():
        _log.info("[WORKER] Bulk insert for %s aborted due to run cancellation (before start)", table)
        raise ImportCancelledException("Import cancelled by user")

    for i in range(0, total, CHUNK_SIZE):
        chunk = rows[i : i + CHUNK_SIZE]
        try:
            client.table(table).insert(chunk).execute()
            _log.info(f"[WORKER] Inserted {table} batch {i//CHUNK_SIZE + 1} ({len(chunk)} rows)")
        except Exception as exc:
            raise RuntimeError(
                f"Insert into {table} failed ({len(chunk)} row(s), offset {i}): {exc}"
            ) from exc

        inserted = min(i + len(chunk), total)
        now = time.monotonic()

        should_flush = (
            (inserted - last_flush_count >= FLUSH_ROW_THRESHOLD)
            or (now - last_flush_time >= FLUSH_TIME_THRESHOLD_SEC)
            or (inserted == total)
        )

        if should_flush:
            if is_cancelled and is_cancelled():
                _log.info("[WORKER] Bulk insert for %s aborted due to run cancellation", table)
                raise ImportCancelledException("Import cancelled by user")
            if on_progress:
                try:
                    on_progress(inserted, total)
                except Exception as exc:
                    _log.warning("Progress callback failed (non-fatal): %s", exc)
            last_flush_count = inserted
            last_flush_time = now


@celery_app.task(
    name="worker.run_import_job",
    max_retries=0,
    soft_time_limit=300,
    time_limit=360,
)
def run_import_job(run_id: str, file_type: str, r2_key: str) -> None:
    print(f"[WORKER] START run_id={run_id}")

    print("=== DEBUG DB URL ===")
    print(get_settings().SUPABASE_URL)
    print("====================")

    client = _supabase()
    bucket = get_settings().R2_BUCKET_NAME
    s3 = _s3()
    now = datetime.now(timezone.utc).isoformat()

    try:
        run_res = (
            client.table("reconciliation_run")
            .select("client_gstin_id, period")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        if not run_res.data:
            raise RuntimeError(f"Run {run_id} does not exist")
        run_data = run_res.data[0] or {}
        client_gstin_id = run_data.get("client_gstin_id")
        period = run_data.get("period")

        _update_run(
            client,
            run_id,
            {
                "status": "importing",
                "progress_percent": 5,
                "updated_at": now,
            },
        )

        obj = s3.get_object(Bucket=bucket, Key=r2_key)
        body = obj["Body"].read()

        client_gstin_fallback = ""
        if client_gstin_id:
            cg_res = (
                client.table("client_gstins")
                .select("gstin")
                .eq("id", str(client_gstin_id))
                .limit(1)
                .execute()
            )
            if cg_res.data and cg_res.data[0].get("gstin") is not None:
                client_gstin_fallback = str(cg_res.data[0]["gstin"]).strip()

        pr_sheet_meta: dict[str, Any] | None = None

        if file_type == "gstr2b":
            gstr_payload = _load_and_normalize_gstr2b_body_for_parse(
                body,
                filename=os.path.basename(r2_key) if r2_key else None,
                fallback_buyer_gstin=client_gstin_fallback or None,
                fallback_period=period,
            )
            parsed = parse_gstr2b(
                gstr_payload,
                fallback_buyer_gstin=client_gstin_fallback or None,
                fallback_period=period,
            )
            records = list(parsed.get("records") or [])
            for_sanity = _gstr_records_for_sanity(records)

            # Persist ISD/IMPG detection for results-page banner (not reconciled).
            try:
                from app.parsers.gstr2b_parser import format_isd_impg_warning
                from app.services.reconciliation_import_wizard.wizard_service import (
                    merge_isd_impg_into_run_summary,
                )

                isd_n = int(parsed.get("isd_count") or 0)
                impg_n = int(parsed.get("impg_count") or 0)
                prior_rs = (
                    client.table("reconciliation_run")
                    .select("run_summary")
                    .eq("id", run_id)
                    .limit(1)
                    .execute()
                )
                existing_rs = (
                    (prior_rs.data or [{}])[0].get("run_summary")
                    if prior_rs.data
                    else None
                )
                if not isinstance(existing_rs, dict):
                    existing_rs = {}
                _update_run(
                    client,
                    run_id,
                    {
                        "run_summary": merge_isd_impg_into_run_summary(
                            existing_rs,
                            isd_count=isd_n,
                            impg_count=impg_n,
                            warning=format_isd_impg_warning(isd_n, impg_n),
                        ),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception:
                _log.exception(
                    "Failed to persist ISD/IMPG detection on run_summary for %s",
                    run_id,
                )
            
            parsed_period = str(parsed.get("period", ""))
            if parsed_period and len(parsed_period) >= 7:
                new_period = parsed_period[:7]
                if new_period != period:
                    _log.info("Updating run %s period from %s to %s based on GSTR-2B", run_id, period, new_period)
                    period = new_period
                    _update_run(client, run_id, {"period": period})
            if parsed.get("buyer_gstin_source") == "placeholder":
                _log.warning(
                    "GSTR-2B alt schema for run %s has no buyer GSTIN in file or "
                    "client_gstins record — using placeholder unique_key buyer",
                    run_id,
                )
        elif file_type == "purchase_register":
            name = os.path.basename(r2_key) or "purchase.xlsx"
            parse_body = body
            parse_name = name
            from app.parsers.purchase_register_parser import list_candidate_pr_sheet_names

            # Cheap sheet-name peek (no header scan / full re-parse). Full mapping
            # happens inside parse_purchase_register once.
            candidate_sheets = list_candidate_pr_sheet_names(body, name)
            multi_sheet = len(candidate_sheets) > 1
            if multi_sheet:
                # Keep the original workbook so parse_purchase_register can
                # auto-detect and combine every mappable sheet. Reshaping to a
                # single-sheet CSV would silently drop the rest.
                _log.info(
                    "PR multi-sheet workbook (%d candidate sheets): %s — skipping "
                    "client_import_mappings reshape",
                    len(candidate_sheets),
                    candidate_sheets,
                )
            else:
                # Apply saved client column mapping before normalization/parser.
                try:
                    saved = cim.get_mappings_or_none(client, str(client_gstin_id))
                except Exception:  # noqa: BLE001
                    _log.exception(
                        "Failed loading client_import_mappings for %s", client_gstin_id
                    )
                    saved = None
                if saved:
                    try:
                        headers = cim.extract_headers_from_file(body, name)
                    except Exception:  # noqa: BLE001
                        headers = []
                    if headers and cim.mapping_covers_headers(saved, headers):
                        parse_body, parse_name = cim.reshape_file_with_mapping(
                            body, name, saved
                        )
                        _log.info(
                            "Applied client_import_mappings for client_gstin_id=%s "
                            "(%d fields)",
                            client_gstin_id,
                            len(saved),
                        )
                    elif headers and not cim.columns_match_expected_schema(headers):
                        raise ValueError(
                            "Column mapping required: saved mapping does not cover "
                            f"file headers {headers}"
                        )
                else:
                    try:
                        headers = cim.extract_headers_from_file(body, name)
                    except Exception:  # noqa: BLE001
                        headers = []
                    if headers and not cim.columns_match_expected_schema(headers):
                        raise ValueError(
                            "Column mapping required: columns do not match expected "
                            f"schema. Detected headers: {headers}"
                        )
            pr_t0 = time.perf_counter()
            pr = parse_purchase_register(
                parse_body, parse_name, client_gstin=client_gstin_fallback or None
            )
            _log.info(
                "PR parse finished run_id=%s elapsed=%.2fs records=%d "
                "missing_invoice=%s sheets_used=%s",
                run_id,
                time.perf_counter() - pr_t0,
                len(pr.get("records") or []),
                pr.get("missing_invoice_number_count"),
                [s.get("sheet") for s in (pr.get("sheets_used") or [])],
            )
            if not pr.get("success"):
                errs = "; ".join(pr.get("errors") or ["parse failed"])
                raise ValueError(errs)
            records = list(pr.get("records") or [])
            for_sanity = records
            pr_sheet_meta = {
                "sheets_used": list(pr.get("sheets_used") or []),
                "sheets_skipped": list(pr.get("sheets_skipped") or []),
                "warnings": list(pr.get("warnings") or []),
                "missing_invoice_number_count": int(
                    pr.get("missing_invoice_number_count") or 0
                ),
            }
            if pr_sheet_meta["warnings"]:
                _log.warning(
                    "PR parse sheet notes run_id=%s: %s",
                    run_id,
                    " | ".join(pr_sheet_meta["warnings"]),
                )
        else:
            raise ValueError(f"unknown file_type: {file_type}")

        print("[WORKER] Input validated")

        if not client_gstin_id or not period:
            raise ValueError("reconciliation_run missing client_gstin_id or period")

        _update_run(
            client,
            run_id,
            {"progress_percent": 40, "updated_at": datetime.now(timezone.utc).isoformat()},
        )

        checks = run_import_sanity(
            for_sanity,
            expected_count=len(for_sanity),
            source_type=file_type,
            client_gstin=client_gstin_fallback or None,
        )
        sanity_json = _sanity_checks_to_json(checks)
        if file_type == "purchase_register" and pr_sheet_meta is not None:
            sheets_used = pr_sheet_meta["sheets_used"]
            sheets_skipped = pr_sheet_meta["sheets_skipped"]
            if sheets_used or sheets_skipped:
                used_txt = ", ".join(
                    f"{s.get('sheet')} ({int(s.get('records') or 0)})"
                    for s in sheets_used
                ) or "none"
                skipped_txt = ", ".join(
                    f"{s.get('sheet')} ({s.get('reason')})"
                    for s in sheets_skipped
                )
                detail = f"Sheets used: {used_txt}."
                if skipped_txt:
                    detail += f" Sheets skipped: {skipped_txt}."
                if len(sheets_used) > 1:
                    detail += (
                        " Multiple sheets were combined; overlapping invoices "
                        "may be double-counted."
                    )
                sanity_json.append(
                    {
                        "name": "Excel sheets",
                        "passed": True,
                        "detail": detail,
                        "severity": (
                            "warning"
                            if len(sheets_used) > 1 or sheets_skipped
                            else "info"
                        ),
                        "affected_records": [],
                    }
                )
            missing_inv = int(pr_sheet_meta.get("missing_invoice_number_count") or 0)
            if missing_inv > 0:
                warn_detail = (
                    f"{missing_inv} skipped: missing invoice number. "
                    "These purchase register rows cannot be matched to GSTR-2B."
                )
                sheet_warns = [
                    w
                    for w in (pr_sheet_meta.get("warnings") or [])
                    if "invoice number" in (w or "").lower()
                ]
                if sheet_warns:
                    warn_detail += " " + " | ".join(sheet_warns[:3])
                sanity_json.append(
                    {
                        "name": "PR invoice number",
                        "passed": False,
                        "detail": warn_detail,
                        "severity": "warning",
                        "affected_records": [],
                    }
                )
            elif pr_sheet_meta.get("warnings"):
                # Surface non-fatal parse notes (e.g. multi-sheet combine) even when
                # invoice numbers mapped successfully.
                note = " | ".join(pr_sheet_meta["warnings"][:3])
                if "Combined" in note or "Sheets skipped" in note:
                    pass  # already covered by Excel sheets check above
                else:
                    sanity_json.append(
                        {
                            "name": "Purchase register parse",
                            "passed": True,
                            "detail": note,
                            "severity": "info",
                            "affected_records": [],
                        }
                    )
        blocking = any(
            c.severity == "error" and not c.passed for c in checks
        )
        if blocking:
            _log.warning(
                "Sanity reported errors (non-fatal; sanity_report saved on completion): %s",
                _sanity_failure_message(checks),
            )

        insert_table = "gstr_records" if file_type == "gstr2b" else "pr_records"

        # 1. Guard against completed, matching, or locked runs
        curr_run = (
            client.table("reconciliation_run")
            .select("status, is_locked")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        curr_status = str((curr_run.data or [{}])[0].get("status") or "").strip().lower()
        is_locked = bool((curr_run.data or [{}])[0].get("is_locked"))

        _TERMINAL_STATUSES = {"matching", "processing", "completed", "final", "finalized"}
        if is_locked or curr_status in _TERMINAL_STATUSES:
            raise RuntimeError(
                f"Cannot import into run {run_id} in status '{curr_status}' (run is finalized, locked, or processing)"
            )

        # 2. Guarded staging deletion for this run_id (idempotent retry)
        try:
            client.table(insert_table).delete().eq("run_id", run_id).execute()
            _log.info(
                "[WORKER] Purged prior staging records from %s for run_id=%s",
                insert_table,
                run_id,
            )
        except Exception as purge_exc:
            _log.warning(
                "Failed to purge prior staging records from %s for run_id=%s (continuing): %s",
                insert_table,
                run_id,
                purge_exc,
            )

        rows = [
            {
                "run_id": run_id,
                "client_gstin_id": client_gstin_id,
                "period": period,
                "record_data": _json_safe(rec),
            }
            for rec in records
        ]
        print(
            f"[WORKER] Inserting {len(rows)} rows into {insert_table}"
        )
        record_label = (
            "purchase"
            if file_type == "purchase_register"
            else ("GSTR-2B" if file_type == "gstr2b" else file_type)
        )
        last_reported_pct = 40

        def _on_insert_progress(inserted: int, total: int) -> None:
            nonlocal last_reported_pct
            if total <= 0:
                pct = 40
            else:
                pct = max(last_reported_pct, min(85, 40 + int((inserted / total) * 45)))
            last_reported_pct = pct
            msg = f"Importing {record_label} records ({inserted:,} / {total:,})…"
            _update_run(
                client,
                run_id,
                {
                    "progress_percent": pct,
                    "status_message": msg,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        def _check_cancelled() -> bool:
            try:
                wiz_res = (
                    client.table("reconciliation_import_runs")
                    .select("status")
                    .eq("id", run_id)
                    .limit(1)
                    .execute()
                )
                if (
                    wiz_res.data
                    and str(wiz_res.data[0].get("status") or "").strip().lower()
                    == "cancelled"
                ):
                    return True

                r_res = (
                    client.table("reconciliation_run")
                    .select("status")
                    .eq("id", run_id)
                    .limit(1)
                    .execute()
                )
                if (
                    r_res.data
                    and str(r_res.data[0].get("status") or "").strip().lower()
                    == "cancelled"
                ):
                    return True
            except Exception as exc:
                _log.warning(
                    "Failed to check cancellation status for run_id=%s: %s",
                    run_id,
                    exc,
                )
            return False

        if rows:
            _bulk_insert(
                client,
                insert_table,
                rows,
                on_progress=_on_insert_progress,
                is_cancelled=_check_cancelled,
            )

        count = len(rows)
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 90,
                "status_message": f"Finalizing {record_label} import…",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        patch: dict[str, Any] = {
            "progress_percent": 100,
            "sanity_report": sanity_json,
            "status_message": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if file_type == "gstr2b":
            patch["gstr_records_imported"] = count
        else:
            patch["pr_records_imported"] = count

        _update_run(client, run_id, patch)

        acc = (
            client.table("reconciliation_run")
            .select("gstr_records_imported, pr_records_imported")
            .eq("id", run_id)
            .single()
            .execute()
        )
        ad = acc.data or {}
        gi = int(ad.get("gstr_records_imported") or 0)
        pi = int(ad.get("pr_records_imported") or 0)
        if gi > 0 and pi > 0:
            post_status = "READY"
        elif gi > 0:
            post_status = "GSTR_IMPORT_COMPLETE"
        elif pi > 0:
            post_status = "PURCHASE_IMPORT_COMPLETE"
        else:
            post_status = "complete"
        _update_run(
            client,
            run_id,
            {
                "status": post_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    except ImportCancelledException:
        _log.info(
            "[WORKER] run_import_job cancelled by user for run_id=%s; cleaning up partial records",
            run_id,
        )
        target_tbl = "gstr_records" if file_type == "gstr2b" else "pr_records"
        try:
            client.table(target_tbl).delete().eq("run_id", run_id).execute()
            _log.info(
                "[WORKER] Purged partial records from %s for cancelled run_id=%s",
                target_tbl,
                run_id,
            )
        except Exception as clean_exc:
            _log.warning(
                "Failed to clean up partial records on cancellation for run_id=%s: %s",
                run_id,
                clean_exc,
            )
        return
    except Exception as exc:
        print(f"[WORKER] ERROR: {str(exc)}")
        _log.exception("run_import_job failed for run_id=%s", run_id)
        _update_run(
            client,
            run_id,
            {
                "status": "failed",
                "status_message": _task_error_detail(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        raise
