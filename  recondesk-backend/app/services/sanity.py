"""Import sanity checks and duplicate detection for normalized invoice records."""

from __future__ import annotations

import datetime
import math
import re
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

GSTIN_PLACEHOLDERS = frozenset({"NA", "UNKNOWN", "EMPTY"})
GSTIN_STRICT_REGEX = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
ALLOWED_TAX_RATES = frozenset({0, 0.1, 0.25, 1.5, 3, 5, 12, 18, 28})
GST_SLABS_FOR_INFERENCE = sorted(ALLOWED_TAX_RATES)
OUTLIER_TAXABLE_PAISE = 1_000_000_000


@dataclass(frozen=True)
class SanityCheck:
    name: str
    passed: bool
    detail: str
    severity: Literal["error", "warning", "info"]
    affected_count: int
    affected_records: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.affected_records) > 10:
            object.__setattr__(self, "affected_records", self.affected_records[:10])


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


def _is_allowed_tax_rate(trf: float) -> bool:
    return any(math.isclose(trf, float(a), rel_tol=0, abs_tol=1e-9) for a in ALLOWED_TAX_RATES)


def _nearest_slab(rate: float) -> float:
    return min(GST_SLABS_FOR_INFERENCE, key=lambda x: abs(x - rate))


def _tax_tolerance_int(taxable: int) -> int:
    return max(50, int(0.01 * abs(taxable)))


def _tax_tolerance_paise(taxable: int) -> float:
    """Alias for tests / callers expecting float paise tolerance."""
    return float(_tax_tolerance_int(taxable))


def _percentile_90(values: list[int]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    k = int(math.ceil(0.90 * n)) - 1
    idx = max(0, min(n - 1, k))
    return float(s[idx])


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
            return float(t)
        except ValueError:
            return None
    return None


def _record_copy_with_extra(rec: dict, **extra: Any) -> dict:
    out = dict(rec)
    out.update(extra)
    return out


def _make_check(
    name: str,
    passed: bool,
    detail: str,
    severity: Literal["error", "warning", "info"],
    samples: list[dict],
    affected_count: int,
) -> SanityCheck:
    bounded = [deepcopy(r) for r in samples[:10]]
    return SanityCheck(
        name=name,
        passed=passed,
        detail=detail,
        severity=severity,
        affected_count=affected_count,
        affected_records=bounded,
    )


def _amount_fingerprint(rec: dict) -> tuple[int | None, int | None]:
    return (
        _coerce_int(rec.get("taxable_amount_paise")),
        _coerce_int(rec.get("total_tax_paise")),
    )


def make_dedup_key_string(rec: dict) -> str:
    gstin = normalize_string(rec.get("gstin"))
    inv = normalize_string(rec.get("invoice_number_normalized") or rec.get("invoice_number"))
    inv_date = normalize_date_for_key(rec.get("invoice_date"))
    doc = normalize_string(rec.get("document_type"))
    return "|".join((gstin, inv, inv_date or "NULL", doc))


def run_import_sanity(
    records: list[dict],
    expected_count: int | None,
    source_type: str,
    existing_records: list[dict] | None = None,
) -> list[SanityCheck]:
    _ = source_type
    n = len(records)
    out: list[SanityCheck] = []

    if expected_count is None:
        out.append(
            _make_check(
                "Row Count",
                True,
                f"No expected row count provided; actual={n}.",
                "info",
                [],
                0,
            )
        )
    else:
        diff = abs(n - expected_count)
        pct_ok = expected_count > 0 and (diff / expected_count) <= 0.02
        if diff == 0:
            out.append(
                _make_check(
                    "Row Count",
                    True,
                    f"Row count matches: expected={expected_count}, actual={n}, diff={diff}.",
                    "info",
                    [],
                    0,
                )
            )
        elif diff <= 2 and pct_ok:
            out.append(
                _make_check(
                    "Row Count",
                    False,
                    f"Row count minor mismatch: expected={expected_count}, actual={n}, "
                    f"diff={diff}, relative={diff / expected_count:.6f}.",
                    "warning",
                    [],
                    0,
                )
            )
        else:
            out.append(
                _make_check(
                    "Row Count",
                    False,
                    f"Row count mismatch: expected={expected_count}, actual={n}, diff={diff}.",
                    "error",
                    [],
                    0,
                )
            )

    required = ("gstin", "invoice_number_normalized", "invoice_date", "taxable_amount_paise")
    missing_samples: list[dict] = []
    missing_count = 0
    for rec in records:
        miss: list[str] = []
        for f in required:
            v = rec.get(f)
            if v is None:
                miss.append(f)
            elif isinstance(v, str) and not v.strip():
                miss.append(f)
            elif f == "taxable_amount_paise" and v is not None:
                if _coerce_int(v) is None:
                    miss.append(f)
        if miss:
            missing_count += 1
            if len(missing_samples) < 10:
                missing_samples.append(
                    _record_copy_with_extra(dict(rec), _missing_fields=sorted(miss))
                )
    out.append(
        _make_check(
            "Mandatory Fields",
            missing_count == 0,
            f"Missing mandatory fields on {missing_count} record(s).",
            "error" if missing_count else "info",
            missing_samples,
            missing_count,
        )
    )

    bad_gstin: list[dict] = []
    bad_gstin_count = 0
    for rec in records:
        if not is_valid_gstin(rec.get("gstin")):
            bad_gstin_count += 1
            if len(bad_gstin) < 10:
                bad_gstin.append(dict(rec))
    out.append(
        _make_check(
            "GSTIN Validity",
            bad_gstin_count == 0,
            f"Invalid GSTIN structure or placeholder on {bad_gstin_count} record(s).",
            "error" if bad_gstin_count else "info",
            bad_gstin,
            bad_gstin_count,
        )
    )

    inv_issues: list[dict] = []
    inv_indices: set[int] = set()
    for i, rec in enumerate(records):
        raw_inv = rec.get("invoice_number")
        norm = rec.get("invoice_number_normalized")
        norm_s = normalize_string(norm) if norm is not None else ""
        if raw_inv is not None and str(raw_inv).strip() != str(raw_inv):
            inv_indices.add(i)
            continue
        if raw_inv is not None and normalize_string(raw_inv) != norm_s:
            inv_indices.add(i)

    by_gstin: dict[str, dict[str, set[str]]] = {}
    indices_by_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        g = normalize_string(rec.get("gstin"))
        invn = normalize_string(rec.get("invoice_number_normalized"))
        if g and invn:
            by_gstin.setdefault(g, {}).setdefault(invn, set()).add(
                normalize_string(rec.get("invoice_number", rec.get("invoice_number_normalized", "")))
            )
            indices_by_pair[(g, invn)].append(i)
    for g, invmap in by_gstin.items():
        for invn, variants in invmap.items():
            if len(variants) <= 1:
                continue
            for j in indices_by_pair.get((g, invn), []):
                inv_indices.add(j)
    for i in sorted(inv_indices):
        if len(inv_issues) < 10:
            inv_issues.append(dict(records[i]))
    inv_count = len(inv_indices)
    out.append(
        _make_check(
            "Invoice Number Consistency",
            inv_count == 0,
            f"Invoice number spacing/casing inconsistencies on {inv_count} indicator(s).",
            "warning" if inv_count else "info",
            inv_issues,
            inv_count,
        )
    )

    tax_samples: list[dict] = []
    tax_record_indices: set[int] = set()
    tax_sev: Literal["error", "warning", "info"] = "info"

    for ri, rec in enumerate(records):
        taxable = _coerce_int(rec.get("taxable_amount_paise"))
        total_tax = _coerce_int(rec.get("total_tax_paise"))
        cgst = _coerce_int(rec.get("cgst_paise")) or 0
        sgst = _coerce_int(rec.get("sgst_paise")) or 0
        igst = _coerce_int(rec.get("igst_paise")) or 0
        if taxable is None or total_tax is None:
            continue

        tol = _tax_tolerance_int(taxable)
        tr_f = _coerce_float(rec.get("tax_rate")) if rec.get("tax_rate") is not None else None

        row_error = False
        row_warn = False

        # Rate-based: compare total_tax vs expected from rate
        if tr_f is not None:
            expected_tax = taxable * tr_f / 100.0
            diff_a = abs(total_tax - expected_tax)
            if diff_a > 0:
                if diff_a > tol:
                    row_error = True
                else:
                    row_warn = True

        # Inferred slab fallback when tax_rate absent
        if tr_f is None and taxable != 0:
            infer_rate = (total_tax / taxable) * 100.0
            nearest = _nearest_slab(infer_rate)
            expected_tax_b = taxable * nearest / 100.0
            diff_b = abs(total_tax - expected_tax_b)
            if diff_b > 0:
                if diff_b > tol:
                    row_error = True
                else:
                    row_warn = True

        # Component check: total_tax vs cgst + sgst + igst
        comp_sum = cgst + sgst + igst
        diff_c = abs(total_tax - comp_sum)
        if diff_c > 0:
            if diff_c > tol:
                row_error = True
            else:
                row_warn = True

        if row_error or row_warn:
            tax_record_indices.add(ri)
            if row_error:
                tax_sev = "error"
            elif tax_sev != "error":
                tax_sev = "warning"
            if len(tax_samples) < 10:
                tax_samples.append(dict(rec))

    tax_issues = len(tax_record_indices)
    out.append(
        _make_check(
            "Tax Math",
            tax_issues == 0,
            f"Tax math issues on {tax_issues} record(s); tolerance=max(50,1%×taxable) per row.",
            tax_sev if tax_issues else "info",
            tax_samples,
            tax_issues,
        )
    )

    struct_samples: list[dict] = []
    struct_count = 0
    for rec in records:
        cgst = _coerce_int(rec.get("cgst_paise")) or 0
        sgst = _coerce_int(rec.get("sgst_paise")) or 0
        igst = _coerce_int(rec.get("igst_paise")) or 0
        ok_igst = igst > 0 and cgst == 0 and sgst == 0
        ok_cgst_sgst = cgst > 0 and sgst > 0 and igst == 0
        if ok_igst or ok_cgst_sgst:
            continue
        bad = (igst > 0 and (cgst > 0 or sgst > 0)) or ((cgst > 0) ^ (sgst > 0))
        if bad:
            struct_count += 1
            if len(struct_samples) < 10:
                struct_samples.append(dict(rec))
    out.append(
        _make_check(
            "Tax Structure",
            struct_count == 0,
            f"Invalid CGST/SGST/IGST combination on {struct_count} record(s).",
            "error" if struct_count else "info",
            struct_samples,
            struct_count,
        )
    )

    date_samples: list[dict] = []
    date_err = 0
    date_warn = 0
    today = datetime.date.today()
    ten_years = datetime.timedelta(days=10 * 365)
    for rec in records:
        d = parse_date_safe(rec.get("invoice_date"))
        if d is None:
            date_err += 1
            if len(date_samples) < 10:
                date_samples.append(dict(rec))
            continue
        if d > today:
            date_err += 1
            if len(date_samples) < 10:
                date_samples.append(dict(rec))
            continue
        if d < today - ten_years:
            date_warn += 1
            if len(date_samples) < 10:
                date_samples.append(dict(rec))
    date_total = date_err + date_warn
    date_sev: Literal["error", "warning", "info"] = (
        "error" if date_err else ("warning" if date_warn else "info")
    )
    out.append(
        _make_check(
            "Date Validity",
            date_total == 0,
            f"Date issues: invalid/future={date_err}, older_than_10_years={date_warn}.",
            date_sev,
            date_samples,
            date_total,
        )
    )

    zero_samples: list[dict] = []
    zero_warn_count = 0
    zero_info_only = 0
    for rec in records:
        taxable = _coerce_int(rec.get("taxable_amount_paise"))
        if taxable != 0:
            continue
        doc = normalize_string(rec.get("document_type"))
        if doc == "CREDIT_NOTE":
            zero_info_only += 1
            continue
        zero_warn_count += 1
        if len(zero_samples) < 10:
            zero_samples.append(dict(rec))
    zero_sev: Literal["error", "warning", "info"] = (
        "warning" if zero_warn_count else ("info" if zero_info_only else "info")
    )
    out.append(
        _make_check(
            "Zero Taxable",
            zero_warn_count == 0,
            f"Zero taxable: non-credit-note={zero_warn_count}, credit_note={zero_info_only}.",
            zero_sev,
            zero_samples,
            zero_warn_count,
        )
    )

    neg_samples: list[dict] = []
    neg_count = 0
    money_fields = (
        "taxable_amount_paise",
        "total_tax_paise",
        "cgst_paise",
        "sgst_paise",
        "igst_paise",
    )
    for rec in records:
        doc = normalize_string(rec.get("document_type"))
        allowed_neg = doc in ("CREDIT_NOTE", "DEBIT_NOTE")
        bad = False
        for mf in money_fields:
            v = _coerce_int(rec.get(mf))
            if v is not None and v < 0 and not allowed_neg:
                bad = True
                break
        if bad:
            neg_count += 1
            if len(neg_samples) < 10:
                neg_samples.append(dict(rec))
    out.append(
        _make_check(
            "Negative Values",
            neg_count == 0,
            f"Negative amounts on {neg_count} record(s) where not allowed.",
            "error" if neg_count else "info",
            neg_samples,
            neg_count,
        )
    )

    rate_samples: list[dict] = []
    rate_count = 0
    for rec in records:
        if rec.get("tax_rate") is None:
            continue
        trf = _coerce_float(rec.get("tax_rate"))
        if trf is None:
            continue
        if not _is_allowed_tax_rate(trf):
            rate_count += 1
            if len(rate_samples) < 10:
                rate_samples.append(dict(rec))
    out.append(
        _make_check(
            "Tax Rate",
            rate_count == 0,
            f"Tax rate outside common GST slabs on {rate_count} record(s).",
            "warning" if rate_count else "info",
            rate_samples,
            rate_count,
        )
    )

    outlier_samples: list[dict] = []
    outlier_count = 0
    for rec in records:
        taxable = _coerce_int(rec.get("taxable_amount_paise"))
        if taxable is not None and taxable > OUTLIER_TAXABLE_PAISE:
            outlier_count += 1
            if len(outlier_samples) < 10:
                outlier_samples.append(dict(rec))
    out.append(
        _make_check(
            "Outliers",
            outlier_count == 0,
            f"Taxable amount exceeds ₹10 crore threshold on {outlier_count} record(s).",
            "warning" if outlier_count else "info",
            outlier_samples,
            outlier_count,
        )
    )

    dup_result = detect_duplicates(records, existing_records=existing_records)
    if dup_result["has_duplicates"]:
        wb = dup_result["counts"]["within_batch"]
        ah = dup_result["counts"]["against_history"]
        aff = wb + ah
        pool = dup_result["within_batch"] + dup_result["against_history"]
        samp = [deepcopy(r) for r in pool[:10]]
        out.append(
            _make_check(
                "Duplicate Indicators",
                False,
                f"Duplicates: within_batch={wb}, against_history={ah}.",
                "error",
                samp,
                aff,
            )
        )
    else:
        out.append(
            _make_check(
                "Duplicate Indicators",
                True,
                "No duplicate rows (within batch or vs history).",
                "info",
                [],
                0,
            )
        )

    tax_vals = [t for t in (_coerce_int(r.get("taxable_amount_paise")) for r in records) if t is not None]
    p90 = _percentile_90(tax_vals)
    currency_fail = n > 20 and p90 < 100.0
    out.append(
        _make_check(
            "Unit Consistency",
            not currency_fail,
            f"p90(taxable_amount_paise)={p90:.2f}, n={n}. Error if n>20 and p90<100.",
            "error" if currency_fail else "info",
            [],
            n if currency_fail else 0,
        )
    )

    return out


def detect_duplicates(
    records: list[dict],
    existing_records: list[dict] | None = None,
) -> dict[str, Any]:
    existing_records = existing_records or []

    def sk(r: dict) -> str:
        return make_dedup_key_string(r)

    def fp(r: dict) -> tuple[int | None, int | None]:
        return _amount_fingerprint(r)

    n_batch = len(records)
    batch_sks: list[str] = [sk(r) for r in records]
    batch_fps: list[tuple[int | None, int | None]] = [fp(r) for r in records]

    hist_fps: dict[str, set[tuple[int | None, int | None]]] = defaultdict(set)
    for er in existing_records:
        k = sk(er)
        hist_fps[k].add(fp(er))

    fps_per_sk: dict[str, set[tuple[int | None, int | None]]] = defaultdict(set)
    for i in range(n_batch):
        fps_per_sk[batch_sks[i]].add(batch_fps[i])

    batch_conflict_sk = {s for s, sfp in fps_per_sk.items() if len(sfp) > 1}

    first_idx: dict[tuple[str, tuple[int | None, int | None]], int] = {}
    for i in range(n_batch):
        kp = (batch_sks[i], batch_fps[i])
        if kp not in first_idx:
            first_idx[kp] = i

    within_batch: list[dict] = []
    against_history: list[dict] = []
    conflicts: list[dict] = []
    clean_records: list[dict] = []
    duplicate_keys: dict[str, int] = {}
    conflict_keys: dict[str, int] = {}

    def _conflict_copy(rec: dict) -> dict:
        x = deepcopy(rec)
        x["_conflict_kind"] = "invoice_conflict"
        return x

    for i, rec in enumerate(records):
        k = batch_sks[i]
        fpi = batch_fps[i]
        kp = (k, fpi)

        if k in batch_conflict_sk:
            conflicts.append(_conflict_copy(rec))
            conflict_keys[k] = conflict_keys.get(k, 0) + 1
            continue

        hset = hist_fps.get(k)
        if hset is not None and len(hset) > 0 and fpi not in hset:
            conflicts.append(_conflict_copy(rec))
            conflict_keys[k] = conflict_keys.get(k, 0) + 1
            continue

        dup_after_first = i > first_idx[kp]

        if hset is not None and len(hset) > 0 and fpi in hset:
            against_history.append(deepcopy(rec))
            if dup_after_first:
                within_batch.append(deepcopy(rec))
            continue

        if dup_after_first:
            within_batch.append(deepcopy(rec))
        else:
            clean_records.append(deepcopy(rec))

    count_sk_fp: dict[tuple[str, tuple[int | None, int | None]], int] = defaultdict(int)
    for i in range(n_batch):
        count_sk_fp[(batch_sks[i], batch_fps[i])] += 1

    for k in set(batch_sks):
        if k in batch_conflict_sk:
            continue
        tot = 0
        for fpi in fps_per_sk[k]:
            c = count_sk_fp[(k, fpi)]
            if c > 1:
                tot += c
        if tot:
            duplicate_keys[k] = tot

    has_conflicts = bool(conflicts)
    has_duplicates = bool(within_batch) or bool(against_history)

    return {
        "has_duplicates": has_duplicates,
        "has_conflicts": has_conflicts,
        "counts": {
            "within_batch": len(within_batch),
            "against_history": len(against_history),
            "clean": len(clean_records),
            "conflicts": len(conflicts),
        },
        "within_batch": within_batch,
        "against_history": against_history,
        "conflicts": conflicts,
        "clean_records": clean_records,
        "duplicate_keys": duplicate_keys,
        "conflict_keys": conflict_keys,
    }
