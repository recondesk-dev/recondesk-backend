"""GSTR-1 sales-side reconciliation endpoint — ``/api/gstr1-reconcile``.

Chains the five standalone GSTR-1 modules end-to-end:

1. ``sales_register_parser``  — parse the uploaded Sales Register file
2. ``gstr1_parser``            — parse the uploaded GSTR-1 JSON
3. ``generic_matcher``         — match SR records to GSTR-1 candidates
4. ``gstr1_mismatch_rules``    — classify mismatches (G1M1–G1M6)
5. ``gstr1_vs_3b``             — GSTR-1 vs GSTR-3B tie-out

Also runs per-run buyer GSTIN verification (G1M7), invoice series
continuity / duplicate detection (G1M8), HSN/rate schedule
validation (G1M9), Documents Issued / Table 13 summary (G1M10),
and optional prior-period amendment detection Tables 9A/9B/9C (G1M11).

Returns combined ``{WHAT, WHY, NEXT, confidence}`` results matching the
purchase-side API response shape.

**This module does NOT modify any existing routes or purchase-side code.**
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any, Mapping, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services.firm_access import list_accessible_client_gstin_ids
from app.rules.gstr1a_eligibility import compute_gstr1a_window
from app.services.gstr1_run_store import (
    get_gstr1_run,
    list_gstr1_runs,
    normalise_period,
    save_gstr1_run,
)
from app.services.gstr1a_period_actions import (
    list_gstr1a_period_actions,
    mark_gstr1a_period_filed,
    normalise_action_period,
)
from app.utils.audit import log_audit

# ── Standalone GSTR-1 modules ────────────────────────────────────────────────
from app.parsers.sales_register_parser import parse_sales_register, ParseError
from app.parsers.gstr1_parser import parse_gstr1
from app.parsers.gstr3b_parser import parse_gstr3b
from app.matching.generic_matcher import match_sales_register_to_gstr1
from app.rules.gstr1_mismatch_rules import (
    classify_all_mismatches,
    check_invoice_series_continuity,
    validate_hsn_rate_mapping,
    summarize_documents_issued,
    detect_amendments,
    _amendment_invoice_key,
    MismatchResult,
)
from app.reconciliation.gstr1_vs_3b import reconcile_gstr1_vs_3b

_log = logging.getLogger(__name__)

# Aggregate / informational GSTR-1 rows (HSN summary, nil, advances, etc.).
# These are parsed for diagnostics / tie-out exclusions but must never enter
# invoice-level matching or Extra-in-GSTR-1 (G1M2) classification.
_NON_INVOICE_GSTR1_SECTIONS: frozenset[str] = frozenset({
    "hsn", "nil", "doc_issue", "at", "ata", "atadj", "atadja",
})
_NON_INVOICE_GSTR1_TYPES: frozenset[str] = frozenset({
    "HSN_SUMMARY", "NIL_RATED", "EXEMPT", "NON_GST", "NIL_EXEMPT", "ADVANCES",
})


def _is_invoice_level_gstr1_record(rec: dict[str, Any]) -> bool:
    """True when *rec* is an invoice/note that can match a Sales Register row."""
    section = str(rec.get("section") or "").strip().lower()
    if section in _NON_INVOICE_GSTR1_SECTIONS:
        return False
    inv_type = str(rec.get("invoice_type") or rec.get("doc_type") or "").strip().upper()
    if inv_type in _NON_INVOICE_GSTR1_TYPES:
        return False
    return True


# Match app-wide redirect_slashes=False (main.py) and peer routers like
# clients/gstin — register at "" so POST /api/gstr1-reconcile works without
# a trailing slash (frontend normalizeApiPath strips trailing slashes).
router = APIRouter(redirect_slashes=False)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _confidence_label(confidence: int | None) -> str:
    """Map a numeric 0-100 confidence score to HIGH/MEDIUM/LOW."""
    if confidence is None:
        return "LOW"
    if confidence >= 90:
        return "HIGH"
    if confidence >= 60:
        return "MEDIUM"
    return "LOW"


def _match_result_to_dict(mr: Any) -> dict[str, Any]:
    """Serialise a ``MatchResult`` dataclass to a JSON-safe dict."""
    return {
        "match_level": mr.level,
        "confidence": mr.confidence,
        "decision_what": mr.decision_what,
        "decision_why": mr.decision_why,
        "decision_next": mr.decision_next,
        "decision_confidence": _confidence_label(mr.confidence),
        "decision_rule": f"L{mr.level}_MATCH",
        "requires_human_review": mr.requires_human_review,
        "identity_confidence": getattr(mr, "identity_confidence", "High"),
        "financial_status": getattr(mr, "financial_status", "Exact"),
        "review_reason": mr.review_reason,
        "discrepancies": list(mr.discrepancies) if mr.discrepancies else [],
        "compared_fields": list(mr.compared_fields) if mr.compared_fields else [],
        "is_late_filing": getattr(mr, "is_late_filing", False),
    }


def _mismatch_result_to_dict(mr: MismatchResult) -> dict[str, Any]:
    """Serialise a ``MismatchResult`` to the unified decision dict."""
    d = mr.to_dict()
    # Ensure the unified decision_confidence field is present
    if "decision_confidence" not in d:
        d["decision_confidence"] = mr.to_decision_output().confidence
    return d


async def _verify_buyer_gstins_for_g1m7(
    sr_records: list[dict[str, Any]],
    gstr1_records: list[dict[str, Any]],
    *,
    rate_limit_seconds: float = 0.15,
) -> list[MismatchResult]:
    """Verify unique buyer GSTINs once per run and build G1M7 mismatches.

    Reuses ``app.services.gstin_verification.verify_gstin`` (Sandbox.co.in).
    Format-invalid GSTINs are flagged without an API call. Infrastructure
    failures are non-blocking — format flags still apply; API checks are
    skipped for remaining GSTINs.
    """
    import asyncio

    from app.rules.gstr1_mismatch_rules import (
        build_g1m7_mismatches,
        collect_unique_buyer_gstins,
        gstin_format_ok,
    )
    from app.services.gstin_verification import verify_gstin

    gstin_refs = collect_unique_buyer_gstins(
        sr_records=sr_records,
        gstr1_records=gstr1_records,
    )
    if not gstin_refs:
        return []

    verification_cache: dict[str, dict[str, Any]] = {}
    api_enabled = True

    for gstin in sorted(gstin_refs.keys()):
        if not gstin_format_ok(gstin):
            verification_cache[gstin] = {
                "valid": False,
                "status": "Invalid Format",
                "reason": "invalid_format",
                "legal_name": None,
                "trade_name": None,
                "taxpayer_type": None,
                "registration_date": None,
                "raw_response": {},
            }
            continue

        if not api_enabled:
            continue

        try:
            verification_cache[gstin] = await verify_gstin(gstin)
        except Exception as exc:  # noqa: BLE001 — never fail the recon run
            _log.error(
                "gstr1_reconcile: GSTIN verification unavailable – %s. "
                "Skipping remaining Sandbox lookups for this run.",
                exc,
            )
            api_enabled = False
            continue

        if rate_limit_seconds > 0:
            await asyncio.sleep(rate_limit_seconds)

    g1m7 = build_g1m7_mismatches(
        gstin_refs=gstin_refs,
        verification_by_gstin=verification_cache,
    )
    _log.info(
        "gstr1_reconcile: G1M7 GSTIN verification — unique=%d flagged=%d "
        "api_enabled=%s",
        len(gstin_refs),
        len(g1m7),
        api_enabled,
    )
    return g1m7


def _sanitise_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Strip non-serialisable fields (DataFrames, etc.) from a parser record."""
    out: dict[str, Any] = {}
    for k, v in rec.items():
        if k in ("normalized_dataframe", "df_canon"):
            continue
        # Convert date objects to ISO strings
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _build_gstin_index(
    records: list[dict[str, Any]],
    gstin_keys: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    """Group records by GSTIN into a lookup dict.

    Blank / placeholder GSTINs (``NA``, ``N/A``, whitespace) are indexed under
    ``\"\"`` so unregistered / B2C rows share one bucket.
    """
    _absent = {
        "NA", "N/A", "N.A", "N.A.", "NONE", "NULL", "NIL", "-", "--", ".",
        "0", "UNREGISTERED", "URP",
    }
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        gstin = ""
        for key in gstin_keys:
            v = rec.get(key)
            if v is None:
                continue
            s = str(v).strip().upper()
            if not s:
                continue
            collapsed = "".join(ch for ch in s if ch.isalnum())
            if s in _absent or collapsed in {"NA", "NIL", "NULL", "NONE", "URP"}:
                continue
            gstin = s
            break
        index[gstin].append(rec)
    return dict(index)


def _invoice_index_key(rec: Mapping[str, Any]) -> str:
    """Normalized invoice key used for sales-side candidate lookup."""
    from app.services.matcher import invoice_match_key_for_record

    try:
        key = invoice_match_key_for_record(rec)
    except Exception:  # noqa: BLE001 — never break matching on key helpers
        key = ""
    if key:
        return str(key).strip().upper()
    for field in ("invoice_number_normalized", "invoice_number"):
        raw = rec.get(field)
        if raw is None:
            continue
        s = str(raw).strip().upper()
        if s:
            return s
    return ""


def _build_invoice_index(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group records by normalized invoice number for O(1) candidate lookup."""
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        key = _invoice_index_key(rec)
        if key:
            index[key].append(rec)
    return dict(index)


# ══════════════════════════════════════════════════════════════════════════════
# Core pipeline
# ══════════════════════════════════════════════════════════════════════════════

async def _run_pipeline(
    sr_file_content: bytes,
    sr_filename: str,
    gstr1_file_content: bytes,
    gstr3b_file_content: bytes,
    gstr1_filing_period: str | None,
    prior_gstr1_file_content: bytes | None = None,
) -> dict[str, Any]:
    """Execute the full GSTR-1 reconciliation pipeline.

    Returns a JSON-serialisable result dict.
    """
    t0 = time.perf_counter()

    # ── Step 1: Parse ─────────────────────────────────────────────────────
    # 1a — Sales Register
    sr_result = parse_sales_register(sr_file_content, sr_filename)
    if not sr_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "sales_register_parse_failed",
                "errors": sr_result.get("errors", []),
            },
        )
    sr_records: list[dict[str, Any]] = sr_result.get("records", [])
    _log.info(
        "gstr1_reconcile: SR parsed — %d records, %d skipped",
        len(sr_records), sr_result.get("skipped_rows", 0),
    )

    # 1b — GSTR-1
    try:
        gstr1_result = parse_gstr1(gstr1_file_content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "gstr1_parse_failed",
                "message": str(exc),
            },
        )
    gstr1_records_all: list[dict[str, Any]] = gstr1_result.get("records", [])
    # HSN / nil / advance aggregates stay in parse diagnostics but are excluded
    # from invoice matching and Extra-in-GSTR-1 (G1M2).
    gstr1_records: list[dict[str, Any]] = [
        r for r in gstr1_records_all if _is_invoice_level_gstr1_record(r)
    ]
    gstr1_metadata_count = len(gstr1_records_all) - len(gstr1_records)
    _log.info(
        "gstr1_reconcile: GSTR-1 parsed — %d invoice-level, %d metadata "
        "(hsn/nil/advances), %d skipped",
        len(gstr1_records),
        gstr1_metadata_count,
        gstr1_result.get("total_skipped", 0),
    )

    # 1c — GSTR-3B
    try:
        gstr3b_data = json.loads(gstr3b_file_content)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "gstr3b_parse_failed",
                "message": f"Invalid JSON: {exc.msg}",
            },
        )

    try:
        parsed_gstr3b = parse_gstr3b(gstr3b_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "gstr3b_parse_failed",
                "message": str(exc),
            },
        )

    # Derive filing period from GSTR-1 if not explicitly supplied
    if not gstr1_filing_period:
        fp_raw = gstr1_result.get("filing_period", "")
        # filing_period is ISO date "2026-04-01" → convert to MMYYYY
        if fp_raw and len(fp_raw) >= 7:
            try:
                parts = fp_raw.split("-")
                gstr1_filing_period = f"{parts[1]}{parts[0]}"  # "042026"
            except (IndexError, ValueError):
                pass

    # ── Step 1d: Prior-period GSTR-1 (amendment context) ──────────────────
    # Parsed before matching so prior-linked SR rows can be excluded from
    # current-period G1M1/G1M2 matching and routed to G1M11 only.
    prior_provided = bool(prior_gstr1_file_content)
    prior_gstr1_records: list[dict[str, Any]] = []
    prior_gstr1_diagnostics: dict[str, Any] | None = None
    prior_invoice_keys: set[str] = set()
    if prior_provided:
        try:
            prior_result = parse_gstr1(prior_gstr1_file_content)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error": "prior_gstr1_parse_failed",
                    "message": str(exc),
                },
            )
        prior_gstr1_records = [
            r for r in prior_result.get("records", [])
            if _is_invoice_level_gstr1_record(r)
        ]
        prior_invoice_keys = {
            k for k in (_amendment_invoice_key(r) for r in prior_gstr1_records) if k
        }
        prior_gstr1_diagnostics = {
            "filing_gstin": prior_result.get("filing_gstin", ""),
            "filing_period": prior_result.get("filing_period", ""),
            "total_parsed": prior_result.get("total_parsed", 0),
            "invoice_level_count": len(prior_gstr1_records),
            "section_counts": prior_result.get("section_counts", {}),
        }

    # Current-period originals vs amendment tables (b2ba/cdnra/expa/…).
    gstr1_amendment_records = [
        r for r in gstr1_records if bool(r.get("is_amendment"))
    ]
    gstr1_current_records = [
        r for r in gstr1_records if not bool(r.get("is_amendment"))
    ]

    # SR rows whose invoice# exists in prior GSTR-1 belong to amendment flow.
    sr_current_records: list[dict[str, Any]] = []
    sr_amendment_records: list[dict[str, Any]] = []
    if prior_invoice_keys:
        for rec in sr_records:
            key = _amendment_invoice_key(rec)
            if key and key in prior_invoice_keys:
                sr_amendment_records.append(rec)
            else:
                sr_current_records.append(rec)
    else:
        sr_current_records = list(sr_records)

    _log.info(
        "gstr1_reconcile: period split — SR current=%d amendment-linked=%d; "
        "GSTR-1 current=%d amendments=%d; prior_keys=%d",
        len(sr_current_records),
        len(sr_amendment_records),
        len(gstr1_current_records),
        len(gstr1_amendment_records),
        len(prior_invoice_keys),
    )

    # ── Step 2: Match (current-period originals only) ─────────────────────
    # Primary key = invoice number (not GSTIN+invoice). GSTIN typos then
    # surface as G1M7 on matched pairs instead of missing+extra doubles.
    # Amendment-linked SR rows and current b2ba/cdnra rows are excluded —
    # they are handled solely by G1M11.
    gstr1_by_invoice = _build_invoice_index(gstr1_current_records)
    # Fallback bucket for format-variant / fuzzy invoice matching.
    gstr1_by_gstin = _build_gstin_index(
        gstr1_current_records, ("recipient_gstin", "gstin"),
    )

    matched_pairs: list[tuple[dict, dict, dict]] = []  # (sr, gstr1, match_result_dict)
    unmatched_sr: list[dict[str, Any]] = []
    used_gstr1_ids: set[int] = set()

    from app.matching.generic_matcher import (
        generic_match_pair,
        SALES_MATCH_CONFIG,
    )

    def _unused(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [c for c in cands if id(c) not in used_gstr1_ids]

    for sr_rec in sr_current_records:
        inv_key = _invoice_index_key(sr_rec)
        candidates = _unused(gstr1_by_invoice.get(inv_key, []))

        # Secondary pool: same/blank GSTIN (covers invoice format variants).
        if not candidates:
            sr_gstin = ""
            for key in ("gstin",):
                v = sr_rec.get(key)
                if v is None:
                    continue
                s = str(v).strip().upper()
                if not s:
                    continue
                collapsed = "".join(ch for ch in s if ch.isalnum())
                if s in {
                    "NA", "N/A", "N.A", "N.A.", "NONE", "NULL", "NIL",
                    "-", "--", ".", "0", "UNREGISTERED", "URP",
                } or collapsed in {"NA", "NIL", "NULL", "NONE", "URP"}:
                    continue
                sr_gstin = s
                break
            gstin_pool = list(gstr1_by_gstin.get(sr_gstin, []))
            if sr_gstin:
                gstin_pool.extend(gstr1_by_gstin.get("", []))
            candidates = _unused(gstin_pool)

        match_result = (
            match_sales_register_to_gstr1(sr_rec, candidates)
            if candidates
            else None
        )

        if match_result is not None and match_result.matched:
            best_candidate = None
            best_level = 999
            for cand in candidates:
                cand_id = id(cand)
                if cand_id in used_gstr1_ids:
                    continue
                pr = generic_match_pair(sr_rec, cand, SALES_MATCH_CONFIG)
                if pr.matched and pr.level < best_level:
                    best_level = pr.level
                    best_candidate = cand

            if best_candidate is not None:
                used_gstr1_ids.add(id(best_candidate))
                matched_pairs.append(
                    (sr_rec, best_candidate, _match_result_to_dict(match_result))
                )
            else:
                matched_pairs.append(
                    (sr_rec, {}, _match_result_to_dict(match_result))
                )
        else:
            unmatched_sr.append(sr_rec)

    # Unmatched GSTR-1: current-period originals not consumed by any SR match.
    # Amendment-table rows (b2ba etc.) are intentionally omitted from G1M2.
    unmatched_gstr1: list[dict[str, Any]] = [
        rec for rec in gstr1_current_records if id(rec) not in used_gstr1_ids
    ]

    _log.info(
        "gstr1_reconcile: matching done — %d matched, %d unmatched_sr, %d unmatched_gstr1",
        len(matched_pairs), len(unmatched_sr), len(unmatched_gstr1),
    )

    # ── Step 3: Classify mismatches ───────────────────────────────────────
    mismatch_results = classify_all_mismatches(
        unmatched_sr=unmatched_sr,
        unmatched_gstr1=unmatched_gstr1,
        matched_pairs=[(sr, g1) for sr, g1, _ in matched_pairs if g1],
        gstr1_filing_period=gstr1_filing_period,
    )

    _log.info(
        "gstr1_reconcile: classified %d mismatches", len(mismatch_results),
    )

    # ── Step 3b: G1M7 buyer GSTIN verification (unique GSTINs, per-run cache)
    g1m7_results = await _verify_buyer_gstins_for_g1m7(
        sr_records, gstr1_records,
    )
    if g1m7_results:
        mismatch_results = list(mismatch_results) + list(g1m7_results)

    # ── Step 3c: G1M8 invoice series continuity / duplicate detection ────
    g1m8_results = check_invoice_series_continuity(
        sr_records, gstr1_records,
    )
    if g1m8_results:
        mismatch_results = list(mismatch_results) + list(g1m8_results)
        _log.info(
            "gstr1_reconcile: G1M8 series continuity — %d issues found",
            len(g1m8_results),
        )

    # ── Step 3d: G1M9 HSN / tax rate schedule validation ────────────────
    # Use full GSTR-1 parse (includes HSN summary rows that carry hsn+rate).
    g1m9_results = validate_hsn_rate_mapping(
        sr_records, gstr1_records_all,
    )
    if g1m9_results:
        mismatch_results = list(mismatch_results) + list(g1m9_results)
        _log.info(
            "gstr1_reconcile: G1M9 HSN/rate validation — %d issues found",
            len(g1m9_results),
        )

    # ── Step 3e: G1M10 Documents Issued Summary (Table 13) ──────────────
    gstr1_doc_issue: dict[str, Any] | None = None
    try:
        gstr1_raw = json.loads(gstr1_file_content)
        if isinstance(gstr1_raw, dict):
            raw_doc = gstr1_raw.get("doc_issue")
            if isinstance(raw_doc, dict):
                gstr1_doc_issue = raw_doc
    except (json.JSONDecodeError, TypeError, ValueError):
        gstr1_doc_issue = None

    documents_issued, g1m10_results = summarize_documents_issued(
        sr_records,
        gstr1_records_all,
        gstr1_doc_issue=gstr1_doc_issue,
    )
    if g1m10_results:
        mismatch_results = list(mismatch_results) + list(g1m10_results)
        _log.info(
            "gstr1_reconcile: G1M10 documents issued — %d series, %d flags",
            documents_issued.get("total_series", 0),
            len(g1m10_results),
        )

    # ── Step 3f: G1M11 amendment detection (Tables 9A/9B/9C) ─────────────
    if prior_provided:
        g1m11_results = detect_amendments(
            sr_records,
            prior_gstr1_records,
            prior_provided=True,
            current_amendment_records=gstr1_amendment_records,
        )
    else:
        g1m11_results = detect_amendments(
            sr_records, None, prior_provided=False,
        )
    if g1m11_results:
        mismatch_results = list(mismatch_results) + list(g1m11_results)
        _log.info(
            "gstr1_reconcile: G1M11 amendments — prior_provided=%s flags=%d",
            prior_provided,
            len(g1m11_results),
        )

    # ── Step 4: GSTR-1 vs 3B tie-out ─────────────────────────────────────
    # Tie-out still sees all parsed rows; aggregate exclusions live inside
    # reconcile_gstr1_vs_3b (hsn/nil/at are skipped there too).
    filing_freq = "monthly"
    if client_gstin_id:
        try:
            sb = get_supabase()
            cg_res = sb.table("client_gstins").select("filing_frequency").eq("id", client_gstin_id).limit(1).execute()
            if cg_res.data:
                filing_freq = str(cg_res.data[0].get("filing_frequency") or "monthly").lower().strip()
        except Exception:
            pass

    tie_out = reconcile_gstr1_vs_3b(gstr1_records_all, parsed_gstr3b, filing_frequency=filing_freq)

    _log.info(
        "gstr1_reconcile: tie-out period=%s clean=%s variances=%d",
        tie_out.ret_period, tie_out.is_clean, len(tie_out.variances),
    )

    # ── Step 5: Assemble response ─────────────────────────────────────────
    elapsed = time.perf_counter() - t0

    # Build matched rows with decision fields
    matched_output: list[dict[str, Any]] = []
    for sr_rec, gstr1_rec, mr_dict in matched_pairs:
        matched_output.append({
            "sr_record": _sanitise_record(sr_rec),
            "gstr1_record": _sanitise_record(gstr1_rec) if gstr1_rec else None,
            **mr_dict,
        })

    # Build unmatched SR rows with G1M1 decisions
    unmatched_sr_output: list[dict[str, Any]] = []
    # Build unmatched GSTR-1 rows with G1M2 decisions
    unmatched_gstr1_output: list[dict[str, Any]] = []
    # Build all mismatch decisions
    mismatch_output: list[dict[str, Any]] = []
    for mr in mismatch_results:
        d = _mismatch_result_to_dict(mr)
        mismatch_output.append(d)
        if mr.mismatch_type.value == "G1M1_MISSING_INVOICE":
            # Find the corresponding SR record
            inv_num = mr.details.get("invoice_number", "?")
            sr_match = next(
                (r for r in unmatched_sr
                 if (r.get("invoice_number") or r.get("invoice_number_normalized")) == inv_num),
                None,
            )
            unmatched_sr_output.append({
                "record": _sanitise_record(sr_match) if sr_match else {"invoice_number": inv_num},
                **d,
            })
        elif mr.mismatch_type.value == "G1M2_EXTRA_INVOICE":
            inv_num = mr.details.get("invoice_number", "?")
            g1_match = next(
                (r for r in unmatched_gstr1
                 if (r.get("invoice_number") or r.get("invoice_number_normalized")) == inv_num),
                None,
            )
            unmatched_gstr1_output.append({
                "record": _sanitise_record(g1_match) if g1_match else {"invoice_number": inv_num},
                **d,
            })

    # Tie-out section
    tie_out_output: dict[str, Any] = tie_out.summary_dict()
    tie_out_output["mismatch_decisions"] = [
        _mismatch_result_to_dict(m) for m in tie_out.mismatches
    ]

    return {
        "success": True,
        "elapsed_seconds": round(elapsed, 3),
        "summary": {
            "sr_total_records": len(sr_records),
            "gstr1_total_records": len(gstr1_records),
            "gstr1_metadata_record_count": gstr1_metadata_count,
            "matched_count": len(matched_pairs),
            "unmatched_sr_count": len(unmatched_sr),
            "unmatched_gstr1_count": len(unmatched_gstr1),
            "mismatch_count": len(mismatch_results),
            "tie_out_clean": tie_out.is_clean,
            "tie_out_variance_count": len(tie_out.variances),
            "documents_issued_series_count": documents_issued.get(
                "total_series", 0
            ),
            "amendment_detection_skipped": not prior_provided,
            "amendment_count": sum(
                1
                for m in g1m11_results
                if m.details.get("issue_type") in {
                    "amendment_required",
                    "amendment_missing",
                    "amendment_still_wrong",
                }
            ),
            "amendment_linked_sr_count": len(sr_amendment_records),
            "gstr1_amendment_record_count": len(gstr1_amendment_records),
        },
        "matched": matched_output,
        "unmatched_sr": unmatched_sr_output,
        "unmatched_gstr1": unmatched_gstr1_output,
        "mismatches": mismatch_output,
        "documents_issued": documents_issued,
        "tie_out": tie_out_output,
        "parse_diagnostics": {
            "sr": {
                "total_rows": sr_result.get("total_rows", 0),
                "valid_rows": sr_result.get("valid_rows", 0),
                "skipped_rows": sr_result.get("skipped_rows", 0),
                "source_software": sr_result.get("source_software", ""),
                "detected_columns": sr_result.get("detected_columns", {}),
                "warnings": sr_result.get("warnings", []),
                "errors": sr_result.get("errors", []),
                "sheets_used": sr_result.get("sheets_used", []),
                "sheets_skipped": sr_result.get("sheets_skipped", []),
            },
            "gstr1": {
                "filing_gstin": gstr1_result.get("filing_gstin", ""),
                "filing_period": gstr1_result.get("filing_period", ""),
                "total_parsed": gstr1_result.get("total_parsed", 0),
                "total_skipped": gstr1_result.get("total_skipped", 0),
                "section_counts": gstr1_result.get("section_counts", {}),
                "sections_present": gstr1_result.get("sections_present", []),
                "skip_breakdown_labeled": gstr1_result.get("skip_breakdown_labeled", []),
            },
            "prior_gstr1": prior_gstr1_diagnostics,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════

def _assert_client_accessible(client_gstin_id: str, current_user: dict) -> None:
    sb = get_supabase()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if str(client_gstin_id).strip() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )


@router.get(
    "/runs",
    summary="List GSTR-1 reconciliation runs for a client",
)
async def list_gstr1_reconcile_runs(
    client_gstin_id: str,
    limit: int = 20,
    run_status: Optional[str] = Query(None, alias="status"),
    current_user: dict = Depends(get_current_active_user),
):
    """Return newest-first GSTR-1 runs (without full result payloads)."""
    _assert_client_accessible(client_gstin_id, current_user)
    rows = list_gstr1_runs(
        get_supabase(),
        client_gstin_id=client_gstin_id,
        limit=limit,
        status=run_status,
    )
    return rows


@router.get(
    "/runs/{run_id}",
    summary="Get a persisted GSTR-1 reconciliation run (incl. full result)",
)
async def get_gstr1_reconcile_run(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    row = get_gstr1_run(get_supabase(), run_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GSTR-1 run not found",
        )
    _assert_client_accessible(str(row.get("client_gstin_id", "")), current_user)
    return row


class Gstr1aMarkFiledBody(BaseModel):
    period: str
    confirmed: bool = False
    filed_date: Optional[str] = None
    note: Optional[str] = None


@router.get(
    "/runs/{run_id}/gstr1a-filed",
    summary="List periods marked GSTR-1A filed for a run",
)
async def list_gstr1a_filed_periods(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    row = get_gstr1_run(get_supabase(), run_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GSTR-1 run not found",
        )
    _assert_client_accessible(str(row.get("client_gstin_id", "")), current_user)
    return list_gstr1a_period_actions(get_supabase(), run_id=run_id)


@router.patch(
    "/runs/{run_id}/gstr1a-filed",
    summary="Mark GSTR-1A as filed for a period (Rule 37 settled analogue)",
)
async def mark_gstr1a_filed_for_period(
    run_id: str,
    body: Gstr1aMarkFiledBody,
    current_user: dict = Depends(get_current_active_user),
):
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Confirmation required to mark GSTR-1A as filed",
        )
    period_norm = normalise_action_period(body.period)
    if not period_norm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="period is required",
        )

    sb = get_supabase()
    row = get_gstr1_run(sb, run_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GSTR-1 run not found",
        )
    _assert_client_accessible(str(row.get("client_gstin_id", "")), current_user)

    user_id = str(current_user.get("id") or "").strip()
    try:
        saved = mark_gstr1a_period_filed(
            sb,
            run_id=run_id,
            period=period_norm,
            user_id=user_id,
            filed_date=body.filed_date,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except Exception:
        _log.exception(
            "gstr1_reconcile: mark GSTR-1A filed failed run=%s period=%s",
            run_id,
            period_norm,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark GSTR-1A as filed",
        )

    await log_audit(
        sb,
        current_user,
        "GSTR1A_MARKED_FILED",
        "gstr1_reconciliation_run",
        str(run_id),
        f"GSTR-1A filed · {period_norm}",
        {
            "period": period_norm,
            "status": saved.get("status"),
            "filed_date": saved.get("filed_date"),
            "action_id": saved.get("id"),
            "client_gstin_id": row.get("client_gstin_id"),
        },
    )

    return {
        "id": saved.get("id"),
        "run_id": run_id,
        "period": saved.get("period") or period_norm,
        "status": saved.get("status") or "filed",
        "filed_date": saved.get("filed_date"),
        "note": saved.get("note"),
        "acted_by": saved.get("user_id") or user_id,
        "acted_at": saved.get("created_at"),
    }


@router.post(
    "",
    summary="Run GSTR-1 sales-side reconciliation",
    response_description=(
        "Combined reconciliation results with WHAT/WHY/NEXT decisions "
        "for matched, unmatched, and mismatched invoices, plus GSTR-1 vs GSTR-3B tie-out."
    ),
)
async def reconcile_gstr1(
    sales_register_file: UploadFile = File(
        ..., description="Sales Register file (.xlsx / .xls / .csv)",
    ),
    gstr1_json: UploadFile = File(
        ..., description="GSTR-1 JSON file (portal download or API response)",
    ),
    gstr3b_json: UploadFile = File(
        ..., description="GSTR-3B JSON file (portal download or API response)",
    ),
    prior_gstr1_json: Optional[UploadFile] = File(
        None,
        description=(
            "Optional prior-period GSTR-1 JSON for Tables 9A/9B/9C "
            "amendment detection. When omitted, amendment checks are skipped."
        ),
    ),
    gstr1_filing_period: Optional[str] = Form(
        None,
        description=(
            "GSTR-1 filing period in MMYYYY format (e.g. '042026'). "
            "Auto-detected from GSTR-1 JSON if omitted."
        ),
    ),
    gstr1_filed_date: Optional[str] = Form(
        None,
        description=(
            "Date GSTR-1 was filed for the period (YYYY-MM-DD). "
            "Used for GSTR-1A amendment-window calculation."
        ),
    ),
    gstr3b_filed_date: Optional[str] = Form(
        None,
        description=(
            "Date GSTR-3B was filed for the period (YYYY-MM-DD). "
            "When set, the GSTR-1A window is closed."
        ),
    ),
    client_gstin_id: Optional[str] = Form(
        None,
        description=(
            "Client GSTIN row id. When provided, the successful result is "
            "persisted for later revisit (banner / results by run id)."
        ),
    ),
    current_user: dict = Depends(get_current_active_user),
):
    """Run end-to-end GSTR-1 sales-side reconciliation.

    Accepts a Sales Register file, GSTR-1 JSON, and GSTR-3B JSON.
    Optionally accepts a prior-period GSTR-1 JSON for amendment detection.
    Parses, matches, classifies mismatches, and performs a GSTR-1 vs 3B tie-out.

    Returns combined ``{WHAT, WHY, NEXT, confidence}`` results in the same
    shape as the purchase-side reconciliation API.
    """
    user_id = current_user.get("id", "?")
    _log.info(
        "gstr1_reconcile: user=%s sr=%s gstr1=%s gstr3b=%s prior_gstr1=%s",
        user_id,
        sales_register_file.filename,
        gstr1_json.filename,
        gstr3b_json.filename,
        prior_gstr1_json.filename if prior_gstr1_json else None,
    )

    # ── Validate file types ──────────────────────────────────────────────
    sr_filename = sales_register_file.filename or "upload.xlsx"
    sr_ext = sr_filename.rsplit(".", 1)[-1].lower() if "." in sr_filename else ""
    if sr_ext not in ("xlsx", "xls", "csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Sales Register must be .xlsx, .xls, or .csv — "
                f"got '.{sr_ext}'"
            ),
        )

    for upload, label in [
        (gstr1_json, "GSTR-1"),
        (gstr3b_json, "GSTR-3B"),
    ]:
        fname = upload.filename or ""
        fext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        if fext not in ("json",):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label} file must be .json — got '.{fext}'",
            )

    if prior_gstr1_json is not None and prior_gstr1_json.filename:
        prior_fname = prior_gstr1_json.filename or ""
        prior_ext = (
            prior_fname.rsplit(".", 1)[-1].lower() if "." in prior_fname else ""
        )
        if prior_ext not in ("json",):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Prior period GSTR-1 file must be .json — got '.{prior_ext}'"
                ),
            )

    # ── Read file contents ───────────────────────────────────────────────
    try:
        sr_content = await sales_register_file.read()
        gstr1_content = await gstr1_json.read()
        gstr3b_content = await gstr3b_json.read()
        prior_gstr1_content: bytes | None = None
        if prior_gstr1_json is not None and prior_gstr1_json.filename:
            prior_gstr1_content = await prior_gstr1_json.read()
    except Exception as exc:
        _log.exception("gstr1_reconcile: file read failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded files: {exc}",
        )

    if not sr_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sales Register file is empty",
        )
    if not gstr1_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GSTR-1 JSON file is empty",
        )
    if not gstr3b_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GSTR-3B JSON file is empty",
        )
    if prior_gstr1_content is not None and not prior_gstr1_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prior period GSTR-1 JSON file is empty",
        )

    # ── Run pipeline ─────────────────────────────────────────────────────
    try:
        result = await _run_pipeline(
            sr_file_content=sr_content,
            sr_filename=sr_filename,
            gstr1_file_content=gstr1_content,
            gstr3b_file_content=gstr3b_content,
            gstr1_filing_period=gstr1_filing_period,
            prior_gstr1_file_content=prior_gstr1_content,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
            _log.warning(
                "gstr1_reconcile: validation failed user=%s detail=%s",
                user_id,
                exc.detail,
            )
        raise
    except ParseError as exc:
        _log.warning("gstr1_reconcile: parse error — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "parse_error", "message": str(exc)},
        )
    except Exception:
        _log.exception("gstr1_reconcile: unhandled error user=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during GSTR-1 reconciliation",
        )

    _log.info(
        "gstr1_reconcile: completed user=%s matched=%d mismatches=%d elapsed=%.2fs",
        user_id,
        result["summary"]["matched_count"],
        result["summary"]["mismatch_count"],
        result["elapsed_seconds"],
    )

    period_norm = normalise_period(
        gstr1_filing_period
        or (result.get("parse_diagnostics") or {})
        .get("gstr1", {})
        .get("filing_period")
    )
    gstr1a_window = compute_gstr1a_window(
        gstr1_filed_date,
        gstr3b_filed_date,
        period=period_norm,
    )
    result = {
        **result,
        "gstr1_filed_date": gstr1_filed_date,
        "gstr3b_filed_date": gstr3b_filed_date,
        "gstr1a_window": gstr1a_window,
        "summary": {
            **(result.get("summary") or {}),
            "gstr1_filed_date": gstr1_filed_date,
            "gstr3b_filed_date": gstr3b_filed_date,
            "gstr1a_window": gstr1a_window,
        },
    }

    # Persist for durable banner / revisit when a client is in scope.
    run_id: str | None = None
    cg_id = (client_gstin_id or "").strip()
    if cg_id and result.get("success"):
        try:
            _assert_client_accessible(cg_id, current_user)
            saved = save_gstr1_run(
                get_supabase(),
                client_gstin_id=cg_id,
                result=result,
                created_by=str(user_id) if user_id != "?" else None,
                period=gstr1_filing_period,
                gstr1_filed_date=gstr1_filed_date,
                gstr3b_filed_date=gstr3b_filed_date,
            )
            run_id = str(saved["id"])
            result = {**result, "run_id": run_id, "client_gstin_id": cg_id}
        except HTTPException:
            raise
        except Exception:
            # Pipeline already succeeded — do not fail the request if persist fails.
            _log.exception(
                "gstr1_reconcile: persist failed user=%s client=%s",
                user_id,
                cg_id,
            )

    return result
