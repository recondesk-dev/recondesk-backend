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

from dataclasses import dataclass, field
import json
import logging
import re
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
from app.parsers.gstr1_parser import parse_gstr1, _parse_filing_period
from app.parsers.gstr3b_parser import parse_gstr3b
from app.matching.generic_matcher import match_sales_register_to_gstr1
from app.services.matcher import normalise_inv_no, normalize_invoice, _is_credit_note
from app.rules.gstr1_mismatch_rules import (
    classify_all_mismatches,
    check_invoice_series_continuity,
    validate_hsn_rate_mapping,
    reconcile_hsn_summary,
    summarize_documents_issued,
    detect_amendments,
    _amendment_invoice_key,
    classify_duplicate_identical,
    classify_duplicate_conflict,
    classify_sr_unmatched_exceptions,
    MismatchResult,
    MismatchType,
    MismatchSeverity,
    AMOUNT_TOLERANCE_PAISE,
    _rs,
    _safe_int,
)
from app.reconciliation.gstr1_vs_3b import reconcile_gstr1_vs_3b

_log = logging.getLogger(__name__)

# Aggregate / informational GSTR-1 rows (HSN summary, nil, advances, B2CS, etc.).
# These are parsed for diagnostics / tie-out exclusions / aggregate recon but
# must never enter invoice-level matching or Extra-in-GSTR-1 (G1M2) classification.
_NON_INVOICE_GSTR1_SECTIONS: frozenset[str] = frozenset({
    "hsn", "nil", "doc_issue", "at", "ata", "atadj", "atadja", "b2cs", "b2csa",
})
_NON_INVOICE_GSTR1_TYPES: frozenset[str] = frozenset({
    "HSN_SUMMARY", "NIL_RATED", "EXEMPT", "NON_GST", "NIL_EXEMPT", "ADVANCES", "B2C_SMALL",
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


def _categorize_mismatch(mr: MismatchResult) -> str:
    mtype = getattr(mr.mismatch_type, "value", str(mr.mismatch_type))
    severity = getattr(mr.severity, "value", str(mr.severity)).lower()
    issue_type = str(mr.details.get("issue_type") or "").lower()

    if severity == "info" or issue_type == "amendment_detection_skipped" or issue_type.endswith("_skipped"):
        return "info_notice"
    if mtype in ("G1M8_INVOICE_SERIES_ISSUE", "G1M10_DOCUMENTS_ISSUED_SUMMARY"):
        return "compliance_warning"
    if mtype in ("G1M3_AMOUNT_MISMATCH", "G1M12_DATE_OUTSIDE_TOLERANCE", "G1D2_DUPLICATE_CONFLICT") or mr.details.get("requires_review"):
        return "review_required"
    return "reconciliation_mismatch"


def _mismatch_result_to_dict(mr: MismatchResult) -> dict[str, Any]:
    """Serialise a ``MismatchResult`` to the unified decision dict."""
    d = mr.to_dict()
    d["category"] = _categorize_mismatch(mr)
    # Ensure the unified decision_confidence field is present
    if "decision_confidence" not in d:
        d["decision_confidence"] = mr.to_decision_output().confidence
    return d


DEFAULT_MAX_BUYER_GSTIN_LIVE_LOOKUPS = 20
DEFAULT_BUYER_GSTIN_TOTAL_TIMEOUT_SECONDS = 12.0
DEFAULT_BUYER_GSTIN_PER_CALL_TIMEOUT_SECONDS = 3.0


async def _verify_buyer_gstins_for_g1m7(
    sr_records: list[dict[str, Any]],
    gstr1_records: list[dict[str, Any]],
    *,
    rate_limit_seconds: float = 0.15,
    max_live_lookups: int = DEFAULT_MAX_BUYER_GSTIN_LIVE_LOOKUPS,
    total_timeout_seconds: float = DEFAULT_BUYER_GSTIN_TOTAL_TIMEOUT_SECONDS,
    per_call_timeout_seconds: float = DEFAULT_BUYER_GSTIN_PER_CALL_TIMEOUT_SECONDS,
) -> list[MismatchResult]:
    """Verify unique buyer GSTINs once per run and build G1M7 mismatches.

    Reuses ``app.services.gstin_verification.verify_gstin`` (Sandbox.co.in).
    Format-invalid GSTINs are flagged locally without an API call.
    Live external Sandbox API lookups are capped at ``max_live_lookups`` and
    guarded by a strict time budget (``total_timeout_seconds``) to prevent
    synchronous HTTP reconciliation timeouts on large files (e.g. 3,000+ invoices).
    Infrastructure failures or timeouts are non-blocking.
    """
    import asyncio
    import time

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

    # 1. Local format check on ALL unique buyer GSTINs (< 1ms, 0 network calls)
    format_valid_gstins: list[str] = []
    for gstin, refs in gstin_refs.items():
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
        else:
            format_valid_gstins.append(gstin)

    # 2. Prioritize format-valid GSTINs by invoice frequency (highest impact first)
    format_valid_gstins.sort(key=lambda g: (-len(gstin_refs.get(g, [])), g))

    # Cap live lookups to prevent unbounded external HTTP requests
    live_targets = format_valid_gstins[:max_live_lookups] if max_live_lookups > 0 else format_valid_gstins
    if len(format_valid_gstins) > len(live_targets):
        _log.info(
            "gstr1_reconcile: %d format-valid buyer GSTINs detected; capping live "
            "Sandbox verification to top %d by invoice volume to prevent HTTP timeout.",
            len(format_valid_gstins),
            len(live_targets),
        )

    # 3. Perform live Sandbox lookups bounded by total time budget
    start_time = time.monotonic()
    live_verified_count = 0

    for gstin in live_targets:
        if not api_enabled:
            break

        # Check total time budget
        elapsed = time.monotonic() - start_time
        if total_timeout_seconds > 0 and elapsed >= total_timeout_seconds:
            _log.warning(
                "gstr1_reconcile: GSTIN verification reached %.1fs time budget "
                "(%d/%d verified). Proceeding with reconciliation.",
                total_timeout_seconds,
                live_verified_count,
                len(live_targets),
            )
            break

        try:
            # Enforce individual per-call timeout
            if per_call_timeout_seconds > 0:
                res = await asyncio.wait_for(
                    verify_gstin(gstin),
                    timeout=per_call_timeout_seconds,
                )
            else:
                res = await verify_gstin(gstin)
            verification_cache[gstin] = res
            live_verified_count += 1
        except asyncio.TimeoutError:
            _log.warning(
                "gstr1_reconcile: GSTIN lookup timed out for %s (%.1fs). "
                "Skipping remaining live lookups for this run.",
                gstin[:5] + "...",
                per_call_timeout_seconds,
            )
            api_enabled = False
            break
        except Exception as exc:  # noqa: BLE001 — never fail the recon run
            _log.error(
                "gstr1_reconcile: GSTIN verification unavailable – %s. "
                "Skipping remaining Sandbox lookups for this run.",
                exc,
            )
            api_enabled = False
            break

        if rate_limit_seconds > 0:
            await asyncio.sleep(rate_limit_seconds)

    g1m7 = build_g1m7_mismatches(
        gstin_refs=gstin_refs,
        verification_by_gstin=verification_cache,
    )
    _log.info(
        "gstr1_reconcile: G1M7 GSTIN verification — unique=%d live_verified=%d "
        "flagged=%d api_enabled=%s elapsed=%.2fs",
        len(gstin_refs),
        live_verified_count,
        len(g1m7),
        api_enabled,
        time.monotonic() - start_time,
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


def _extract_doc_number(rec: Mapping[str, Any]) -> str:
    """Extract raw invoice or credit/debit note number from a record."""
    for field in (
        "inum",
        "nt_num",
        "ntnum",
        "credit_note_number",
        "note_number",
        "invoice_number_raw",
        "invoice_number",
        "invoice_number_normalized",
    ):
        v = rec.get(field)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _candidate_keys_for_record(rec: Mapping[str, Any]) -> list[str]:
    """Generate normalized lookup keys for candidate indexing/matching."""
    from app.services.matcher import invoice_match_key_for_record, ocr_canonical_invoice

    keys: list[str] = []
    doc = _extract_doc_number(rec)
    if doc:
        norm = normalise_inv_no(doc)
        if norm and norm not in keys:
            keys.append(norm)
            # Prefix-stripped key (e.g. "INV202526001" -> "202526001")
            core = re.sub(r"^[A-Z]+", "", norm)
            if core and core not in keys:
                keys.append(core)

        ocr_key = ocr_canonical_invoice(doc)
        if ocr_key and ocr_key not in keys:
            keys.append(ocr_key)
            core_ocr = re.sub(r"^[A-Z]+", "", ocr_key)
            if core_ocr and core_ocr not in keys:
                keys.append(core_ocr)

    try:
        k = invoice_match_key_for_record(rec)
        if k and str(k).strip().upper() not in keys:
            keys.append(str(k).strip().upper())
    except Exception:
        pass

    for field in ("invoice_number_normalized", "invoice_number"):
        raw = rec.get(field)
        if raw is not None:
            s = str(raw).strip().upper()
            if s and s not in keys:
                keys.append(s)

    return keys


def _invoice_index_key(rec: Mapping[str, Any]) -> str:
    """Normalized invoice key used for sales-side candidate lookup."""
    doc = _extract_doc_number(rec)
    if doc:
        norm = normalise_inv_no(doc)
        if norm:
            return norm
    keys = _candidate_keys_for_record(rec)
    return keys[0] if keys else ""


def _build_invoice_index(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group records by normalized invoice number for O(1) candidate lookup."""
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        for key in _candidate_keys_for_record(rec):
            if rec not in index[key]:
                index[key].append(rec)
    return dict(index)


def _is_sr_b2cs_record(
    rec: Mapping[str, Any],
    supplier_gstin: str | None = None,
    b2cl_invoice_keys: set[str] | None = None,
    return_period: str | None = None,
) -> bool:
    """Determine if a Sales Register row belongs to B2CS (Table 7 aggregate).

    Period-aware threshold via get_gstr1_rules:
    - Notification 12/2024-CT (from 2024-08 onward): B2CL threshold > ₹1,00,000 (10,000,000 paise).
    - Historical periods (up to 2024-07): B2CL threshold > ₹2,50,000 (25,000,000 paise).
    """
    if _is_credit_note(rec):
        return False
    inv_type = str(rec.get("invoice_type") or "").upper().strip()
    cust_type = str(rec.get("customer_type") or "").upper().strip()
    sec_type = str(rec.get("gstr1_section") or "").upper().strip()
    if inv_type in ("B2C_SMALL", "B2CS") or cust_type in ("B2C_SMALL", "B2CS") or sec_type in ("B2C_SMALL", "B2CS"):
        return True
    if inv_type in ("B2C_LARGE", "B2CL") or cust_type in ("B2C_LARGE", "B2CL") or sec_type in ("B2C_LARGE", "B2CL"):
        return False
    if inv_type in ("EXPORT", "NIL_RATED", "ADVANCES") or cust_type == "EXPORT":
        return False
    doc_type = str(rec.get("doc_type") or "").upper().strip()
    if doc_type in ("CREDIT_NOTE", "DEBIT_NOTE", "EXPORT"):
        return False

    # Valid 15-char recipient GSTIN -> B2B (Table 4)
    gstin = str(rec.get("gstin") or rec.get("recipient_gstin") or "").strip().upper()
    if gstin and re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$", gstin):
        return False

    # Known GSTR-1 B2CL invoice match -> B2CL (Table 5)
    inv_no = _extract_doc_number(rec)
    if b2cl_invoice_keys and inv_no:
        norm_inv = normalise_inv_no(inv_no)
        if norm_inv in b2cl_invoice_keys:
            return False

    pos = str(rec.get("place_of_supply") or rec.get("pos") or "").strip()
    pos_digits = re.match(r"^(\d{2})", pos)
    pos_code = pos_digits.group(1) if pos_digits else ""
    if pos_code in ("96", "97"):
        return False

    supplier_state = ""
    if supplier_gstin and len(supplier_gstin) >= 2 and supplier_gstin[:2].isdigit():
        supplier_state = supplier_gstin[:2]

    inv_val_paise = _safe_int(rec.get("invoice_value_paise") or rec.get("total_amount_paise"))
    if not inv_val_paise:
        taxable_paise = _safe_int(rec.get("taxable_amount_paise"))
        tax_paise = _safe_int(rec.get("total_tax_paise"))
        inv_val_paise = taxable_paise + tax_paise

    is_interstate = (
        bool(pos_code and supplier_state and pos_code != supplier_state)
        or _safe_int(rec.get("igst_paise")) > 0
    )

    from app.rules.gstr1_rules import get_gstr1_rules
    rules = get_gstr1_rules(return_period)
    b2cl_threshold = rules.b2cl_threshold_paise

    # B2CL threshold: interstate unregistered > threshold -> Table 5 B2CL
    if is_interstate and inv_val_paise > b2cl_threshold:
        return False

    # Intra-state unregistered or inter-state <= threshold -> Table 7 B2CS
    return True


@dataclass
class B2CSReconciliationResult:
    """Structured result of B2CS aggregate reconciliation."""
    matched: list[tuple[dict, dict, dict]]
    mismatches: list[MismatchResult]
    status: str                         # "MATCHED", "MISMATCH", "NOT_APPLICABLE"
    source_invoice_count: int           # count of underlying SR invoices
    group_count: int                    # dimensional groups count
    matched_group_count: int
    accounted_invoice_count: int        # source invoices covered by matched groups
    unaccounted_invoice_count: int
    groups: list[dict[str, Any]]
    unaccounted_invoice_numbers: list[str] = field(default_factory=list)

    def __iter__(self):
        """Allows legacy unpacking as `matched, mismatches = reconcile_b2cs_aggregate(...)`."""
        return iter((self.matched, self.mismatches))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_invoice_count": self.source_invoice_count,
            "group_count": self.group_count,
            "matched_group_count": self.matched_group_count,
            "accounted_invoice_count": self.accounted_invoice_count,
            "unaccounted_invoice_count": self.unaccounted_invoice_count,
            "unaccounted_invoice_numbers": self.unaccounted_invoice_numbers,
            "groups": self.groups,
            "matches": [
                {
                    "sr_record": _sanitise_record(sr_rec),
                    "gstr1_record": _sanitise_record(g1_rec) if g1_rec else None,
                    **mr_dict,
                }
                for sr_rec, g1_rec, mr_dict in self.matched
            ],
            "mismatch_count": len(self.mismatches),
        }


def _extract_b2cs_dimensions(rec: Mapping[str, Any], supplier_state: str = "") -> tuple[str, float | None, str]:
    pos_raw = str(rec.get("place_of_supply") or rec.get("pos") or "").strip()
    m_pos = re.match(r"^(\d{2})", pos_raw)
    pos = m_pos.group(1) if m_pos else (supplier_state or "")

    # 1. Group using explicit GST rate (rt) only
    rate: float | None = None
    for k in ("rt", "rate", "tax_rate", "gst_rate"):
        if k in rec and rec[k] is not None:
            try:
                rate = round(float(rec[k]), 2)
                break
            except (TypeError, ValueError):
                pass

    if rate is None:
        # Check items if present
        items = rec.get("items")
        if isinstance(items, list) and items:
            for it in items:
                for k in ("tax_rate", "rate", "rt", "gst_rate"):
                    if k in it and it[k] is not None:
                        try:
                            rate = round(float(it[k]), 2)
                            break
                        except (TypeError, ValueError):
                            pass
                if rate is not None:
                    break

    if rate is None:
        # Check explicit component rates (e.g. igst_rate or cgst_rate + sgst_rate)
        try:
            if rec.get("igst_rate") is not None:
                rate = round(float(rec["igst_rate"]), 2)
            elif rec.get("cgst_rate") is not None and rec.get("sgst_rate") is not None:
                rate = round(float(rec["cgst_rate"]) + float(rec["sgst_rate"]), 2)
        except (TypeError, ValueError):
            pass

    # 2. Check if cess is present
    has_cess = (
        _safe_int(rec.get("cess_paise")) > 0
        or _safe_int(rec.get("cess")) > 0
        or _safe_int(rec.get("csamt")) > 0
        or rec.get("cess_rate") is not None
        or (
            isinstance(rec.get("items"), list)
            and any(
                _safe_int(it.get("cess_paise")) > 0
                or _safe_int(it.get("csamt")) > 0
                or it.get("cess_rate") is not None
                for it in rec.get("items", [])
            )
        )
    )

    # 3. CRITICAL: Never derive the B2CS GST rate from total tax / taxable value when cess is present.
    # Group using explicit GST rate (rt) only. Cess must remain a separate dimension/value
    # and must not be added to CGST/SGST/IGST rate.
    if rate is None and not has_cess:
        txval = _safe_int(rec.get("taxable_amount_paise"))
        gst_tax = (
            _safe_int(rec.get("igst_paise"))
            + _safe_int(rec.get("cgst_paise"))
            + _safe_int(rec.get("sgst_paise"))
        )
        if txval > 0 and gst_tax >= 0:
            raw_calc = (gst_tax / txval) * 100.0
            common_rates = [0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 6.0, 12.0, 18.0, 28.0]
            matched_rate = min(common_rates, key=lambda r: abs(r - raw_calc))
            if abs(matched_rate - raw_calc) < 0.25:
                rate = matched_rate
            else:
                rate = round(raw_calc, 2)

    sply_ty = str(
        rec.get("supply_type")
        or rec.get("sply_ty")
        or rec.get("sply_tp")
        or ""
    ).strip().upper()
    if not sply_ty or sply_ty not in ("INTER", "INTRA"):
        if _safe_int(rec.get("igst_paise")) > 0 or (pos and supplier_state and pos != supplier_state):
            sply_ty = "INTER"
        else:
            sply_ty = "INTRA"

    return pos, rate, sply_ty


def reconcile_b2cs_aggregate(
    sr_b2cs_records: list[dict[str, Any]],
    gstr1_b2cs_records: list[dict[str, Any]],
    *,
    supplier_gstin: str | None = None,
    tolerance_paise: int = AMOUNT_TOLERANCE_PAISE,
) -> B2CSReconciliationResult:
    """Reconcile Sales Register B2C rows against GSTR-1 Table 7 B2CS aggregates.

    B2CS is an aggregate return section. Underlying Sales Register rows are reconciled
    by statutory GST dimensions: Place of Supply (POS), Tax Rate, and Supply Type.
    Returns a B2CSReconciliationResult without creating fake individual invoices
    or inflating headline invoice match counts.
    """
    matched: list[tuple[dict, dict, dict]] = []
    mismatches: list[MismatchResult] = []

    if not sr_b2cs_records and not gstr1_b2cs_records:
        return B2CSReconciliationResult(
            matched=matched,
            mismatches=mismatches,
            status="NOT_APPLICABLE",
            source_invoice_count=0,
            group_count=0,
            matched_group_count=0,
            accounted_invoice_count=0,
            unaccounted_invoice_count=0,
            groups=[],
        )

    supplier_state = ""
    if supplier_gstin and len(supplier_gstin) >= 2 and supplier_gstin[:2].isdigit():
        supplier_state = supplier_gstin[:2]

    # Group SR records by dimension (pos, rate, supply_type)
    sr_dim_groups: dict[tuple[str, float | None, str], list[dict[str, Any]]] = {}
    for r in sr_b2cs_records:
        dim = _extract_b2cs_dimensions(r, supplier_state)
        sr_dim_groups.setdefault(dim, []).append(r)

    # Group GSTR-1 records by dimension (pos, rate, supply_type)
    g1_dim_groups: dict[tuple[str, float | None, str], list[dict[str, Any]]] = {}
    for r in gstr1_b2cs_records:
        dim = _extract_b2cs_dimensions(r, supplier_state)
        g1_dim_groups.setdefault(dim, []).append(r)

    all_dims = sorted(
        set(sr_dim_groups.keys()) | set(g1_dim_groups.keys()),
        key=lambda d: (d[0], d[1] if d[1] is not None else -1, d[2]),
    )

    group_details: list[dict[str, Any]] = []
    accounted_source_invoices = 0
    matched_groups_count = 0
    matched_dims: set[tuple[str, float | None, str]] = set()

    # If both sides are single un-dimensioned aggregates (e.g. flat totals in tests)
    has_dimensions = any(d[0] or d[1] is not None for d in all_dims)
    if not has_dimensions and (len(all_dims) <= 1):
        dims_to_evaluate = [all_dims[0]] if all_dims else [("", None, "INTRA")]
    else:
        dims_to_evaluate = all_dims

    for dim in dims_to_evaluate:
        pos, rate, sply_ty = dim
        sr_list = sr_dim_groups.get(dim, [])
        g1_list = g1_dim_groups.get(dim, [])

        sr_txval = sum(_safe_int(r.get("taxable_amount_paise")) for r in sr_list)
        sr_igst = sum(_safe_int(r.get("igst_paise")) for r in sr_list)
        sr_cgst = sum(_safe_int(r.get("cgst_paise")) for r in sr_list)
        sr_sgst = sum(_safe_int(r.get("sgst_paise")) for r in sr_list)
        sr_cess = sum(_safe_int(r.get("cess_paise")) for r in sr_list)
        sr_gst_tax = sr_igst + sr_cgst + sr_sgst
        sr_tot_tax = sr_gst_tax + sr_cess

        g1_txval = sum(_safe_int(r.get("taxable_amount_paise")) for r in g1_list)
        g1_igst = sum(_safe_int(r.get("igst_paise")) for r in g1_list)
        g1_cgst = sum(_safe_int(r.get("cgst_paise")) for r in g1_list)
        g1_sgst = sum(_safe_int(r.get("sgst_paise")) for r in g1_list)
        g1_cess = sum(_safe_int(r.get("cess_paise")) for r in g1_list)
        g1_gst_tax = g1_igst + g1_cgst + g1_sgst
        g1_tot_tax = g1_gst_tax + g1_cess

        txval_diff = abs(sr_txval - g1_txval)
        gst_tax_diff = abs(sr_gst_tax - g1_gst_tax)
        cess_diff = abs(sr_cess - g1_cess)
        tot_tax_diff = abs(sr_tot_tax - g1_tot_tax)

        # Match condition: Cess must remain a separate dimension/value and must not be added to CGST/SGST/IGST
        is_group_matched = (
            txval_diff <= tolerance_paise
            and gst_tax_diff <= tolerance_paise
            and cess_diff <= tolerance_paise
        )

        group_label = f"POS {pos or 'NA'} · {rate if rate is not None else 'NA'}% · {sply_ty}"

        group_info = {
            "dimension": {"pos": pos, "rate": rate, "supply_type": sply_ty},
            "group_label": group_label,
            "status": "MATCHED" if is_group_matched else "MISMATCH",
            "sr_invoices_count": len(sr_list),
            "sr_taxable_paise": sr_txval,
            "sr_gst_tax_paise": sr_gst_tax,
            "sr_cess_paise": sr_cess,
            "sr_total_tax_paise": sr_tot_tax,
            "gstr1_taxable_paise": g1_txval,
            "gstr1_gst_tax_paise": g1_gst_tax,
            "gstr1_cess_paise": g1_cess,
            "gstr1_total_tax_paise": g1_tot_tax,
            "taxable_diff_paise": txval_diff,
            "gst_tax_diff_paise": gst_tax_diff,
            "cess_diff_paise": cess_diff,
            "tax_diff_paise": tot_tax_diff,
            "unaccounted_invoice_numbers": (
                [str(r.get("invoice_number")) for r in sr_list if r.get("invoice_number")]
                if not is_group_matched
                else []
            ),
        }
        group_details.append(group_info)

        if is_group_matched:
            matched_dims.add(dim)
            matched_groups_count += 1
            accounted_source_invoices += len(sr_list)
            sr_synth = {
                "invoice_number": f"B2CS-AGGREGATE",
                "invoice_number_raw": "B2CS-AGGREGATE",
                "gstin": "B2C",
                "recipient_name": f"B2C Small Supplies ({len(sr_list)} invoices, {group_label})",
                "taxable_amount_paise": sr_txval,
                "igst_paise": sr_igst,
                "cgst_paise": sr_cgst,
                "sgst_paise": sr_sgst,
                "cess_paise": sr_cess,
                "total_tax_paise": sr_tot_tax,
                "invoice_type": "B2C_SMALL",
                "doc_type": "INVOICE",
            }
            g1_synth = {
                "invoice_number": f"B2CS-AGGREGATE",
                "invoice_number_raw": "B2CS-AGGREGATE",
                "gstin": "B2C",
                "recipient_name": f"GSTR-1 Table 7 B2CS Aggregate ({group_label})",
                "taxable_amount_paise": g1_txval,
                "igst_paise": g1_igst,
                "cgst_paise": g1_cgst,
                "sgst_paise": g1_sgst,
                "cess_paise": g1_cess,
                "total_tax_paise": g1_tot_tax,
                "invoice_type": "B2C_SMALL",
                "doc_type": "INVOICE",
            }
            mr_dict = {
                "match_level": 1,
                "confidence": 100,
                "decision_what": f"B2CS aggregate matched for {group_label}",
                "decision_why": f"Sales Register B2C aggregate matches GSTR-1 Table 7 ({group_label})",
                "decision_next": "No action required",
                "decision_confidence": "HIGH",
                "decision_rule": "L1_B2CS_AGGREGATE_MATCH",
                "requires_human_review": False,
                "identity_confidence": "High",
                "financial_status": "Exact",
                "review_reason": None,
                "discrepancies": [],
                "compared_fields": [
                    {"field": "taxable_amount", "status": "exact"},
                    {"field": "gst_tax", "status": "exact"},
                    {"field": "cess", "status": "exact"},
                    {"field": "total_tax", "status": "exact"},
                ],
            }
            matched.append((sr_synth, g1_synth, mr_dict))
        else:
            mismatches.append(
                MismatchResult(
                    mismatch_type=MismatchType.AMOUNT_MISMATCH,
                    severity=MismatchSeverity.HIGH,
                    decision_what=(
                        f"B2CS aggregate mismatch ({group_label}): Sales Register taxable {_rs(sr_txval)} "
                        f"vs GSTR-1 Table 7 {_rs(g1_txval)} (diff {_rs(txval_diff)})"
                    ),
                    decision_why=(
                        f"Under Section 37 of the CGST Act, consolidated B2C Small supplies "
                        f"reported in GSTR-1 Table 7 must align with accounting books by state and rate. "
                        f"Variance in {group_label} results in output tax discrepancy."
                    ),
                    decision_next="Reconcile Sales Register B2C rows for this dimension against GSTR-1 Table 7 and amend if needed.",
                    rule_id="G1M_003_B2CS_AGGREGATE",
                    details={
                        "invoice_number": "B2CS-AGGREGATE",
                        "dimension": {"pos": pos, "rate": rate, "supply_type": sply_ty},
                        "sr_invoices_count": len(sr_list),
                        "sr_taxable": sr_txval,
                        "gstr1_taxable": g1_txval,
                        "taxable_diff": txval_diff,
                        "sr_gst_tax": sr_gst_tax,
                        "gstr1_gst_tax": g1_gst_tax,
                        "gst_tax_diff": gst_tax_diff,
                        "sr_cess": sr_cess,
                        "gstr1_cess": g1_cess,
                        "cess_diff": cess_diff,
                        "sr_tax": sr_tot_tax,
                        "gstr1_tax": g1_tot_tax,
                        "tax_diff": tot_tax_diff,
                        "issue_type": "b2cs_aggregate_mismatch",
                        "unaccounted_invoice_numbers": [
                            str(r.get("invoice_number")) for r in sr_list if r.get("invoice_number")
                        ],
                    },
                )
            )

    overall_status = "MATCHED" if len(mismatches) == 0 else "MISMATCH"
    # Ensure unaccounted_invoice_count counts actual source invoices belonging to mismatched dimensions,
    # NOT the number of mismatched aggregate dimensions!
    unaccounted_invoices = sum(len(sr_dim_groups.get(dim, [])) for dim in dims_to_evaluate if dim not in matched_dims)
    unaccounted_invoice_numbers = [
        str(r.get("invoice_number"))
        for dim in dims_to_evaluate if dim not in matched_dims
        for r in sr_dim_groups.get(dim, [])
        if r.get("invoice_number")
    ]

    return B2CSReconciliationResult(
        matched=matched,
        mismatches=mismatches,
        status=overall_status,
        source_invoice_count=len(sr_b2cs_records),
        group_count=len(dims_to_evaluate),
        matched_group_count=matched_groups_count,
        accounted_invoice_count=accounted_source_invoices,
        unaccounted_invoice_count=unaccounted_invoices,
        groups=group_details,
        unaccounted_invoice_numbers=unaccounted_invoice_numbers,
    )


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
    client_gstin_id: str | None = None,
) -> dict[str, Any]:
    """Execute the full GSTR-1 reconciliation pipeline.

    Returns a JSON-serialisable result dict.
    """
    t0 = time.perf_counter()

    # ── Step 0: Validate filing period if explicitly supplied ─────────────
    if gstr1_filing_period and str(gstr1_filing_period).strip():
        try:
            fp_dt = _parse_filing_period(str(gstr1_filing_period).strip())
            gstr1_filing_period = f"{fp_dt.month:02d}{fp_dt.year}"
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error": "gstr1_parse_failed",
                    "message": "invalid_filing_period",
                },
            )
    else:
        gstr1_filing_period = None

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
        gstr1_result = parse_gstr1(gstr1_file_content, filing_period=gstr1_filing_period)
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
        prior_invoice_keys = set()
        for r in prior_gstr1_records:
            k1 = _amendment_invoice_key(r)
            if k1:
                prior_invoice_keys.add(k1)
            raw = r.get("inum") or r.get("nt_num") or r.get("invoice_number_raw") or r.get("invoice_number")
            if raw:
                prior_invoice_keys.add(normalize_invoice(str(raw).strip()))
                prior_invoice_keys.add(normalise_inv_no(str(raw).strip()))
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

    # Resolve and link Table 9 amendments to Sales Register and prior filings
    from app.services.gstr1_amendment_engine import process_gstr1_amendments

    amendment_recon = process_gstr1_amendments(
        current_amendment_records=gstr1_amendment_records,
        sr_records=sr_records,
        prior_gstr1_records=prior_gstr1_records,
        filing_period=gstr1_filing_period,
    )
    accounted_amendment_sr_ids = amendment_recon["accounted_sr_ids"]
    sr_amendment_records = amendment_recon["accounted_sr_records"]

    # Exclude source records accounted by amendments from standard invoice matching
    sr_current_records: list[dict[str, Any]] = [
        r for r in sr_records if id(r) not in accounted_amendment_sr_ids
    ]

    _log.info(
        "gstr1_reconcile: period split — SR current=%d amendment-accounted=%d; "
        "GSTR-1 current=%d amendments=%d; prior_keys=%d",
        len(sr_current_records),
        len(accounted_amendment_sr_ids),
        len(gstr1_current_records),
        len(gstr1_amendment_records),
        len(prior_invoice_keys),
    )

    # ── Step 2: Match (current-period originals only) ─────────────────────
    # Primary key = invoice number (not GSTIN+invoice). GSTIN typos then
    # surface as G1M7 on matched pairs instead of missing+extra doubles.
    # Amendment-linked SR rows and current b2ba/cdnra rows are excluded —
    # they are handled solely by G1M11.

    # Partition Sales Register into invoice-level rows vs B2CS aggregate rows.
    # B2CS (Table 7) is an aggregate section with no invoice numbers.
    supplier_gstin = gstr1_result.get("filing_gstin")
    b2cl_invoice_keys = {
        normalise_inv_no(_extract_doc_number(r))
        for r in gstr1_current_records
        if str(r.get("section") or "").lower() == "b2cl"
    }

    sr_invoice_records: list[dict[str, Any]] = []
    sr_b2cs_records: list[dict[str, Any]] = []
    for rec in sr_current_records:
        if _is_sr_b2cs_record(rec, supplier_gstin, b2cl_invoice_keys, return_period=gstr1_filing_period):
            sr_b2cs_records.append(rec)
        else:
            sr_invoice_records.append(rec)

    gstr1_b2cs_records = [
        r for r in gstr1_records_all
        if str(r.get("section") or "").lower() in ("b2cs", "b2csa")
    ]

    b2cs_recon = reconcile_b2cs_aggregate(
        sr_b2cs_records, gstr1_b2cs_records, supplier_gstin=supplier_gstin,
    )
    b2cs_matches, b2cs_mismatches = b2cs_recon.matched, b2cs_recon.mismatches

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

    # ── Step 2: Match (current-period originals only) ─────────────────────
    # Pass 1: Primary candidate keys (exact, normalized, prefix-stripped core key).
    # All high-confidence matches (L1-L3) and format variants sharing invoice keys
    # are claimed first, preventing missing invoices from stealing legitimate records.
    unmatched_sr_pass1: list[dict[str, Any]] = []

    for sr_rec in sr_invoice_records:
        sr_keys = _candidate_keys_for_record(sr_rec)
        raw_cands: list[dict[str, Any]] = []
        for k in sr_keys:
            for c in gstr1_by_invoice.get(k, []):
                if c not in raw_cands:
                    raw_cands.append(c)
        candidates = _unused(raw_cands)

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
            unmatched_sr_pass1.append(sr_rec)

    # Pass 2: Secondary pool (same/blank GSTIN) for residual unmatched SR records only.
    # Only evaluates GSTR-1 records that remained unclaimed after Pass 1.
    for sr_rec in unmatched_sr_pass1:
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

    # B2CS aggregate reconciliation is handled separately and reported via
    # b2cs_reconciliation rather than injected as a fake invoice into matched_pairs.

    # Unmatched GSTR-1: current-period originals not consumed by any SR match.
    # Amendment-table rows (b2ba etc.) are intentionally omitted from G1M2.
    unmatched_gstr1_candidates: list[dict[str, Any]] = [
        rec for rec in gstr1_current_records if id(rec) not in used_gstr1_ids
    ]

    # ── Step 2c: GSTR-1 Duplicate Detection ──────────────────────────────
    # Distinguish genuine extra invoices (G1M2) from identical or conflicting
    # duplicate filings in GSTR-1 (G1M_DUPLICATE_IDENTICAL / G1M_DUPLICATE_CONFLICT).
    # Identity key: (section, recipient_gstin, normalized_invoice_number, invoice_date, document_type).
    def _gstr1_id_key(r: Mapping[str, Any]) -> tuple:
        sec = str(r.get("section") or "").lower().strip()
        gstin = str(r.get("recipient_gstin") or r.get("ctin") or "").strip().upper()
        raw_inv = (
            r.get("invoice_number_raw")
            or r.get("invoice_number")
            or r.get("inum")
            or r.get("nt_num")
            or ""
        )
        norm_inv = normalize_invoice(str(raw_inv).strip())
        idt = str(r.get("invoice_date") or r.get("idt") or "")[:10]
        dtype = str(r.get("doc_type") or r.get("document_type") or r.get("inv_typ") or "INVOICE").strip().upper()
        return (sec, gstin, norm_inv, idt, dtype)

    matched_g1_by_key: dict[tuple, list[dict[str, Any]]] = {}
    for _, g1_rec, _ in matched_pairs:
        if g1_rec and str(g1_rec.get("section") or "").lower() not in ("b2cs", "b2csa"):
            k = _gstr1_id_key(g1_rec)
            if k[2]:
                matched_g1_by_key.setdefault(k, []).append(g1_rec)

    unmatched_gstr1: list[dict[str, Any]] = []
    surplus_gstr1_records: list[dict[str, Any]] = []
    duplicate_mismatch_results: list[MismatchResult] = []
    duplicate_groups_set: set[tuple] = set()
    identical_dup_count = 0
    conflict_dup_count = 0

    seen_unmatched_by_key: dict[tuple, dict[str, Any]] = {}

    for u_rec in unmatched_gstr1_candidates:
        sec = str(u_rec.get("section") or "").lower().strip()
        if sec in ("b2cs", "b2csa", "doc_issue", "hsn"):
            unmatched_gstr1.append(u_rec)
            continue

        k = _gstr1_id_key(u_rec)
        canon: dict[str, Any] | None = None
        if k[2] and k in matched_g1_by_key:
            canon = matched_g1_by_key[k][0]
        elif k[2] and k in seen_unmatched_by_key:
            canon = seen_unmatched_by_key[k]

        if canon is not None:
            # Surplus duplicate record found!
            surplus_gstr1_records.append(u_rec)
            duplicate_groups_set.add(k)

            diffs = []
            if _safe_int(u_rec.get("taxable_amount_paise")) != _safe_int(canon.get("taxable_amount_paise")):
                diffs.append("taxable_amount")
            if _safe_int(u_rec.get("total_tax_paise")) != _safe_int(canon.get("total_tax_paise")):
                diffs.append("total_tax")
            if _safe_int(u_rec.get("igst_paise")) != _safe_int(canon.get("igst_paise")):
                diffs.append("igst")
            if _safe_int(u_rec.get("cgst_paise")) != _safe_int(canon.get("cgst_paise")):
                diffs.append("cgst")
            if _safe_int(u_rec.get("sgst_paise")) != _safe_int(canon.get("sgst_paise")):
                diffs.append("sgst")

            if not diffs:
                identical_dup_count += 1
                duplicate_mismatch_results.append(classify_duplicate_identical(u_rec, canon))
            else:
                conflict_dup_count += 1
                duplicate_mismatch_results.append(classify_duplicate_conflict(u_rec, canon, diffs))
        else:
            if k[2]:
                seen_unmatched_by_key[k] = u_rec
            unmatched_gstr1.append(u_rec)

    _log.info(
        "gstr1_reconcile: matching done — %d matched, %d unmatched_sr, %d unmatched_gstr1 (genuine extra), "
        "%d surplus duplicates (%d identical, %d conflicting), %d b2cs_matches",
        len(matched_pairs), len(unmatched_sr), len(unmatched_gstr1),
        len(surplus_gstr1_records), identical_dup_count, conflict_dup_count, len(b2cs_matches),
    )

    # ── Step 3: Classify mismatches ───────────────────────────────────────
    # Partition unmatched SR into current-period missing vs prior-period unresolved amendment references
    unmatched_sr_current: list[dict[str, Any]] = []
    unmatched_sr_prior_unresolved: list[dict[str, Any]] = []
    for r in unmatched_sr:
        doc_no = normalize_invoice(_extract_doc_number(r))
        doc_alnum = normalise_inv_no(_extract_doc_number(r))
        if prior_invoice_keys and (doc_no in prior_invoice_keys or doc_alnum in prior_invoice_keys):
            unmatched_sr_prior_unresolved.append(r)
        else:
            unmatched_sr_current.append(r)

    # Classify unmatched SR exceptions into identical duplicates, conflicting duplicates,
    # cancelled/reissued originals, and genuine missing in GSTR-1
    (
        sr_identical_dups,
        sr_conflict_dups,
        sr_cancelled_reissued,
        genuine_missing_sr,
    ) = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr_current,
        matched_pairs=matched_pairs,
    )

    # Map each exception MismatchResult to its corresponding raw SR record for output enrichment
    sr_by_mr_id: dict[int, dict[str, Any]] = {}
    for sr_rec, mr in sr_identical_dups:
        sr_by_mr_id[id(mr)] = sr_rec
    for sr_rec, mr in sr_conflict_dups:
        sr_by_mr_id[id(mr)] = sr_rec
    for sr_rec, mr in sr_cancelled_reissued:
        sr_by_mr_id[id(mr)] = sr_rec

    matched_for_mismatch = [
        (sr, g1) for sr, g1, _ in matched_pairs
        if g1 and str(g1.get("section") or "").lower() not in ("b2cs", "b2csa")
    ]
    mismatch_results = classify_all_mismatches(
        unmatched_sr=genuine_missing_sr,
        unmatched_gstr1=unmatched_gstr1,
        matched_pairs=matched_for_mismatch,
        gstr1_filing_period=gstr1_filing_period,
    )
    if b2cs_mismatches:
        mismatch_results = list(mismatch_results) + list(b2cs_mismatches)
    if duplicate_mismatch_results:
        mismatch_results = list(mismatch_results) + list(duplicate_mismatch_results)

    # Add duplicate and cancel/reissue source exception results
    for _, mr in sr_identical_dups:
        mismatch_results.append(mr)
    for _, mr in sr_conflict_dups:
        mismatch_results.append(mr)
    for _, mr in sr_cancelled_reissued:
        mismatch_results.append(mr)

    # Route prior-period unresolved source documents to Review Required
    for sr_rec in unmatched_sr_prior_unresolved:
        inv_raw = str(sr_rec.get("invoice_number_raw") or sr_rec.get("invoice_number") or "?").strip()
        mismatch_results.append(
            MismatchResult(
                mismatch_type=MismatchType.AMENDMENT_REQUIRED,
                severity=MismatchSeverity.HIGH,
                decision_what=(
                    f"REVIEW REQUIRED — UNRESOLVED AMENDMENT ORIGINAL: Prior-period document '{inv_raw}' "
                    "was recorded in books but has no valid corresponding Table 9 amendment in GSTR-1."
                ),
                decision_why=(
                    f"Document '{inv_raw}' from prior return period was recorded in current books for revision, "
                    "but corresponding Table 9 amendment record was either missing or referenced an invalid document number."
                ),
                decision_next=(
                    f"Verify whether an amendment for '{inv_raw}' was filed under an incorrect original number, "
                    "and file a Table 9 correction if necessary."
                ),
                rule_id="G1M_011_AMENDMENT_ORIGINAL_UNRESOLVED",
                details={
                    "invoice_number": inv_raw,
                    "issue_type": "amendment_original_unresolved",
                    "requires_review": True,
                    "taxable_value": _safe_int(sr_rec.get("taxable_amount_paise")),
                    "igst": _safe_int(sr_rec.get("igst_paise")),
                    "cgst": _safe_int(sr_rec.get("cgst_paise")),
                    "sgst": _safe_int(sr_rec.get("sgst_paise")),
                },
            )
        )

    # Add duplicate amendment chain review items
    for chain_mm in amendment_recon.get("mismatches", []):
        if chain_mm.rule_id == "G1M_011_MULTIPLE_AMENDMENTS":
            mismatch_results.append(chain_mm)

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

    # ── Step 3d-2: Table 12 HSN Summary vs Outward Transactions ──────────
    hsn_reconcile_results = reconcile_hsn_summary(
        gstr1_records_all, sr_records, return_period=gstr1_filing_period,
    )
    if hsn_reconcile_results:
        mismatch_results = list(mismatch_results) + list(hsn_reconcile_results)
        _log.info(
            "gstr1_reconcile: HSN summary reconciliation — %d issues found",
            len(hsn_reconcile_results),
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

    surplus_g1_ids = {id(r) for r in surplus_gstr1_records}
    gstr1_for_tieout = [r for r in gstr1_records_all if id(r) not in surplus_g1_ids]
    tie_out = reconcile_gstr1_vs_3b(
        gstr1_for_tieout,
        parsed_gstr3b,
        filing_frequency=filing_freq,
        prior_records=prior_gstr1_records,
        canonical_amendments=amendment_recon.get("canonical_amendments"),
    )

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
    reconciliation_mismatches: list[dict[str, Any]] = []
    review_required_items: list[dict[str, Any]] = []
    series_compliance_warnings: list[dict[str, Any]] = []
    informational_notices: list[dict[str, Any]] = []

    for mr in mismatch_results:
        d = _mismatch_result_to_dict(mr)
        cat = d.get("category", "reconciliation_mismatch")
        mismatch_output.append(d)
        if cat == "reconciliation_mismatch":
            reconciliation_mismatches.append(d)
        elif cat == "review_required":
            review_required_items.append(d)
        elif cat == "compliance_warning":
            series_compliance_warnings.append(d)
        elif cat == "info_notice":
            informational_notices.append(d)

        if mr.mismatch_type.value in (
            "G1M1_MISSING_INVOICE",
            "G1D1_DUPLICATE_IDENTICAL",
            "G1D2_DUPLICATE_CONFLICT",
            "G1C1_CANCEL_REISSUE",
        ):
            # Prefer the exact original SR record if tracked via sr_by_mr_id
            sr_match = sr_by_mr_id.get(id(mr))
            if not sr_match:
                inv_num = mr.details.get("invoice_number", "?")
                norm_inv = normalise_inv_no(inv_num)
                sr_match = next(
                    (r for r in unmatched_sr
                     if (norm_inv and normalise_inv_no(_extract_doc_number(r)) == norm_inv)
                     or (r.get("invoice_number") or r.get("invoice_number_normalized")) == inv_num),
                    None,
                )
            unmatched_sr_output.append({
                "record": _sanitise_record(sr_match) if sr_match else {"invoice_number": mr.details.get("invoice_number", "?")},
                **d,
            })
        elif mr.mismatch_type.value == "G1M2_EXTRA_INVOICE":
            inv_num = mr.details.get("invoice_number", "?")
            norm_inv = normalise_inv_no(inv_num)
            g1_match = next(
                (r for r in unmatched_gstr1
                 if (norm_inv and normalise_inv_no(_extract_doc_number(r)) == norm_inv)
                 or (r.get("invoice_number") or r.get("invoice_number_normalized")) == inv_num),
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
            "invoice_level_match_count": len(matched_pairs),
            "aggregate_source_invoice_count": b2cs_recon.source_invoice_count,
            "aggregate_group_count": b2cs_recon.group_count,
            "accounted_source_invoice_count": (
                len(matched_pairs)
                + b2cs_recon.accounted_invoice_count
                + len(accounted_amendment_sr_ids)
            ),
            "unaccounted_source_invoice_count": (
                len(unmatched_sr_current)
                + len(unmatched_sr_prior_unresolved)
                + b2cs_recon.unaccounted_invoice_count
            ),
            "coverage_percentage": round(
                100.0
                * (len(matched_pairs) + b2cs_recon.accounted_invoice_count + len(accounted_amendment_sr_ids))
                / len(sr_records),
                2,
            ) if sr_records else 100.0,
            "b2cs_reconciliation_status": b2cs_recon.status,
            "unmatched_sr_count": len(unmatched_sr_current),
            "missing_in_gstr1_count": len(genuine_missing_sr),
            "genuine_missing_count": len(genuine_missing_sr),
            "duplicate_identical_count": len(sr_identical_dups) + identical_dup_count,
            "duplicate_conflict_count": len(sr_conflict_dups) + conflict_dup_count,
            "duplicate_sr_identical_count": len(sr_identical_dups),
            "duplicate_sr_conflict_count": len(sr_conflict_dups),
            "duplicate_postings_count": len(sr_identical_dups) + len(sr_conflict_dups),
            "cancelled_reissued_count": len(sr_cancelled_reissued),
            "amendment_accounted_source_count": len(accounted_amendment_sr_ids),
            "unmatched_gstr1_count": len(unmatched_gstr1),
            "duplicate_gstr1_group_count": len(duplicate_groups_set),
            "duplicate_gstr1_record_count": len(surplus_gstr1_records),
            "identical_duplicate_count": len(sr_identical_dups) + identical_dup_count,
            "conflicting_duplicate_count": len(sr_conflict_dups) + conflict_dup_count,
            "reconciliation_mismatch_count": len(reconciliation_mismatches),
            "review_required_count": len(review_required_items),
            "series_compliance_warning_count": len(series_compliance_warnings),
            "compliance_warning_count": len(series_compliance_warnings),
            "info_notice_count": len(informational_notices),
            "total_mismatch_count": len(mismatch_output),
            "mismatch_count": len(reconciliation_mismatches),
            "tie_out_clean": tie_out.is_clean,
            "tie_out_variance_count": len(tie_out.variances),
            "documents_issued_series_count": documents_issued.get(
                "total_series", 0
            ),
            "amendment_detection_skipped": not prior_provided,
            "amendment_count": (
                len(amendment_recon.get("canonical_amendments", []))
                if amendment_recon.get("canonical_amendments")
                else sum(
                    1
                    for m in g1m11_results
                    if m.details.get("issue_type") in {
                        "amendment_required",
                        "amendment_missing",
                        "amendment_still_wrong",
                        "unmatched_amendment",
                    }
                )
            ),
            "amendment_linked_sr_count": len(accounted_amendment_sr_ids),
            "gstr1_amendment_record_count": len(gstr1_amendment_records),
            "amendment_chains_count": len([c for c in amendment_recon.get("chains_summary", []) if c.get("is_duplicate_chain")]),
        },
        "matched": matched_output,
        "unmatched_sr": unmatched_sr_output,
        "unmatched_gstr1": unmatched_gstr1_output,
        "mismatches": mismatch_output,
        "reconciliation_mismatches": reconciliation_mismatches,
        "review_required_items": review_required_items,
        "series_compliance_warnings": series_compliance_warnings,
        "compliance_warnings": series_compliance_warnings,
        "informational_notices": informational_notices,
        "b2cs_reconciliation": b2cs_recon.to_dict(),
        "amendments": [a.to_dict() for a in amendment_recon.get("canonical_amendments", [])],
        "amendment_chains": amendment_recon.get("chains_summary", []),
        "documents_issued": documents_issued,
        "duplicates": [_mismatch_result_to_dict(m) for m in duplicate_mismatch_results],
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
    if sr_ext not in ("xlsx", "xls", "csv", "zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Sales Register must be .xlsx, .xls, .csv, or .zip — "
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
            client_gstin_id=client_gstin_id,
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
