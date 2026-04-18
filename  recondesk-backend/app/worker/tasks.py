"""
Celery tasks for the import pipeline.

Uses Supabase (PostgREST) for DB and boto3 for R2. Chunk inserts use
``upsert(..., ignore_duplicates=True, returning='representation')``;
``len(response.data)`` is treated as the insert count (equivalent to conflict-aware inserts).
"""

from __future__ import annotations

import io
import json
import logging
import re
import traceback
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from celery.exceptions import Retry, SoftTimeLimitExceeded
from postgrest.types import ReturnMethod

from app.config import settings
from app.database import get_supabase
from app.parsers.gstr2b_parser import parse_gstr2b
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)
FINAL_FAILED = "failed"

_RETRYABLE_EXC = (OSError, ConnectionError, TimeoutError, ClientError)


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _download_r2_bytes(key: str) -> bytes:
    c = _r2_client()
    obj = c.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    return obj["Body"].read()


def _r2_copy_then_delete(source_key: str, dest_key: str) -> None:
    c = _r2_client()
    c.copy_object(
        Bucket=settings.R2_BUCKET_NAME,
        CopySource={"Bucket": settings.R2_BUCKET_NAME, "Key": source_key},
        Key=dest_key,
    )
    c.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=source_key)


def _parse_period_bounds(period: str) -> tuple[date, date]:
    y, m = period.split("-")
    yy, mm = int(y), int(m)
    last = monthrange(yy, mm)[1]
    return date(yy, mm, 1), date(yy, mm, last)


def _parse_invoice_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    s = s.replace("Z", "+00:00")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return date_type.fromisoformat(s[:10])
        except ValueError:
            pass
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except ValueError:
        return None


def log_step(
    run_id: str,
    step_name: str,
    status: str,
    error: Optional[BaseException] = None,
    supabase: Optional[Any] = None,
) -> None:
    client = supabase or get_supabase()
    err_details = traceback.format_exc() if error else None
    client.table("job_logs").insert(
        {
            "run_id": run_id,
            "step_name": step_name,
            "status": status,
            "error_details": err_details,
        }
    ).execute()


def _update_run(supabase, run_id: str, fields: dict[str, Any]) -> None:
    supabase.table("reconciliation_run").update(fields).eq("id", run_id).execute()


def _fetch_run(supabase, run_id: str) -> Optional[dict[str, Any]]:
    r = (
        supabase.table("reconciliation_run")
        .select("*")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if r.data:
        return r.data[0]
    return None


def _inc_retry_count(supabase, run_id: str) -> None:
    row = _fetch_run(supabase, run_id)
    if not row:
        return
    n = int(row.get("retry_count") or 0) + 1
    _update_run(supabase, run_id, {"retry_count": n})


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:  # noqa: BLE001
            return str(obj)
    return obj


def _chunk_size(total_rows: int) -> int:
    if total_rows >= 1000:
        return 1000
    if total_rows <= 0:
        return 1
    alt = max(100, total_rows // 10)
    if alt >= total_rows:
        return max(1, total_rows // 10) or 1
    return alt


def _sanity_gstr(
    records: list[dict], period: str, status_message_holder: list[str]
) -> tuple[bool, Optional[dict], Optional[str]]:
    if len(records) == 0:
        sm = "No invoices found after parsing."
        status_message_holder.append(sm)
        return False, {"errors": ["empty_file"]}, sm

    start_d, end_d = _parse_period_bounds(period)
    null_sg = 0
    null_inum = 0
    bad_gstin = 0
    bad_date = 0
    for rec in records:
        sg = rec.get("supplier_gstin")
        inv = rec.get("invoice_number")
        if not sg or (isinstance(sg, str) and not str(sg).strip()):
            null_sg += 1
        if not inv or (isinstance(inv, str) and not str(inv).strip()):
            null_inum += 1
        sgs = str(sg).strip() if sg else ""
        if sgs and not GSTIN_RE.match(sgs):
            bad_gstin += 1
        idate = _parse_invoice_date(rec.get("invoice_date_norm"))
        if idate is None or idate < start_d or idate > end_d:
            bad_date += 1

    issues: list[str] = []
    if null_sg:
        issues.append(f"{null_sg} invoices have null supplier_gstin")
    if null_inum:
        issues.append(f"{null_inum} invoices have null invoice_number")
    if bad_gstin:
        issues.append(f"{bad_gstin} invoices have invalid supplier GSTIN format")
    if bad_date:
        issues.append(f"{bad_date} invoices have dates outside declared period {period}")

    if issues:
        msg = "Sanity check failed: " + "; ".join(issues)
        status_message_holder.append(msg)
        return False, {"issues": issues}, msg

    return True, None, None


def _sanity_pr(
    df: pd.DataFrame,
    period: str,
    status_message_holder: list[str],
) -> tuple[bool, Optional[dict], Optional[str]]:
    if len(df) == 0:
        sm = "No rows in purchase register file."
        status_message_holder.append(sm)
        return False, {"errors": ["empty_file"]}, sm

    start_d, end_d = _parse_period_bounds(period)
    cols = {str(c).strip().lower(): c for c in df.columns}
    inv_date_col = cols.get("invoice_date")
    if not inv_date_col:
        sm = "Missing invoice_date column after header normalisation."
        status_message_holder.append(sm)
        return False, {"errors": ["no_invoice_date"]}, sm

    sg_col = cols.get("supplier_gstin") or cols.get("gstin")
    in_col = cols.get("invoice_number")
    if not sg_col or not in_col:
        sm = "Missing supplier GSTIN or invoice number column."
        status_message_holder.append(sm)
        return False, {"errors": ["missing_columns"]}, sm

    null_sg = 0
    null_inum = 0
    bad_gstin = 0
    bad_date = 0

    for _, row in df.iterrows():
        sg = row.get(sg_col)
        inv = row.get(in_col)
        if pd.isna(sg) or str(sg).strip() == "":
            null_sg += 1
        if pd.isna(inv) or str(inv).strip() == "":
            null_inum += 1
        sgs = str(sg).strip() if not pd.isna(sg) else ""
        if sgs and not GSTIN_RE.match(sgs):
            bad_gstin += 1
        raw_d = row.get(inv_date_col)
        idate = _parse_invoice_date(raw_d)
        if idate is None or idate < start_d or idate > end_d:
            bad_date += 1

    issues: list[str] = []
    if null_sg:
        issues.append(f"{null_sg} rows have null supplier_gstin")
    if null_inum:
        issues.append(f"{null_inum} rows have null invoice_number")
    if bad_gstin:
        issues.append(f"{bad_gstin} rows have invalid supplier GSTIN format")
    if bad_date:
        issues.append(f"{bad_date} rows have invoice dates outside period {period}")

    if issues:
        msg = "Sanity check failed: " + "; ".join(issues)
        status_message_holder.append(msg)
        return False, {"issues": issues}, msg

    return True, None, None


def _rows_gstr2b(
    records: list[dict],
    client_gstin_id: str,
    period: str,
    run_id: str,
) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        inv_dt = _parse_invoice_date(rec.get("invoice_date_norm"))
        out.append(
            {
                "client_gstin_id": client_gstin_id,
                "period": period,
                "supplier_gstin": str(rec.get("supplier_gstin") or "").strip(),
                "invoice_number": str(rec.get("invoice_number") or "").strip(),
                "run_id": run_id,
                "invoice_date": inv_dt.isoformat() if inv_dt else None,
                "payload": _json_safe(rec),
            }
        )
    return out


def _read_pr_dataframe(content: bytes, r2_key: str) -> pd.DataFrame:
    ext = r2_key.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        return pd.read_csv(io.BytesIO(content), dtype=str)
    return pd.read_excel(io.BytesIO(content), dtype=str)


def _normalize_pr_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    lower = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for req in (
        "supplier_gstin",
        "invoice_number",
        "invoice_date",
        "taxable_value",
        "igst",
        "cgst",
        "sgst",
    ):
        if req in lower:
            rename[lower[req]] = req
        elif req == "supplier_gstin" and "gstin" in lower:
            rename[lower["gstin"]] = "supplier_gstin"
    return df.rename(columns=rename)


def _rows_pr(
    df: pd.DataFrame,
    client_gstin_id: str,
    period: str,
    run_id: str,
) -> list[dict]:
    def num(v: Any) -> Optional[float]:
        if pd.isna(v) or v is None or str(v).strip() == "":
            return None
        try:
            return float(str(v).replace(",", ""))
        except ValueError:
            return None

    rows: list[dict] = []
    for _, r in df.iterrows():
        idate = _parse_invoice_date(r.get("invoice_date"))
        rows.append(
            {
                "client_gstin_id": client_gstin_id,
                "period": period,
                "supplier_gstin": str(r.get("supplier_gstin") or "").strip(),
                "invoice_number": str(r.get("invoice_number") or "").strip(),
                "run_id": run_id,
                "invoice_date": idate.isoformat() if idate else None,
                "taxable_value": num(r.get("taxable_value")),
                "igst": num(r.get("igst")),
                "cgst": num(r.get("cgst")),
                "sgst": num(r.get("sgst")),
                "raw": _json_safe(
                    {
                        "invoice_date": r.get("invoice_date"),
                        "taxable_value": r.get("taxable_value"),
                        "igst": r.get("igst"),
                        "cgst": r.get("cgst"),
                        "sgst": r.get("sgst"),
                    }
                ),
            }
        )
    return rows


def _upsert_chunk(
    supabase,
    table: str,
    on_conflict: str,
    chunk: list[dict],
) -> int:
    if not chunk:
        return 0
    resp = (
        supabase.table(table)
        .upsert(
            chunk,
            on_conflict=on_conflict,
            ignore_duplicates=True,
            returning=ReturnMethod.representation,
        )
        .execute()
    )
    return len(resp.data or [])


def run_import_job_impl(self, run_id: str, file_type: str, r2_key: str) -> None:
    supabase = get_supabase()
    run_id_str = str(run_id)
    status_messages: list[str] = []

    run_row = _fetch_run(supabase, run_id_str)
    if not run_row:
        logger.error("Run %s not found", run_id_str)
        return

    try:
        _update_run(supabase, run_id_str, {"status": "importing"})
        log_step(run_id_str, "start", "success", supabase=supabase)

        try:
            raw = _download_r2_bytes(r2_key)
        except _RETRYABLE_EXC as e:
            _inc_retry_count(supabase, run_id_str)
            log_step(run_id_str, "downloading_file", "error", e, supabase=supabase)
            raise self.retry(exc=e, countdown=30)
        except Exception as e:  # noqa: BLE001
            msg = f"Failed to download file from storage: {e}"
            _update_run(
                supabase,
                run_id_str,
                {"status": FINAL_FAILED, "status_message": msg},
            )
            log_step(run_id_str, "downloading_file", "error", e, supabase=supabase)
            return

        log_step(run_id_str, "downloading_file", "success", supabase=supabase)

        client_gstin_id = str(run_row["client_gstin_id"])
        period = str(run_row["period"])
        inserted_records = 0
        failed_records = 0
        processed_rows = 0
        total_records = 0
        invoice_rows: list[dict] = []

        try:
            if file_type == "gstr2b":
                parsed = parse_gstr2b(raw)
                records = parsed.get("records") or []
                total_records = len(records)
            elif file_type == "purchase_register":
                df_raw = _read_pr_dataframe(raw, r2_key)
                df_norm = _normalize_pr_df(df_raw)
                total_records = len(df_norm)
            else:
                raise ValueError(f"Unknown file_type {file_type}")
        except SoftTimeLimitExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            msg = f"Parse failed: {e}"
            status_messages.append(msg)
            _update_run(
                supabase,
                run_id_str,
                {
                    "status": FINAL_FAILED,
                    "status_message": msg,
                    "sanity_report": {"parse_error": str(e)},
                },
            )
            log_step(run_id_str, "parsing_complete", "error", e, supabase=supabase)
            return

        _update_run(supabase, run_id_str, {"total_records": total_records})
        log_step(run_id_str, "parsing_complete", "success", supabase=supabase)

        if file_type == "gstr2b":
            ok, sanity_report, _ = _sanity_gstr(records, period, status_messages)
        else:
            ok, sanity_report, _ = _sanity_pr(df_norm, period, status_messages)

        if not ok:
            sm = status_messages[-1] if status_messages else "Sanity check failed."
            _update_run(
                supabase,
                run_id_str,
                {
                    "status": FINAL_FAILED,
                    "sanity_report": sanity_report or {},
                    "status_message": sm,
                },
            )
            log_step(run_id_str, "sanity_failed", "error", Exception(sm), supabase=supabase)
            return

        log_step(run_id_str, "sanity_passed", "success", supabase=supabase)

        if file_type == "gstr2b":
            invoice_rows = _rows_gstr2b(
                records, client_gstin_id, period, run_id_str
            )
        else:
            invoice_rows = _rows_pr(
                df_norm, client_gstin_id, period, run_id_str
            )

        table = (
            "gstr2b_invoices"
            if file_type == "gstr2b"
            else "purchase_register_invoices"
        )
        conflict_cols = "client_gstin_id,period,supplier_gstin,invoice_number"

        chunk_n = _chunk_size(total_records)
        pos = 0
        while pos < total_records:
            chunk = invoice_rows[pos : pos + chunk_n]
            try:
                ins = _upsert_chunk(supabase, table, conflict_cols, chunk)
                inserted_records += ins
                failed_records += len(chunk) - ins
            except Exception as e:  # noqa: BLE001
                failed_records += len(chunk)
                log_step(run_id_str, "chunk_failed", "error", e, supabase=supabase)

            processed_rows += len(chunk)
            progress = (
                (processed_rows / total_records) * 100 if total_records else 100.0
            )
            _update_run(supabase, run_id_str, {"progress_percent": progress})
            pos += chunk_n

        failure_ratio = (failed_records / total_records) if total_records else 0.0
        if failure_ratio > 0.05:
            final_status = "failed"
        elif failed_records > 0:
            final_status = "partial_success"
        else:
            final_status = "complete"

        log_step(run_id_str, "db_insert_complete", "success", supabase=supabase)

        archive_key = r2_key.replace("uploads/", "archive/", 1)
        try:
            _r2_copy_then_delete(r2_key, archive_key)
            log_step(run_id_str, "file_archived", "success", supabase=supabase)
        except _RETRYABLE_EXC as e:
            _inc_retry_count(supabase, run_id_str)
            log_step(run_id_str, "file_archived", "error", e, supabase=supabase)
            raise self.retry(exc=e, countdown=30)
        except Exception as e:  # noqa: BLE001
            log_step(run_id_str, "file_archived", "error", e, supabase=supabase)
            final_status = FINAL_FAILED
            status_messages.append(f"Archiving failed: {e}")

        if final_status == FINAL_FAILED and status_messages:
            summary_msg = status_messages[-1]
        elif final_status == "complete":
            summary_msg = f"Imported {inserted_records:,} records successfully."
        elif final_status == "partial_success":
            summary_msg = (
                f"Imported {inserted_records:,} of {total_records:,} rows; "
                f"{failed_records:,} rows skipped due to duplicates or errors."
            )
        elif final_status == FINAL_FAILED:
            summary_msg = (
                f"Import failed: more than 5% of rows could not be inserted "
                f"({failed_records:,} of {total_records:,})."
            )
        else:
            summary_msg = f"Import finished with status {final_status}."

        counters: dict[str, Any] = {
            "status": final_status,
            "inserted_records": inserted_records,
            "failed_records": failed_records,
            "progress_percent": 100.0,
            "status_message": summary_msg,
        }
        if file_type == "gstr2b":
            counters["gstr_records_imported"] = inserted_records
        else:
            counters["pr_records_imported"] = inserted_records

        _update_run(supabase, run_id_str, counters)

        stub = (
            supabase.table("reconciliation_run")
            .select("id")
            .eq("r2_key", r2_key)
            .eq("file_type", "purchase_register")
            .limit(1)
            .execute()
        )
        if stub.data:
            _update_run(supabase, stub.data[0]["id"], {"status": final_status})

        if final_status in ("complete", "partial_success"):
            log_step(run_id_str, "job_success", "success", supabase=supabase)
        elif final_status == FINAL_FAILED:
            log_step(
                run_id_str,
                "job_finished_failed",
                "error",
                Exception(summary_msg),
                supabase=supabase,
            )

    except SoftTimeLimitExceeded:
        _update_run(
            supabase,
            run_id_str,
            {
                "status": FINAL_FAILED,
                "status_message": "Time limit exceeded while processing import.",
            },
        )
        log_step(run_id_str, "fatal_error", "error", Exception("timeout"), supabase=supabase)
        raise
    except Retry:
        raise
    except Exception as e:  # noqa: BLE001
        msg = f"Fatal error: {e}"
        _update_run(
            supabase,
            run_id_str,
            {"status": FINAL_FAILED, "status_message": msg},
        )
        log_step(run_id_str, "fatal_error", "error", e, supabase=supabase)
        raise


class _ApiThreadTaskShim:
    """Minimal Celery-like ``self`` for :func:`run_import_job_impl` outside a worker."""

    def retry(self, exc=None, countdown=30):
        raise Retry(exc=exc)


def run_import_job_in_api_thread(run_id: str, file_type: str, r2_key: str) -> None:
    """Run the import pipeline from a FastAPI daemon thread (no broker / worker required)."""
    import time

    try:
        run_import_job_impl(_ApiThreadTaskShim(), run_id, file_type, r2_key)
    except Retry:
        time.sleep(min(30, 5))
        try:
            run_import_job_impl(_ApiThreadTaskShim(), run_id, file_type, r2_key)
        except Retry:
            logger.warning(
                "Import retry exhausted in API thread mode (run_id=%s)",
                run_id,
            )
            supabase = get_supabase()
            _update_run(
                supabase,
                str(run_id),
                {
                    "status": FINAL_FAILED,
                    "status_message": (
                        "Transient storage error. Re-upload or use a Celery worker with Redis."
                    ),
                },
            )


@celery_app.task(
    bind=True,
    max_retries=3,
    soft_time_limit=600,
    time_limit=660,
    name="worker.run_import_job",
)
def run_import_job(self, run_id: str, file_type: str, r2_key: str) -> None:
    run_import_job_impl(self, run_id, file_type, r2_key)
