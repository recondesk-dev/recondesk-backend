"""Resilient recovery, sanitization, and content-based column inference for damaged/truncated files.

Handles:
- Embedded null bytes (\\x00) from corrupted exports
- Unclosed quotes and truncated trailing lines
- Jagged rows and mixed delimiters
- Headerless and corrupted-header sheets via heuristic column content inference
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

import pandas as pd

from app.services.normalizer import normalize_date

logger = logging.getLogger(__name__)

# Strict 15-character Indian GSTIN pattern
_GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def sanitize_csv_bytes(raw_bytes: bytes, encoding: str = "utf-8") -> tuple[str, list[str]]:
    """Sanitize raw CSV bytes to recover from null bytes, unclosed quotes, and jagged truncated lines.

    Returns:
        (clean_text, recovery_warnings)
    """
    warnings: list[str] = []

    # 1. Strip null bytes
    if b"\x00" in raw_bytes:
        raw_bytes = raw_bytes.replace(b"\x00", b"")
        warnings.append("Stripped corrupted null bytes (\\x00) from file.")

    # 2. Decode text safely
    try:
        text = raw_bytes.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        for enc in ("utf-8-sig", "latin-1", "cp1252"):
            try:
                text = raw_bytes.decode(enc)
                warnings.append(f"Decoded with fallback encoding: {enc}")
                break
            except Exception:
                continue
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
            warnings.append("Decoded with replacement characters for invalid bytes.")

    # 3. Normalize newline conventions
    text = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")

    lines = text.split("\n")
    if not lines:
        return "", warnings

    # 4. Check for unclosed quote on the final non-empty line (truncated file symptom)
    # A standard CSV must have an even number of double quotes across lines
    total_quotes = text.count('"')
    if total_quotes % 2 != 0:
        last_non_empty = -1
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].strip():
                last_non_empty = idx
                break
        if last_non_empty >= 0 and lines[last_non_empty].count('"') % 2 != 0:
            lines[last_non_empty] = lines[last_non_empty] + '"'
            warnings.append("Repaired unclosed quote on truncated final line.")
        else:
            text = text.rstrip() + '"\n'
            lines = text.split("\n")
            warnings.append("Repaired unmatched quote at end of stream.")

    # 5. Handle trailing truncated line with fewer delimiters than the header/data average
    if len(lines) >= 2:
        # Determine dominant delimiter
        sample = "\n".join(lines[:min(10, len(lines))])
        counts = {",": sample.count(","), ";": sample.count(";"), "\t": sample.count("\t"), "|": sample.count("|")}
        delim = max(counts, key=counts.get) if any(counts.values()) else ","

        header_delim_count = lines[0].count(delim)
        last_non_empty = -1
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].strip():
                last_non_empty = idx
                break

        if last_non_empty > 0 and header_delim_count > 0:
            last_line = lines[last_non_empty]
            last_delim_count = last_line.count(delim)
            # If last line has significantly fewer delimiters, it was cut off mid-download
            if last_delim_count < (header_delim_count // 2):
                dropped = lines.pop(last_non_empty)
                warnings.append(f"Discarded truncated partial trailing line: '{dropped[:40]}...'")

    clean_text = "\n".join(lines)
    return clean_text, warnings


def _is_probable_gstin(val: str) -> bool:
    if not val or len(val) != 15:
        return False
    return bool(_GSTIN_REGEX.match(val.upper()))


def _is_probable_date(val: str) -> bool:
    if not val or len(val) < 6:
        return False
    # Avoid classifying pure amounts (e.g. 50000 or 1000.50) as dates
    if re.fullmatch(r"\d+(?:\.\d+)?", val) and len(val) != 8:
        return False
    try:
        res = normalize_date(val)
        y = res.value.year
        return 2000 <= y <= 2035
    except Exception:
        return False


def _is_probable_amount(val: str) -> bool:
    if not val:
        return False
    s = val.strip().replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    # Check for negative / parentheses
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1].strip()
    try:
        f = float(s)
        # Avoid 15-digit GSTIN or telephone numbers being classified as invoice amounts
        return not (len(s) >= 10 and "." not in s)
    except ValueError:
        return False


def _parse_amount_val(val: str) -> float | None:
    if not val:
        return None
    s = val.strip().replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1].strip()
    try:
        return float(s)
    except ValueError:
        return None


def infer_columns_by_content(
    df: pd.DataFrame,
    client_gstin: str | None = None,
    mode: str = "purchase",
    max_scan_rows: int = 50,
) -> tuple[dict[str, str], int]:
    """Infer column mappings from cell content patterns when headers are damaged or missing.

    Returns:
        (mapping, data_start_row)
        where mapping maps standard names (gstin, invoice_number, invoice_date, etc.)
        to df.columns labels, and data_start_row is 0 (if row 0 was data) or >0.
    """
    if df is None or df.empty or len(df.columns) < 2:
        return {}, 0

    scan_df = df.iloc[:max_scan_rows].copy()
    num_rows = len(scan_df)
    if num_rows == 0:
        return {}, 0

    # 1. Determine data_start_row by finding the first row with GSTIN, Date, or Date+Amount
    data_start_row = 0
    for r_idx in range(min(15, len(df))):
        vals = [str(x).strip() for x in df.iloc[r_idx].tolist() if pd.notna(x) and str(x).strip()]
        has_gstin = any(_is_probable_gstin(v) for v in vals)
        has_date = any(_is_probable_date(v) for v in vals)
        has_amount = any(_is_probable_amount(v) for v in vals)
        if has_gstin or (has_date and has_amount):
            data_start_row = r_idx
            break
        # If row 0 looks like header text, data likely starts at row 1
        if r_idx == 0 and not (has_gstin or has_date or has_amount):
            data_start_row = 1

    eval_df = scan_df.iloc[data_start_row:] if data_start_row < len(scan_df) else scan_df
    effective_rows = len(eval_df)
    if effective_rows == 0:
        return {}, 0

    col_scores: dict[str, dict[str, float]] = {}
    col_samples: dict[str, list[str]] = {}

    norm_client = client_gstin.strip().upper() if client_gstin else None

    for col in eval_df.columns:
        series = eval_df[col].dropna().astype(str).str.strip()
        vals = [v for v in series if v and v.upper() not in ("NAN", "NONE", "NAT", "NULL")]
        col_samples[col] = vals
        if not vals:
            continue

        n = len(vals)
        gstin_count = sum(1 for v in vals if _is_probable_gstin(v))
        date_count = sum(1 for v in vals if _is_probable_date(v))
        amount_count = sum(1 for v in vals if _is_probable_amount(v))

        # Check unique ratio (invoice numbers are mostly unique)
        unique_ratio = len(set(vals)) / n if n > 0 else 0.0

        col_scores[col] = {
            "gstin_ratio": gstin_count / n,
            "date_ratio": date_count / n,
            "amount_ratio": amount_count / n,
            "unique_ratio": unique_ratio,
            "sample_len_avg": sum(len(v) for v in vals) / n,
        }

    mapping: dict[str, str] = {}
    assigned_cols: set[str] = set()

    # --- Match GSTIN ---
    best_gstin_col = None
    best_gstin_score = 0.0
    for col, sc in col_scores.items():
        if sc["gstin_ratio"] >= 0.3 and sc["gstin_ratio"] > best_gstin_score:
            # Check if this column is solely client's own GSTIN
            vals = col_samples.get(col, [])
            if norm_client and len(set(vals)) == 1 and norm_client in vals:
                continue
            best_gstin_score = sc["gstin_ratio"]
            best_gstin_col = col

    if best_gstin_col is not None:
        mapping["gstin"] = str(best_gstin_col)
        assigned_cols.add(best_gstin_col)

    # --- Match Date ---
    best_date_col = None
    best_date_score = 0.0
    for col, sc in col_scores.items():
        if col in assigned_cols:
            continue
        if sc["date_ratio"] >= 0.35 and sc["date_ratio"] > best_date_score:
            best_date_score = sc["date_ratio"]
            best_date_col = col

    if best_date_col is not None:
        mapping["invoice_date"] = str(best_date_col)
        assigned_cols.add(best_date_col)

    # --- Match Amounts ---
    amount_cols: list[tuple[str, float]] = []
    for col, sc in col_scores.items():
        if col in assigned_cols:
            continue
        if sc["amount_ratio"] >= 0.6:
            # Compute average absolute amount
            vals = col_samples.get(col, [])
            parsed = [_parse_amount_val(v) for v in vals]
            clean_parsed = [abs(p) for p in parsed if p is not None]
            avg_val = (sum(clean_parsed) / len(clean_parsed)) if clean_parsed else 0.0
            amount_cols.append((col, avg_val))

    # Sort amount columns by magnitude (descending)
    amount_cols.sort(key=lambda x: x[1], reverse=True)

    if len(amount_cols) == 1:
        mapping["taxable_amount"] = str(amount_cols[0][0])
        assigned_cols.add(amount_cols[0][0])
    elif len(amount_cols) == 2:
        # Larger is total_amount, smaller is taxable_amount
        mapping["total_amount"] = str(amount_cols[0][0])
        mapping["taxable_amount"] = str(amount_cols[1][0])
        assigned_cols.add(amount_cols[0][0])
        assigned_cols.add(amount_cols[1][0])
    elif len(amount_cols) >= 3:
        # Look for equal tax columns (CGST == SGST)
        # Check pairwise equality between amount columns
        cgst_col = None
        sgst_col = None
        for i in range(len(amount_cols)):
            for j in range(i + 1, len(amount_cols)):
                c1, _ = amount_cols[i]
                c2, _ = amount_cols[j]
                v1s = eval_df[c1].map(_parse_amount_val)
                v2s = eval_df[c2].map(_parse_amount_val)
                matches = sum(1 for a, b in zip(v1s, v2s) if a is not None and b is not None and a > 0 and abs(a - b) < 0.01)
                if matches >= 2:
                    cgst_col = c1
                    sgst_col = c2
                    break
            if cgst_col:
                break

        if cgst_col and sgst_col:
            mapping["cgst"] = str(cgst_col)
            mapping["sgst"] = str(sgst_col)
            assigned_cols.add(cgst_col)
            assigned_cols.add(sgst_col)
            rem_amounts = [c for c, _ in amount_cols if c not in assigned_cols]
            if len(rem_amounts) >= 2:
                mapping["total_amount"] = str(rem_amounts[0])
                mapping["taxable_amount"] = str(rem_amounts[1])
                assigned_cols.add(rem_amounts[0])
                assigned_cols.add(rem_amounts[1])
            elif len(rem_amounts) == 1:
                mapping["taxable_amount"] = str(rem_amounts[0])
                assigned_cols.add(rem_amounts[0])
        else:
            mapping["total_amount"] = str(amount_cols[0][0])
            mapping["taxable_amount"] = str(amount_cols[1][0])
            assigned_cols.add(amount_cols[0][0])
            assigned_cols.add(amount_cols[1][0])
            if len(amount_cols) >= 3:
                mapping["igst"] = str(amount_cols[2][0])
                assigned_cols.add(amount_cols[2][0])

    # --- Match Invoice Number ---
    # Needs high uniqueness ratio, not pure long text, not already assigned
    best_inv_col = None
    best_inv_score = -1.0
    for col, sc in col_scores.items():
        if col in assigned_cols:
            continue
        # Avoid columns with very long text (likely party name or address)
        if sc["sample_len_avg"] > 35:
            continue
        # Favor columns with good uniqueness and moderate length (3-20 chars)
        score = sc["unique_ratio"] * (10.0 if 3 <= sc["sample_len_avg"] <= 20 else 5.0)
        if score > best_inv_score:
            best_inv_score = score
            best_inv_col = col

    if best_inv_col is not None:
        mapping["invoice_number"] = str(best_inv_col)
        assigned_cols.add(best_inv_col)

    # --- Match Supplier / Recipient Name ---
    # Any remaining column with longer text (average length >= 4)
    party_field = "recipient_name" if mode == "sales" else "supplier_name"
    for col, sc in col_scores.items():
        if col in assigned_cols:
            continue
        if sc["sample_len_avg"] >= 4 and sc["amount_ratio"] < 0.2:
            mapping[party_field] = str(col)
            assigned_cols.add(col)
            break

    return mapping, data_start_row
