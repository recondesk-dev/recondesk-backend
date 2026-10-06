"""Compact reconciliation_results / run_summary persistence for large runs."""

from __future__ import annotations

import json
import logging
from typing import Any

from supabase import Client

_log = logging.getLogger(__name__)

RESULTS_INSERT_BATCH = 1

_MATCHED_KEYS = (
    "gstr_id",
    "pr_id",
    "confidence_score",
    "is_late_filing",
    "original_period",
    "late_months",
    "vendor_similarity_score",
    # Required for exact vs non-exact chip count and match-level badge.
    # These are small scalars and do not materially increase payload size.
    "match_level",
    "financial_status",
    # Multi-line PR splits (one GSTR invoice booked as N tax-rate / HSN rows).
    # Without these the Matched-tab Discrepancy column only sees the primary
    # pr_id and fabricates a fake gap equal to the sibling line(s).
    "pr_ids",
    "multiline_pr_split",
    # L5/fuzzy match invoice_similarity score [0.0–1.0] — surfaced as a
    # confidence badge on the UI. None for exact (L1–L4) matches.
    "match_confidence",
    # Per-field comparison snapshot for the CA rationale drawer.
    "compared_fields",
    # IMS taxpayer action status overlaid from Sandbox IMS fetch.
    "ims_status",
)

_MISSED_ITC_KEYS = (
    "gstr_id",
    "supplier_gstin",
    "invoice_number_normalized",
    "invoice_date",
    "total_tax_paise",
    "mismatch_reason",
    "ims_status",
)

_WRONGFUL_KEYS = (
    "id",
    "supplier_gstin",
    "invoice_number_normalized",
    "invoice_date",
    "taxable_amount_paise",
    "total_tax_paise",
    "risk_reason",
)

_GSTIN_MISMATCH_KEYS = (
    "gstr_id",
    "pr_id",
    "gstr_supplier_gstin",
    "pr_supplier_gstin",
    "invoice_number_normalized",
    "invoice_date",
    "taxable_amount_paise",
    "total_tax_paise",
    "reason",
)

_DUPLICATE_KEYS = (
    "gstr_id",
    "id",
    "supplier_gstin",
    "invoice_number_normalized",
    "invoice_date",
    "taxable_amount_paise",
    "total_tax_paise",
    "side",
    "reason",
    # Canonical PR that was auto-matched for true-duplicate groups — shown so a
    # CA reviewing a Duplicate Entry knows which row is treated as the real one.
    "matched_pr_id",
    "classification",
    # Review-required rows are stored via duplicates; these three fields
    # must be preserved so the API can show real match_level, confidence,
    # and review reason instead of defaulting to FUZZY / 0%.
    "confidence_score",
    "match_level",
    "review_reason",
    # The absolute taxable-amount diff (paise) between GSTR and PR — shown as
    # ₹ discrepancy in the Review Required table.  Previously absent from this
    # whitelist, which caused the column to always display ₹0.
    "taxable_diff_paise",
    # Decision layer output for review-required rows — without these the
    # Notes column always shows "—" because the decision fields are dropped
    # by the slim_duplicates whitelist.
    "decision_what",
    "decision_why",
    "decision_next",
    "decision_rule",
    "decision_confidence",
    "decision_matched_fields",
    "decision_differed_fields",
    "decision_normalized_pairs",
    # L5/fuzzy match invoice_similarity score [0.0–1.0] — surfaced as a
    # confidence badge on the UI. None for exact (L1–L4) matches.
    "match_confidence",
    # Per-field comparison snapshot for the CA rationale drawer.
    "compared_fields",
    # IMS taxpayer action status overlaid from Sandbox IMS fetch.
    "ims_status",
)

_UNMATCHED_NOTE_KEYS = (
    "id",
    "supplier_gstin",
    "supplier_name",
    "note_number",
    "note_amount_paise",
    "document_type",
    "invoice_date",
    "reason",
    "classification",
    "match_status",
    "side",
)

_DECISION_ROW_KEYS = (
    "gstr_id",
    "pr_id",
    "decision_what",
    "decision_why",
    "decision_next",
    "decision_rule",
    "decision_confidence",
)

_RULE37_DECISION_KEYS = (
    "id",
    "pr_id",
    "supplier_gstin",
    "invoice_number",
    "invoice_date",
    "itc_at_risk_paise",
    "status",
    "days_remaining",
    "deadline",
    "itc_claimed_period",
    "decision_what",
    "decision_why",
    "decision_next",
    "decision_rule",
    "decision_confidence",
)

_SECTION175_DECISION_KEYS = (
    "supplier_gstin",
    "invoice_number",
    "invoice_date",
    "amount",
    "estimated_itc_amount",
    "hsn_code",
    "category",
    "reason",
    "section",
    "flag_source",
    "decision_what",
    "decision_why",
    "decision_next",
    "decision_rule",
    "decision_confidence",
)


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: row[k] for k in keys if k in row}


def slim_engine_matched(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_pick(r, _MATCHED_KEYS) for r in rows]


def slim_missed_itc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_pick(r, _MISSED_ITC_KEYS) for r in rows]


def slim_wrongful_itc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_pick(r, _WRONGFUL_KEYS) for r in rows]


def slim_gstin_mismatch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_pick(r, _GSTIN_MISMATCH_KEYS) for r in rows]


def slim_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_pick(r, _DUPLICATE_KEYS) for r in rows]


def slim_unmatched_notes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_pick(r, _UNMATCHED_NOTE_KEYS) for r in rows]


def slim_decision_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_pick(r, _DECISION_ROW_KEYS) for r in rows]


def slim_decision_payload(decisions: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decisions, dict):
        return {}
    out = dict(decisions)
    if isinstance(out.get("rows"), list):
        out["rows"] = slim_decision_rows(out["rows"])
    if isinstance(out.get("rule37"), list):
        out["rule37"] = [_pick(r, _RULE37_DECISION_KEYS) for r in out["rule37"] if isinstance(r, dict)]
    if isinstance(out.get("section_175"), list):
        out["section_175"] = [
            _pick(r, _SECTION175_DECISION_KEYS) for r in out["section_175"] if isinstance(r, dict)
        ]
    return out


def build_run_summary_metrics(
    *,
    n_gstr: int,
    n_pr: int,
    matched_count: int,
    missed_itc_count: int,
    wrongful_count: int,
    itc_missed: int,
    wrongful_paise: int,
    rule37_itc_paise: int,
    itc_at_risk_total: int,
    late_itc_paise: int,
    late_match_count: int,
    rule37_pending_verification_count: int = 0,
    rule37_pending_verification_paise: int = 0,
    rule37_claimed_invoice_count: int = 0,
    rule37_payment_status_known_count: int = 0,
    rule37_payment_status_unknown_count: int = 0,
    skipped_count: int = 0,
    review_required_count: int = 0,
    duplicate_entry_count: int = 0,
    unmatched_notes_count: int = 0,
    matched_itc_paise: int = 0,
) -> dict[str, Any]:
    """Scalar run_summary only — no decisions/compliance blobs (kept in results payload)."""
    skip_detail = None
    if skipped_count > 0:
        skip_detail = (
            f"{skipped_count} skipped: missing invoice number"
        )
    return {
        "total_records": n_gstr + n_pr,
        "matched_count": matched_count + review_required_count, # total linked
        "clean_matched_count": matched_count,
        "review_required_count": review_required_count,
        "total_linked_count": matched_count + review_required_count,
        "unmatched_count": missed_itc_count + wrongful_count,
        "itc_at_risk": itc_at_risk_total,
        "missed_itc_paise": itc_missed,
        "matched_itc_paise": int(matched_itc_paise or 0),
        "rule37_itc_paise": rule37_itc_paise,
        "wrongful_itc": wrongful_paise,
        "late_itc": late_itc_paise,
        "late_match_count": late_match_count,
        "gstr_in_scope": n_gstr,
        "pr_in_scope": n_pr,
        "rule37_pending_verification_count": rule37_pending_verification_count,
        "rule37_pending_verification_paise": rule37_pending_verification_paise,
        "rule37_claimed_invoice_count": rule37_claimed_invoice_count,
        "rule37_payment_status_known_count": rule37_payment_status_known_count,
        "rule37_payment_status_unknown_count": rule37_payment_status_unknown_count,
        "skipped_count": skipped_count,
        "pr_skipped_missing_invoice_count": skipped_count,
        "pr_skipped_detail": skip_detail,
        "duplicate_entry_count": duplicate_entry_count,
        "unmatched_notes_count": unmatched_notes_count,
    }


def build_stored_results_payload(
    *,
    matched: list[dict[str, Any]],
    missed_itc: list[dict[str, Any]],
    wrongful_itc_risk: list[dict[str, Any]],
    rule37: list[dict[str, Any]],
    section_175_warnings: list[dict[str, Any]],
    credit_note_adjustment: dict[str, Any],
    decision_payload: dict[str, Any],
    matching_version: str,
    rules_version: str,
    decision_version: str,
    late_filing: list[dict[str, Any]] | None = None,
    gstin_mismatch: list[dict[str, Any]] | None = None,
    duplicates: list[dict[str, Any]] | None = None,
    duplicate_entries: list[dict[str, Any]] | None = None,
    unmatched_notes: list[dict[str, Any]] | None = None,
    rule37_pending_verification: list[dict[str, Any]] | None = None,
    rule37_coverage: dict[str, Any] | None = None,
    review_required_typo: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Minimal JSON persisted to reconciliation_results (invoice detail loaded from row tables)."""
    return {
        "engine": {
            "matched": slim_engine_matched(matched),
            "missed_itc": slim_missed_itc(missed_itc),
            "wrongful_itc_risk": slim_wrongful_itc(wrongful_itc_risk),
            "gstin_mismatch": slim_gstin_mismatch(gstin_mismatch or []),
            "duplicates": slim_duplicates(duplicates or []),
            "duplicate_entries": slim_duplicates(duplicate_entries or []),
            "unmatched_notes": slim_unmatched_notes(unmatched_notes or []),
            "review_required_typo": review_required_typo or [],
        },
        "compliance": {
            "rule37": rule37,
            "rule37_pending_verification": rule37_pending_verification or [],
            "rule37_coverage": rule37_coverage or {},
            "section_17_5": section_175_warnings,
            "credit_notes": credit_note_adjustment or {},
            "late_filing": late_filing or [],
        },
        "decisions": slim_decision_payload(decision_payload),
        "meta": {
            "matching_version": matching_version,
            "rules_version": rules_version,
            "decision_version": decision_version,
        },
    }


def payload_json_byte_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


import base64
import gzip
import json
import os

from app.config import get_settings
from app.services.r2_service import (
    delete_file_from_r2,
    is_r2_configured,
    upload_bytes_to_r2,
)


def delete_reconciliation_payload(client: Client, run_id: str) -> None:
    """Delete reconciliation_results row and any associated external R2 object."""
    settings = get_settings()
    prefix = (settings.RECONCILIATION_PAYLOAD_PREFIX or "reconciliation-payloads").strip().strip("/")
    try:
        res = (
            client.table("reconciliation_results")
            .select("storage_type, storage_path, payload")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            st = row.get("storage_type")
            sp = row.get("storage_path")
            p = row.get("payload")
            path = sp or (p.get("path") if isinstance(p, dict) and p.get("_storage") == "r2" else None)
            if (st == "r2" or path) and path:
                clean_path = str(path).strip()
                # Security: prevent path traversal or deletion outside expected prefix
                if ".." not in clean_path and clean_path.startswith(f"{prefix}/"):
                    delete_file_from_r2(clean_path)
    except Exception as exc:
        _log.warning("Could not delete external R2 payload for run_id=%s: %s", run_id, exc)

    try:
        client.table("reconciliation_results").delete().eq("run_id", run_id).execute()
    except Exception as exc:
        _log.warning("Could not delete reconciliation_results row for run_id=%s: %s", run_id, exc)


def save_reconciliation_results(
    client: Client,
    run_id: str,
    payload: dict[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    """Persist reconciliation_results.
    
    Supports externalized object storage (Cloudflare R2) with automatic PostgreSQL
    fallback. Stores storage_type, storage_path, and size metrics.
    """
    settings = get_settings()
    raw_json_str = json.dumps(payload)
    raw_bytes = raw_json_str.encode("utf-8")
    raw_size_bytes = len(raw_bytes)
    compressed_bytes = gzip.compress(raw_bytes)
    compressed_size_bytes = len(compressed_bytes)

    size_mb = raw_size_bytes / (1024 * 1024)
    _log.info(
        "reconciliation_results save run_id=%s payload_bytes=%.2fMB (compressed=%.2fMB) matched=%s missed=%s",
        run_id,
        size_mb,
        compressed_size_bytes / (1024 * 1024),
        len((payload.get("engine") or {}).get("matched") or []),
        len((payload.get("engine") or {}).get("missed_itc") or []),
    )

    storage_pref = (os.environ.get("RECONCILIATION_PAYLOAD_STORAGE") or settings.RECONCILIATION_PAYLOAD_STORAGE or "auto").lower()
    storage_type = "db"
    storage_path: str | None = None
    row_payload: Any = None

    if storage_pref in ("auto", "r2") and is_r2_configured():
        clean_run_id = os.path.basename(str(run_id).strip())
        prefix = (settings.RECONCILIATION_PAYLOAD_PREFIX or "reconciliation-payloads").strip().strip("/")
        target_path = f"{prefix}/{clean_run_id}.json.gz"
        try:
            upload_bytes_to_r2(compressed_bytes, target_path, content_type="application/gzip")
            storage_type = "r2"
            storage_path = target_path
            row_payload = {
                "_storage": "r2",
                "path": target_path,
                "size": raw_size_bytes,
                "compressed_size": compressed_size_bytes,
            }
            _log.info("Persisted reconciliation payload for run_id=%s to R2 at %s", run_id, target_path)
        except Exception as exc:
            _log.warning(
                "Failed to offload reconciliation payload to R2 for run_id=%s (%s); falling back to DB",
                run_id,
                exc,
            )
            storage_type = "db"
            storage_path = None

    if storage_type == "db":
        compressed_b64 = base64.b64encode(compressed_bytes).decode("utf-8")
        row_payload = compressed_b64

    # Remove previous row if any
    try:
        client.table("reconciliation_results").delete().eq("run_id", run_id).execute()
    except Exception as exc:
        _log.warning("reconciliation_results delete prior row warning for run_id=%s: %s", run_id, exc)

    full_row = {
        "run_id": run_id,
        "storage_type": storage_type,
        "storage_path": storage_path,
        "payload_size_bytes": raw_size_bytes,
        "compressed_size_bytes": compressed_size_bytes,
        "payload": row_payload,
        "created_at": created_at,
    }

    try:
        res_ins = client.table("reconciliation_results").insert(full_row).execute()
        if res_ins.data is None and getattr(res_ins, "error", None):
            raise RuntimeError(f"reconciliation_results insert failed: {res_ins.error}")
    except Exception as exc:
        err_str = str(exc).lower()
        if "storage_type" in err_str or "column" in err_str:
            _log.warning(
                "Storage metadata columns not found on reconciliation_results; inserting legacy row schema: %s",
                exc,
            )
            legacy_row = {
                "run_id": run_id,
                "payload": row_payload,
                "created_at": created_at,
            }
            res_ins = client.table("reconciliation_results").insert(legacy_row).execute()
            if res_ins.data is None and getattr(res_ins, "error", None):
                raise RuntimeError(f"reconciliation_results legacy insert failed: {res_ins.error}")
        else:
            raise

    return {
        "storage_type": storage_type,
        "storage_path": storage_path,
        "payload_size_bytes": raw_size_bytes,
        "compressed_size_bytes": compressed_size_bytes,
    }
