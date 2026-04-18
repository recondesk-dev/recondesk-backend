"""Import sanity checks and duplicate detection for normalized invoice records."""

from __future__ import annotations

import datetime
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

GSTIN_PLACEHOLDERS = frozenset({"NA", "UNKNOWN", "EMPTY"})
GSTIN_STRICT_REGEX = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

TAX_MATH_TOLERANCE_PAISE = 500


@dataclass
class SanityCheck:
    name: str
    passed: bool
    detail: str
    severity: Literal["error", "warning", "info"]
    affected_records: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.affected_records) > 10:
            self.affected_records = self.affected_records[:10]


SanityIssue = SanityCheck


def normalize_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().upper()
    return str(value).strip().upper()


def parse_date_safe(value: Any) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if len(s) >= 10:
            s = s[:10]
        try:
            return datetime.date.fromisoformat(s)
        except ValueError:
            return None
    return None


def normalize_date_for_key(value: Any) -> str | None:
    d = parse_date_safe(value)
    return d.isoformat() if d is not None else None


def is_valid_gstin(value: Any) -> bool:
    s = normalize_string(value)
    if not s or s in GSTIN_PLACEHOLDERS:
        return False
    if len(s) != 15:
        return False
    return GSTIN_STRICT_REGEX.match(s) is not None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(round(value))
    if isinstance(value, str):
        t = value.strip()
        if not t:
            return None
        try:
            return int(round(float(t)))
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        t = value.strip()
        if not t:
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _paise_component(rec: dict, primary: str, *aliases: str) -> int:
    """Read a tax component in paise; prefer canonical ``*_paise`` keys, then short names (e.g. cgst, igst)."""
    for k in (primary, *aliases):
        v = _coerce_int(rec.get(k))
        if v is not None:
            return v
    return 0


def _total_tax_paise_resolved(rec: dict) -> int:
    """Prefer ``total_tax_paise`` when set; otherwise CGST + SGST + IGST (``*_paise`` or short keys)."""
    raw = rec.get("total_tax_paise")
    if raw is not None and not (isinstance(raw, str) and not str(raw).strip()):
        t = _coerce_int(raw)
        if t is not None:
            return t
    cg = _paise_component(rec, "cgst_paise", "cgst")
    sg = _paise_component(rec, "sgst_paise", "sgst")
    ig = _paise_component(rec, "igst_paise", "igst")
    return cg + sg + ig


def make_dedup_key_string(rec: dict) -> str:
    gstin = normalize_string(rec.get("gstin"))
    inv_src = rec.get("invoice_number_normalized") or rec.get("invoice_number")
    inv = normalize_string(inv_src)
    d = normalize_date_for_key(rec.get("invoice_date"))
    tax = _coerce_int(rec.get("taxable_amount_paise"))
    tax_part = str(tax) if tax is not None else "NULL"
    return "|".join((gstin, inv, d or "NULL", tax_part))


def _sample(records: list[dict], cap: int = 10) -> list[dict]:
    return [deepcopy(r) for r in records[:cap]]


def run_import_sanity(
    records: list[dict],
    expected_count: int,
    source_type: str,
) -> list[SanityCheck]:
    _ = source_type
    n = len(records)
    out: list[SanityCheck] = []

    # 1 — Row Count
    row_ok = n == expected_count
    out.append(
        SanityCheck(
            name="Row Count",
            passed=row_ok,
            detail=(
                f"Actual row count ({n}) equals expected ({expected_count})."
                if row_ok
                else f"Actual row count ({n}) does not equal expected ({expected_count})."
            ),
            severity="info" if row_ok else "error",
            affected_records=[],
        )
    )

    # 2 — GSTIN Validity
    bad_gstin: list[dict] = []
    for rec in records:
        if not is_valid_gstin(rec.get("gstin")):
            bad_gstin.append(rec)
    g_ok = len(bad_gstin) == 0
    out.append(
        SanityCheck(
            name="GSTIN Validity",
            passed=g_ok,
            detail=(
                "All records have valid normalized GSTIN."
                if g_ok
                else f"{len(bad_gstin)} record(s) have invalid GSTIN."
            ),
            severity="info" if g_ok else "error",
            affected_records=_sample(bad_gstin),
        )
    )

    # 3 — Tax Math (only when tax_rate is present: compare taxable × rate / 100 vs total tax)
    # Total tax = total_tax_paise if provided, else cgst + sgst + igst. No rate → skip row (not a failure).
    bad_tax: list[dict] = []
    for rec in records:
        tr = _coerce_float(rec.get("tax_rate"))
        if tr is None:
            continue
        taxable = _coerce_int(rec.get("taxable_amount_paise"))
        if taxable is None:
            continue
        total_tax = _total_tax_paise_resolved(rec)
        expected = taxable * tr / 100.0
        if abs(float(total_tax) - expected) > TAX_MATH_TOLERANCE_PAISE:
            bad_tax.append(rec)
    t_ok = len(bad_tax) == 0
    out.append(
        SanityCheck(
            name="Tax Math",
            passed=t_ok,
            detail=(
                "All rows with tax_rate set: total tax (total_tax_paise or CGST+SGST+IGST) matches "
                f"taxable × rate / 100 within ±{TAX_MATH_TOLERANCE_PAISE} paise; rows without tax_rate are not checked."
                if t_ok
                else f"{len(bad_tax)} record(s) have tax_rate set but total tax differs from taxable × rate / 100 "
                f"by more than ±{TAX_MATH_TOLERANCE_PAISE} paise (total from total_tax_paise or sum of CGST/SGST/IGST)."
            ),
            severity="info" if t_ok else "error",
            affected_records=_sample(bad_tax),
        )
    )

    # 4 — CGST/IGST Conflict
    bad_cg_ig: list[dict] = []
    for rec in records:
        cg = _paise_component(rec, "cgst_paise", "cgst")
        ig = _paise_component(rec, "igst_paise", "igst")
        if cg > 0 and ig > 0:
            bad_cg_ig.append(rec)
    ci_ok = len(bad_cg_ig) == 0
    out.append(
        SanityCheck(
            name="CGST/IGST Conflict",
            passed=ci_ok,
            detail=(
                "No record has both CGST and IGST positive."
                if ci_ok
                else f"{len(bad_cg_ig)} record(s) have both cgst > 0 and igst > 0."
            ),
            severity="info" if ci_ok else "error",
            affected_records=_sample(bad_cg_ig),
        )
    )

    # 5 — Future Date
    today = datetime.date.today()
    bad_dates: list[dict] = []
    for rec in records:
        d = parse_date_safe(rec.get("invoice_date"))
        if d is None:
            continue
        if d > today:
            bad_dates.append(rec)
    fd_ok = len(bad_dates) == 0
    out.append(
        SanityCheck(
            name="Future Date",
            passed=fd_ok,
            detail=(
                f"No invoice date is after today ({today.isoformat()})."
                if fd_ok
                else f"{len(bad_dates)} record(s) have invoice date after today."
            ),
            severity="info" if fd_ok else "error",
            affected_records=_sample(bad_dates),
        )
    )

    # 6 — Zero Amount
    zeros: list[dict] = []
    for rec in records:
        tx = _coerce_int(rec.get("taxable_amount_paise"))
        if tx == 0:
            zeros.append(rec)
    z_ok = len(zeros) == 0
    out.append(
        SanityCheck(
            name="Zero Amount",
            passed=z_ok,
            detail=(
                "No record has taxable_amount_paise = 0."
                if z_ok
                else f"{len(zeros)} record(s) have taxable_amount_paise = 0."
            ),
            severity="info" if z_ok else "warning",
            affected_records=_sample(zeros),
        )
    )

    # 7 — Negative Tax
    neg_tax_fields = ("total_tax_paise", "cgst_paise", "sgst_paise", "igst_paise")
    bad_neg: list[dict] = []
    for rec in records:
        for f in neg_tax_fields:
            v = _coerce_int(rec.get(f))
            if v is not None and v < 0:
                bad_neg.append(rec)
                break
    n_ok = len(bad_neg) == 0
    out.append(
        SanityCheck(
            name="Negative Tax",
            passed=n_ok,
            detail=(
                "No negative tax component amounts."
                if n_ok
                else f"{len(bad_neg)} record(s) have negative tax amount(s)."
            ),
            severity="info" if n_ok else "error",
            affected_records=_sample(bad_neg),
        )
    )

    return out


def detect_duplicates(
    records: list[dict],
    existing_records: list[dict] | None = None,
) -> dict[str, Any]:
    existing_records = existing_records or []

    def key_fn(r: dict) -> str:
        return make_dedup_key_string(r)

    existing_keys = {key_fn(r) for r in existing_records}
    seen_in_batch: set[str] = set()
    within_batch: list[dict] = []
    against_history: list[dict] = []
    clean_records: list[dict] = []

    for rec in records:
        k = key_fn(rec)
        copy = dict(rec)
        if k in existing_keys:
            against_history.append(copy)
        elif k in seen_in_batch:
            within_batch.append(copy)
        else:
            seen_in_batch.add(k)
            clean_records.append(copy)

    has_duplicates = bool(within_batch or against_history)
    return {
        "has_duplicates": has_duplicates,
        "within_batch": within_batch,
        "against_history": against_history,
        "clean_records": clean_records,
    }
