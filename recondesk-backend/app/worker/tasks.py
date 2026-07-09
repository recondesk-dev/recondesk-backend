"""Celery tasks for import pipeline (R2 + Supabase)."""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
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


def _load_and_normalize_gstr2b_body_for_parse(body: bytes) -> dict[str, Any]:
    from app.parsers.gstr2b_parser import normalize_gstr2b_payload

    try:
        data: Any = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"invalid_json at line {e.lineno}, column {e.colno}: {e.msg}"
        ) from e
    except UnicodeDecodeError as e:
        raise ValueError(f"invalid_utf8: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("invalid_data_structure")
    if "data" not in data:
        raise ValueError("missing_data_key")
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


def _bulk_insert(
    client: Client,
    table: str,
    rows: list[dict[str, Any]],
) -> None:
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i : i + CHUNK_SIZE]
        try:
            client.table(table).insert(chunk).execute()
            _log.info(f"[WORKER] Inserted {table} batch {i//CHUNK_SIZE + 1} ({len(chunk)} rows)")
        except Exception as exc:
            raise RuntimeError(
                f"Insert into {table} failed ({len(chunk)} row(s), offset {i}): {exc}"
            ) from exc


@celery_app.task(name="worker.run_import_job", max_retries=0)
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

        if file_type == "gstr2b":
            gstr_payload = _load_and_normalize_gstr2b_body_for_parse(body)
            parsed = parse_gstr2b(gstr_payload)
            records = list(parsed.get("records") or [])
            for_sanity = _gstr_records_for_sanity(records)
            
            parsed_period = str(parsed.get("period", ""))
            if parsed_period and len(parsed_period) >= 7:
                new_period = parsed_period[:7]
                if new_period != period:
                    _log.info("Updating run %s period from %s to %s based on GSTR-2B", run_id, period, new_period)
                    period = new_period
                    _update_run(client, run_id, {"period": period})
        elif file_type == "purchase_register":
            name = os.path.basename(r2_key) or "purchase.xlsx"
            parse_body = body
            parse_name = name
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
            pr = parse_purchase_register(parse_body, parse_name)
            if not pr.get("success"):
                errs = "; ".join(pr.get("errors") or ["parse failed"])
                raise ValueError(errs)
            records = list(pr.get("records") or [])
            for_sanity = records
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
        )
        sanity_json = _sanity_checks_to_json(checks)
        blocking = any(
            c.severity == "error" and not c.passed for c in checks
        )
        if blocking:
            _log.warning(
                "Sanity reported errors (non-fatal; sanity_report saved on completion): %s",
                _sanity_failure_message(checks),
            )

        insert_table = "gstr_records" if file_type == "gstr2b" else "pr_records"
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
        if rows:
            _bulk_insert(client, insert_table, rows)

        count = len(rows)
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 90,
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
