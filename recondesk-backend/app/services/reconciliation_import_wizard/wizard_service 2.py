"""Persistence and domain logic for the import wizard."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException, status
from supabase import Client

from app.config import settings
from app.database import get_supabase
from app.parsers.purchase_register_parser import (
    ParseError,
    detect_column_mapping,
    _find_best_header_from_raw,
)
from app.services.reconciliation_import_wizard import state_machine

_log = logging.getLogger(__name__)

T_RUNS = "reconciliation_import_runs"
T_AUDIT = "reconciliation_import_run_audit_log"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

STANDARD_FIELDS = [
    "gstin",
    "invoice_number",
    "invoice_date",
    "taxable_value",
    "cgst",
    "sgst",
    "igst",
    "cess",
    "total_tax",
    "supplier_name",
]

# Parser field names from ``detect_column_mapping`` → wizard ``standard_field`` keys.
_PARSER_TO_WIZARD_FIELD: dict[str, str] = {
    "gstin": "gstin",
    "invoice_number": "invoice_number",
    "invoice_date": "invoice_date",
    "taxable_amount": "taxable_value",
    "cgst": "cgst",
    "sgst": "sgst",
    "igst": "igst",
    "cess": "cess",
    "total_tax": "total_tax",
    "supplier_name": "supplier_name",
}


def _wizard_columns_from_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Build wizard column-mapping rows using the purchase-register parser detector."""
    try:
        parser_mapping = detect_column_mapping(df)
    except ParseError:
        parser_mapping = {}

    wizard_detected: dict[str, str] = {
        wizard_field: parser_mapping[parser_field]
        for parser_field, wizard_field in _PARSER_TO_WIZARD_FIELD.items()
        if parser_field in parser_mapping
    }

    columns_out: list[dict[str, Any]] = []
    for field in STANDARD_FIELDS:
        detected = wizard_detected.get(field)
        confidence = "high" if detected else "not_found"
        samples: list[str] = []
        if detected and detected in df.columns:
            ser = df[detected].dropna().head(3)
            samples = [str(x) for x in ser.tolist()]
        columns_out.append(
            {
                "standard_field": field,
                "detected_column": detected,
                "confidence": confidence,
                "sample_values": samples,
                "confirmed": confidence == "high",
            }
        )
    return columns_out


def _r2():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def audit(sb: Client, run_id: str, user_id: str, event: str, detail: Optional[dict] = None) -> None:
    sb.table(T_AUDIT).insert(
        {
            "run_id": run_id,
            "user_id": user_id,
            "event": event,
            "detail": detail or {},
        }
    ).execute()


def transition_run(
    sb: Client,
    run_id: str,
    user_id: str,
    new_status: str,
    *,
    extra_patch: Optional[dict] = None,
    audit_event: Optional[str] = None,
    audit_detail: Optional[dict] = None,
) -> dict:
    row = (
        sb.table(T_RUNS)
        .select("*")
        .eq("id", run_id)
        .single()
        .execute()
    ).data
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    old = row["status"]
    try:
        state_machine.assert_transition_allowed(old, new_status)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    patch = {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if extra_patch:
        patch.update(extra_patch)
    res = sb.table(T_RUNS).update(patch).eq("id", run_id).execute()
    data = (res.data or [row])[0]
    audit(
        sb,
        run_id,
        user_id,
        audit_event or f"status_{new_status}",
        {"from": old, "to": new_status, **(audit_detail or {})},
    )
    return data


def delete_r2_keys(keys: list[str]) -> None:
    if not keys:
        return
    c = _r2()
    for k in keys:
        if not k:
            continue
        try:
            c.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=k)
        except ClientError as e:
            _log.warning("R2 delete failed %s: %s", k, e)


def verify_r2_sha256(key: str, expected_hex: str, max_bytes: int = MAX_UPLOAD_BYTES) -> int:
    c = _r2()
    try:
        o = c.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    except ClientError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Object not found in storage") from e
    body = o["Body"].read()
    if len(body) > max_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large")
    digest = hashlib.sha256(body).hexdigest()
    if digest.lower() != (expected_hex or "").lower():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File hash mismatch")
    return len(body)


def presign_put(key: str, content_type: str, expires: int = 3600) -> str:
    c = _r2()
    return c.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires,
    )


def fetch_run(sb: Client, run_id: str) -> dict:
    r = sb.table(T_RUNS).select("*").eq("id", run_id).single().execute()
    if not r.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return r.data


def assert_client_access(sb: Client, client_id: str, user_id: str) -> dict:
    c = (
        sb.table("client_gstins")
        .select("id, firm_owner_id, assigned_to, gstin, trade_name, is_active")
        .eq("id", client_id)
        .single()
        .execute()
    ).data
    if not c or not c.get("is_active", True):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    fo = str(c.get("firm_owner_id") or "").strip()
    assigned = str(c.get("assigned_to") or "").strip()
    user_str = str(user_id or "").strip()
    if fo == user_str or assigned == user_str:
        return c
    from app.services.firm_access import user_can_access_firm
    if fo and user_can_access_firm(sb, {"id": user_str}, fo):
        return c
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")


def another_processing_run(sb: Client, client_id: str, period_iso: str, exclude_run_id: str) -> bool:
    q = (
        sb.table(T_RUNS)
        .select("id")
        .eq("client_id", client_id)
        .eq("period", period_iso)
        .eq("status", "processing")
        .neq("id", exclude_run_id)
        .limit(1)
        .execute()
    )
    return bool(q.data)


def run_sanity_gstr2b_json(
    raw: bytes,
    *,
    filename: str | None = None,
    fallback_buyer_gstin: str | None = None,
    fallback_period: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return checks list per API contract and parsed invoice record count.

    Accepts portal/alt JSON or third-party ``.xls`` / ``.xlsx`` (same flat schema).
    """
    from app.parsers.gstr2b_excel import (
        is_gstr2b_excel_bytes,
        is_gstr2b_excel_filename,
        load_gstr2b_upload_payload,
    )
    from app.parsers.gstr2b_parser import (
        BUYER_GSTIN_MISSING_WARNING,
        BUYER_GSTIN_SOURCE_PLACEHOLDER,
        parse_gstr2b,
    )

    checks: list[dict[str, Any]] = []
    name = filename or ""
    is_excel = is_gstr2b_excel_filename(name) or (
        not name.lower().endswith(".json") and is_gstr2b_excel_bytes(raw)
    )

    try:
        payload = load_gstr2b_upload_payload(
            raw,
            name,
            fallback_buyer_gstin=fallback_buyer_gstin,
            fallback_period=fallback_period,
        )
    except ValueError as exc:
        detail = str(exc)
        if is_excel:
            detail = f"File is not a readable GSTR-2B Excel export. ({exc})"
        elif "invalid_json" in detail or "invalid_utf8" in detail:
            detail = "File is not valid JSON or GSTR-2B Excel."
        checks.append(
            {
                "id": "file_parse",
                "label": "Valid file",
                "status": "error",
                "detail": detail,
                "affected_records": [],
            }
        )
        return checks, 0

    checks.append(
        {
            "id": "file_parse",
            "label": "Valid file",
            "status": "pass",
            "detail": "Excel GSTR-2B export" if is_excel else "JSON GSTR-2B export",
            "affected_records": [],
        }
    )

    try:
        parsed = parse_gstr2b(
            payload,
            fallback_buyer_gstin=fallback_buyer_gstin,
            fallback_period=fallback_period,
        )
    except ValueError as exc:
        checks.append(
            {
                "id": "records",
                "label": "Records present",
                "status": "error",
                "detail": str(exc),
                "affected_records": [],
            }
        )
        return checks, 0

    record_count = int(parsed.get("total_parsed") or 0)
    skipped = int(parsed.get("total_skipped") or 0)

    breakdown_labeled = (
        parsed.get("metrics", {}).get("skip_breakdown_labeled") or []
    )
    breakdown_text = _format_skip_breakdown(breakdown_labeled)
    affected = _skip_breakdown_affected_records(breakdown_labeled)

    if record_count == 0:
        detail = "No B2B/CDN invoices parsed."
        if skipped:
            detail += f" {skipped} invoice(s) skipped — check export format."
            if breakdown_text:
                detail += f" Breakdown: {breakdown_text}."
        checks.append(
            {
                "id": "records",
                "label": "Records present",
                "status": "warning",
                "detail": detail,
                "affected_records": affected,
                # Empty/incomplete GSTR-2B is high-risk — must acknowledge
                # before continuing (covers the historic "all CDNR skipped"
                # Unsupported-schema case).
                "requires_acknowledgment": True,
                "acknowledged": False,
            }
        )
    else:
        detail = f"{record_count} invoice(s) parsed."
        if skipped:
            detail += f" {skipped} skipped."
            if breakdown_text:
                detail += f" Breakdown: {breakdown_text}."
        checks.append(
            {
                "id": "records",
                "label": "Records present",
                "status": "pass",
                "detail": detail,
                "affected_records": affected,
            }
        )

    if parsed.get("buyer_gstin_source") == BUYER_GSTIN_SOURCE_PLACEHOLDER:
        checks.append(
            {
                "id": "buyer_gstin",
                "label": "Buyer GSTIN",
                "status": "warning",
                "detail": BUYER_GSTIN_MISSING_WARNING,
                "affected_records": [],
            }
        )

    isd_count = int(
        parsed.get("isd_count")
        or (parsed.get("metrics") or {}).get("isd_count")
        or 0
    )
    impg_count = int(
        parsed.get("impg_count")
        or (parsed.get("metrics") or {}).get("impg_count")
        or 0
    )
    isd_impg_check = build_isd_impg_unprocessed_check(isd_count, impg_count)
    if isd_impg_check is not None:
        checks.append(isd_impg_check)

    return checks, record_count


def _format_skip_breakdown(breakdown_labeled: list[dict[str, Any]]) -> str:
    """Render the parser's skip breakdown as ``"Label (n), …"`` for UI detail text."""
    return ", ".join(
        f"{item.get('label', item.get('category', 'Other'))} ({int(item.get('count', 0))})"
        for item in breakdown_labeled
        if int(item.get("count", 0)) > 0
    )


def _skip_breakdown_affected_records(
    breakdown_labeled: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose the breakdown as structured affected_records rows for the wizard UI."""
    return [
        {
            "category": item.get("category"),
            "label": item.get("label", item.get("category")),
            "count": int(item.get("count", 0)),
        }
        for item in breakdown_labeled
        if int(item.get("count", 0)) > 0
    ]


# ---------------------------------------------------------------------------
# High-risk wizard acknowledgments
# ---------------------------------------------------------------------------
# Checks with ``requires_acknowledgment: true`` block Continue / detect-columns
# / start until the user acknowledges them. Promote new risks by setting the
# flag on the check — do not hardcode check IDs in the gate.

MULTI_SHEET_COMBINE_CHECK_ID = "multi_sheet_combine"
MISSING_INVOICE_CHECK_ID = "missing_invoice_number"
ISD_IMPG_UNPROCESSED_CHECK_ID = "isd_impg_unprocessed"


def build_multi_sheet_combine_check(
    sheets_used: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Build the blocking warning check when 2+ sheets were combined, else None."""
    used = [s for s in (sheets_used or []) if isinstance(s, dict) and s.get("sheet")]
    if len(used) < 2:
        return None
    used_names = ", ".join(
        f"{s.get('sheet')} ({int(s.get('records') or 0)})" for s in used
    )
    return {
        "id": MULTI_SHEET_COMBINE_CHECK_ID,
        "label": "Multiple Excel sheets combined",
        "status": "warning",
        "detail": (
            f"Combined {len(used)} sheets into one purchase register: {used_names}. "
            "If sheets overlap, invoices may be double-counted."
        ),
        "affected_records": [
            {
                "gstin": "",
                "invoice_number": str(s.get("sheet") or ""),
            }
            for s in used
        ],
        "requires_acknowledgment": True,
        "acknowledged": False,
    }


def build_missing_invoice_number_check(
    missing_count: int,
    parse_warnings: list[str] | None = None,
) -> dict[str, Any] | None:
    """Blocking warning when PR rows lack invoice numbers after mapping."""
    n = int(missing_count or 0)
    if n <= 0:
        return None
    detail = f"{n} skipped: missing invoice number"
    inv_notes = [
        w
        for w in (parse_warnings or [])
        if "invoice number" in (w or "").lower()
    ]
    if inv_notes:
        detail += ". " + inv_notes[0]
    else:
        detail += (
            ". These purchase register rows cannot be matched to GSTR-2B "
            "and may skew Missed ITC / ITC at Risk."
        )
    return {
        "id": MISSING_INVOICE_CHECK_ID,
        "label": "Missing invoice numbers",
        "status": "warning",
        "detail": detail,
        "affected_records": [],
        "requires_acknowledgment": True,
        "acknowledged": False,
    }


def build_isd_impg_unprocessed_check(
    isd_count: int,
    impg_count: int,
) -> dict[str, Any] | None:
    """Blocking warning when GSTR-2B contains ISD / IMPG lines we do not reconcile."""
    from app.parsers.gstr2b_parser import format_isd_impg_warning

    isd_n = int(isd_count or 0)
    impg_n = int(impg_count or 0)
    detail = format_isd_impg_warning(isd_n, impg_n)
    if not detail:
        return None
    return {
        "id": ISD_IMPG_UNPROCESSED_CHECK_ID,
        "label": "ISD / Import of goods not reconciled",
        "status": "warning",
        "detail": detail,
        "affected_records": [],
        "requires_acknowledgment": True,
        "acknowledged": False,
        "isd_present": isd_n > 0,
        "isd_count": isd_n,
        "impg_present": impg_n > 0,
        "impg_count": impg_n,
    }


def isd_impg_fields_from_checks(
    sanity_check_results: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Pull ISD/IMPG detection fields out of sanity checks for run_summary."""
    for item in sanity_check_results or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") != ISD_IMPG_UNPROCESSED_CHECK_ID:
            continue
        isd_n = int(item.get("isd_count") or 0)
        impg_n = int(item.get("impg_count") or 0)
        return {
            "isd_present": isd_n > 0,
            "isd_count": isd_n,
            "impg_present": impg_n > 0,
            "impg_count": impg_n,
            "isd_impg_warning": str(item.get("detail") or "") or None,
        }
    return {
        "isd_present": False,
        "isd_count": 0,
        "impg_present": False,
        "impg_count": 0,
        "isd_impg_warning": None,
    }


def merge_isd_impg_into_run_summary(
    existing: dict[str, Any] | None,
    *,
    isd_count: int = 0,
    impg_count: int = 0,
    warning: str | None = None,
) -> dict[str, Any]:
    """Merge ISD/IMPG detection into a run_summary dict (preserves other keys)."""
    from app.parsers.gstr2b_parser import format_isd_impg_warning

    out = dict(existing) if isinstance(existing, dict) else {}
    isd_n = int(isd_count or 0)
    impg_n = int(impg_count or 0)
    out["isd_present"] = isd_n > 0
    out["isd_count"] = isd_n
    out["impg_present"] = impg_n > 0
    out["impg_count"] = impg_n
    out["isd_impg_warning"] = warning or format_isd_impg_warning(isd_n, impg_n)
    return out


def upsert_sanity_check(
    existing: list[dict[str, Any]] | None,
    check: dict[str, Any] | None,
    *,
    check_id: str | None = None,
) -> list[dict[str, Any]]:
    """Replace or remove a check by id; preserve prior ``acknowledged``."""
    cid = check_id or (str(check.get("id")) if check else None)
    if not cid:
        return [dict(item) for item in (existing or []) if isinstance(item, dict)]
    out = [
        dict(item)
        for item in (existing or [])
        if isinstance(item, dict) and str(item.get("id")) != cid
    ]
    if check is None:
        return out
    prior = next(
        (
            item
            for item in (existing or [])
            if isinstance(item, dict) and str(item.get("id")) == cid
        ),
        None,
    )
    merged = dict(check)
    if prior and prior.get("acknowledged"):
        merged["acknowledged"] = True
    out.append(merged)
    return out


def preserve_check_acknowledgments(
    prior: list[dict[str, Any]] | None,
    fresh: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Copy ``acknowledged=True`` from prior checks onto matching fresh ids."""
    prior_ack = {
        str(item.get("id")): bool(item.get("acknowledged"))
        for item in (prior or [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    out: list[dict[str, Any]] = []
    for item in fresh or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        cid = str(row.get("id") or "")
        if cid and prior_ack.get(cid):
            row["acknowledged"] = True
        out.append(row)
    return out


def unacknowledged_blocking_checks(
    sanity_check_results: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Warnings that declare ``requires_acknowledgment`` and are not yet acked."""
    out: list[dict[str, Any]] = []
    for item in sanity_check_results or []:
        if not isinstance(item, dict):
            continue
        if not item.get("requires_acknowledgment"):
            continue
        if str(item.get("status") or "").lower() != "warning":
            continue
        if item.get("acknowledged"):
            continue
        out.append(item)
    return out


def blocking_acknowledgments_pending(
    sanity_check_results: list[dict[str, Any]] | None,
) -> bool:
    """True when any high-risk warning still needs acknowledgment."""
    return bool(unacknowledged_blocking_checks(sanity_check_results))


# Back-compat alias used by earlier Issue 5 wiring.
def multi_sheet_combine_blocks_start(
    sanity_check_results: list[dict[str, Any]] | None,
) -> bool:
    return blocking_acknowledgments_pending(sanity_check_results)


def _read_pr_dataframe(raw: bytes, filename: str) -> pd.DataFrame:
    """Read a purchase-register file, scanning the first 20 rows to find the
    correct header row (handles CA exports with noisy title/blank rows before
    the actual column headers)."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else "csv"
    bio = io.BytesIO(raw)

    if ext == "csv":
        for encoding in ("utf-8", "latin-1"):
            try:
                raw_text = raw.decode(encoding, errors="replace")
                raw_df = pd.read_csv(io.StringIO(raw_text), header=None, dtype=str)
                best_df, _, _ = _find_best_header_from_raw(raw_df)
                if best_df is not None:
                    return best_df
            except Exception:  # noqa: BLE001
                continue
        # final fallback — try row 0 directly
        return pd.read_csv(bio, dtype=str)

    # Excel path
    try:
        xl = pd.ExcelFile(io.BytesIO(raw))
    except Exception:  # noqa: BLE001
        return pd.DataFrame()

    for sheet_name in xl.sheet_names:
        try:
            raw_df = pd.read_excel(
                io.BytesIO(raw),
                sheet_name=sheet_name,
                header=None,
                dtype=str,
            )
        except Exception:  # noqa: BLE001
            continue
        _log.info(
            "[detect-columns] _read_pr_dataframe: scanning sheet '%s', shape=%s",
            sheet_name,
            raw_df.shape,
        )
        best_df, best_mapping, best_header_row = _find_best_header_from_raw(raw_df)
        _log.info(
            "[detect-columns] _read_pr_dataframe: best_header_row=%s, mapping=%s",
            best_header_row,
            best_mapping,
        )
        if best_df is not None:
            return best_df

    # Nothing worked — fall back to openpyxl row-0 parse
    _log.warning("[detect-columns] _read_pr_dataframe: no best header found, falling back to row 0")
    try:
        return pd.read_excel(io.BytesIO(raw), dtype=str, engine="openpyxl")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def detect_pr_columns_from_r2(
    key: str, filename: str
) -> tuple[list[dict], list[str], int, list[str], int, list[dict]]:
    """Return wizard columns, headers, row count, parse warnings, missing-invoice
    count, and ``sheets_used`` from the purchase-register parse.
    """
    c = _r2()
    o = c.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    raw = o["Body"].read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large")
    df_full = _read_pr_dataframe(raw, filename)
    # Prefer full multi-sheet parse count when the workbook has several mappable
    # sheets — _read_pr_dataframe only returns the first sheet's rows.
    from app.parsers.purchase_register_parser import (
        list_candidate_pr_sheet_names,
        parse_purchase_register,
    )

    candidates = list_candidate_pr_sheet_names(raw, filename)
    parse_warnings: list[str] = []
    missing_invoice_count = 0
    sheets_used: list[dict] = []
    if len(candidates) > 1:
        parsed = parse_purchase_register(raw, filename)
        row_count = int(parsed.get("valid_rows") or 0)
        parse_warnings = list(parsed.get("warnings") or [])
        missing_invoice_count = int(parsed.get("missing_invoice_number_count") or 0)
        sheets_used = list(parsed.get("sheets_used") or [])
        _log.info(
            "[detect-columns] multi-sheet PR: used=%s skipped=%s valid_rows=%s "
            "missing_invoice=%s",
            sheets_used,
            parsed.get("sheets_skipped"),
            row_count,
            missing_invoice_count,
        )
    else:
        row_count = int(len(df_full))
        # Single-sheet: still parse once so missing-invoice mapping gaps surface early.
        try:
            parsed = parse_purchase_register(raw, filename)
            parse_warnings = list(parsed.get("warnings") or [])
            missing_invoice_count = int(
                parsed.get("missing_invoice_number_count") or 0
            )
            sheets_used = list(parsed.get("sheets_used") or [])
            if parsed.get("valid_rows"):
                row_count = int(parsed["valid_rows"])
        except Exception:  # noqa: BLE001
            pass
    df = df_full.head(50)
    headers = [str(h).strip() for h in df.columns.tolist()]
    columns_out = _wizard_columns_from_dataframe(df)
    return (
        columns_out,
        headers,
        row_count,
        parse_warnings,
        missing_invoice_count,
        sheets_used,
    )


def _set_wizard_progress(sb: Client, run_id: str, pct: int, msg: str) -> None:
    sb.table(T_RUNS).update(
        {
            "progress_pct": pct,
            "status_message": msg,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", run_id).execute()


def run_processing_job_sync(run_id: str) -> None:
    """Run the full import-wizard pipeline synchronously.

    Called via asyncio.to_thread() from the FastAPI endpoint so it executes in
    a thread pool without blocking the event loop.  Everything runs in-process —
    no Celery workers required.
    """
    from app.worker.tasks import run_import_job
    from app.worker.reconciliation_task import execute_reconciliation

    sb = get_supabase()
    row = fetch_run(sb, run_id)
    actor = str(row.get("created_by") or row.get("firm_owner_id") or "")
    if not actor:
        actor = "00000000-0000-0000-0000-000000000000"

    client_id = str(row.get("client_id") or "").strip()
    period_raw = str(row.get("period") or "").strip()
    gstr2b_key = str(row.get("gstr2b_r2_key") or "").strip()
    pr_key = str(row.get("pr_r2_key") or "").strip()

    if not client_id or not period_raw or not gstr2b_key or not pr_key:
        raise ValueError(
            "wizard run is missing required fields "
            f"(client_id={client_id!r}, period={period_raw!r}, "
            f"gstr2b_r2_key={gstr2b_key!r}, pr_r2_key={pr_key!r})"
        )

    # reconciliation_task._parse_period expects "YYYY-MM"; wizard stores "YYYY-MM-DD".
    period = period_raw[:7]
    now = datetime.now(timezone.utc).isoformat()

    # Ensure reconciliation_run row exists before run_import_job writes to it.
    existing = (
        sb.table("reconciliation_run")
        .select("id, status")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        sb.table("reconciliation_run").insert(
            {
                "id": run_id,
                "client_gstin_id": client_id,
                "period": period,
                "status": "uploading",
                "progress_percent": 0,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()

    try:
        _set_wizard_progress(sb, run_id, 10, "Loading files…")
        run_import_job.apply(args=[run_id, "gstr2b", gstr2b_key])

        _set_wizard_progress(sb, run_id, 25, "Parsed GSTR-2B")
        run_import_job.apply(args=[run_id, "purchase_register", pr_key])

        _set_wizard_progress(sb, run_id, 40, "Matching invoices…")
        sb.table("reconciliation_run").update(
            {"status": "MATCHING", "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", run_id).execute()

        _set_wizard_progress(sb, run_id, 50, "Running engine…")
        execute_reconciliation.apply(args=[run_id])

        _set_wizard_progress(sb, run_id, 95, "Finalising…")
        transition_run(
            sb,
            run_id,
            actor,
            "complete",
            extra_patch={
                "progress_pct": 100,
                "status_message": "Complete",
            },
            audit_event="processing_complete",
            audit_detail={},
        )
    except Exception as e:  # noqa: BLE001
        _log.exception("run_processing_job_sync failed for run_id=%s", run_id)
        try:
            row2 = fetch_run(sb, run_id)
            actor2 = str(row2.get("created_by") or row2.get("firm_owner_id") or actor)
            transition_run(
                sb,
                run_id,
                actor2,
                "error",
                extra_patch={
                    "error_detail": str(e),
                    "status_message": "Processing failed",
                },
                audit_event="processing_error",
                audit_detail={"error": str(e)},
            )
        except Exception:  # noqa: BLE001
            try:
                sb.table(T_RUNS).update(
                    {
                        "status": "error",
                        "error_detail": str(e),
                        "status_message": "Processing failed",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", run_id).execute()
            except Exception:  # noqa: BLE001
                pass
        raise

