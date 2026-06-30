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
)

_MISSED_ITC_KEYS = (
    "gstr_id",
    "supplier_gstin",
    "invoice_number_normalized",
    "invoice_date",
    "total_tax_paise",
    "mismatch_reason",
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
    # Review-required rows are stored via duplicates; these three fields
    # must be preserved so the API can show real match_level, confidence,
    # and review reason instead of defaulting to FUZZY / 0%.
    "confidence_score",
    "match_level",
    "review_reason",
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
    "decision_what",
    "decision_why",
    "decision_next",
    "decision_rule",
    "decision_confidence",
)

_SECTION175_DECISION_KEYS = (
    "supplier_gstin",
    "hsn_code",
    "category",
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
    skipped_count: int = 0,
    review_required_count: int = 0,
) -> dict[str, Any]:
    """Scalar run_summary only — no decisions/compliance blobs (kept in results payload)."""
    return {
        "total_records": n_gstr + n_pr,
        "matched_count": matched_count + review_required_count, # total linked
        "clean_matched_count": matched_count,
        "review_required_count": review_required_count,
        "total_linked_count": matched_count + review_required_count,
        "unmatched_count": missed_itc_count + wrongful_count,
        "itc_at_risk": itc_at_risk_total,
        "missed_itc_paise": itc_missed,
        "rule37_itc_paise": rule37_itc_paise,
        "wrongful_itc": wrongful_paise,
        "late_itc": late_itc_paise,
        "late_match_count": late_match_count,
        "gstr_in_scope": n_gstr,
        "pr_in_scope": n_pr,
        "rule37_pending_verification_count": rule37_pending_verification_count,
        "rule37_pending_verification_paise": rule37_pending_verification_paise,
        "skipped_count": skipped_count,
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
    rule37_pending_verification: list[dict[str, Any]] | None = None,
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
            "review_required_typo": review_required_typo or [],
        },
        "compliance": {
            "rule37": rule37,
            "rule37_pending_verification": rule37_pending_verification or [],
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


import gzip
import base64
import json

def save_reconciliation_results(
    client: Client,
    run_id: str,
    payload: dict[str, Any],
    *,
    created_at: str,
) -> None:
    """Replace reconciliation_results row; log payload size for large-run diagnostics."""
    size_mb = payload_json_byte_size(payload) / (1024 * 1024)
    _log.info(
        "reconciliation_results save run_id=%s payload_bytes=%.2fMB matched=%s missed=%s",
        run_id,
        size_mb,
        len((payload.get("engine") or {}).get("matched") or []),
        len((payload.get("engine") or {}).get("missed_itc") or []),
    )
    
    payload_str = json.dumps(payload)
    compressed_payload = base64.b64encode(gzip.compress(payload_str.encode("utf-8"))).decode("utf-8")
    
    client.table("reconciliation_results").delete().eq("run_id", run_id).execute()
    res_ins = (
        client.table("reconciliation_results")
        .insert(
            {
                "run_id": run_id,
                "payload": compressed_payload,
                "created_at": created_at,
            }
        )
        .execute()
    )
    if res_ins.data is None and getattr(res_ins, "error", None):
        raise RuntimeError(f"reconciliation_results insert failed: {res_ins.error}")
