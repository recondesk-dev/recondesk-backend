"""E-Invoice Report parser — parses .xlsx / .xls / .csv IRP e-invoice exports
into a normalized DataFrame.

Supported columns:
- Invoice No
- Invoice Date
- IRN
- Ack No
- Ack Date
- IRN Status (Active/Cancelled)
- Total Value
- GSTIN
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

import pandas as pd

from app.services.matcher import normalize_invoice
from app.services.normalizer import (
    NormalizationError,
    normalize_amount,
    normalize_date,
    normalize_gstin,
)

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """Raised when an e-invoice report file cannot be parsed."""


# Column aliases for flexible header matching on IRP / GST Portal e-invoice exports
EINVOICE_COLUMN_ALIASES: dict[str, list[str]] = {
    "invoice_number": [
        "invoice no",
        "invoice number",
        "inv no",
        "inv. no.",
        "inv no.",
        "inv number",
        "doc no",
        "doc no.",
        "doc number",
        "document no",
        "document number",
        "bill no",
        "bill no.",
    ],
    "invoice_date": [
        "invoice date",
        "inv date",
        "inv. date",
        "doc date",
        "doc. date",
        "irn date",
        "irn. date",
        "ack date",
        "bill date",
    ],
    "irn": [
        "irn",
        "irn no",
        "irn number",
        "invoice reference number",
        "hash",
        "irn hash",
    ],
    "ack_number": [
        "ack no",
        "ack no.",
        "ack number",
        "acknowledgement no",
        "acknowledgement number",
        "ack_no",
    ],
    "ack_date": [
        "ack date",
        "ack. date",
        "acknowledgement date",
        "ack_date",
    ],
    "irn_status": [
        "irn status",
        "status",
        "cancel status",
        "e-invoice status",
        "einvoice status",
    ],
    "total_value": [
        "total value",
        "total amount",
        "invoice value",
        "invoice amount",
        "grand total",
        "value",
        "tot val",
        "totval",
    ],
    "gstin": [
        "gstin",
        "supplier gstin",
        "buyer gstin",
        "recipient gstin",
        "party gstin",
        "gstin/uin",
        "gstin / uin",
        "gst reg no",
    ],
}


def _clean_header_str(col: Any) -> str:
    """Normalize raw header string for alias matching."""
    s = str(col).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def map_einvoice_columns(df_cols: list[Any]) -> dict[str, str]:
    """Map DataFrame column headers to canonical e-invoice field names.
    Returns dict mapping canonical_name -> original_column_name.
    """
    mapped: dict[str, str] = {}
    normalized_cols = {idx: _clean_header_str(col) for idx, col in enumerate(df_cols)}

    for canonical, aliases in EINVOICE_COLUMN_ALIASES.items():
        found = False
        # Direct match check first
        for idx, norm_col in normalized_cols.items():
            if norm_col in aliases or norm_col == canonical:
                mapped[canonical] = str(df_cols[idx])
                found = True
                break
        if found:
            continue

        # Substring / partial match check fallback
        for idx, norm_col in normalized_cols.items():
            for alias in aliases:
                if alias in norm_col or norm_col in alias:
                    mapped[canonical] = str(df_cols[idx])
                    found = True
                    break
            if found:
                break

    return mapped


def parse_einvoice_report(
    content: bytes,
    filename: str,
) -> pd.DataFrame:
    """Parse Excel or CSV e-invoice export file into a normalized DataFrame.

    Canonical output columns:
    - invoice_number (raw string)
    - invoice_number_normalized (normalized via shared matcher logic)
    - invoice_date (datetime.date or None)
    - irn (str or "")
    - ack_number (str or "")
    - ack_date (datetime.date or None)
    - irn_status ("Active" | "Cancelled")
    - value_paise (int, amount in paise)
    - total_value (float, amount in rupees)
    - gstin (normalized GSTIN or "")
    """
    fn_lower = filename.lower()
    df_raw: pd.DataFrame | None = None

    if fn_lower.endswith(".csv"):
        # Try standard encodings for CSV
        for enc in ("utf-8-sig", "utf-8", "latin1", "cp1252"):
            try:
                df_raw = pd.read_csv(io.BytesIO(content), encoding=enc, dtype=str)
                break
            except Exception:
                continue
    elif fn_lower.endswith((".xlsx", ".xls")):
        try:
            excel_file = pd.ExcelFile(io.BytesIO(content))
            sheet_name = excel_file.sheet_names[0]
            df_raw = pd.read_excel(excel_file, sheet_name=sheet_name, dtype=str)
        except Exception as e:
            raise ParseError(f"Failed to read Excel file: {e}") from e

    if df_raw is None or df_raw.empty:
        raise ParseError("File is empty or could not be parsed into a DataFrame.")

    # Find row with header if file has top metadata rows
    headers_col_map: dict[str, str] = {}
    best_row_idx = 0
    max_mapped_count = 0

    # Search top 15 rows for best column match
    for row_idx in range(min(15, len(df_raw))):
        row_values = df_raw.iloc[row_idx].values if row_idx > 0 else df_raw.columns.values
        col_map = map_einvoice_columns(list(row_values))
        if len(col_map) > max_mapped_count:
            max_mapped_count = len(col_map)
            best_row_idx = row_idx
            headers_col_map = col_map

    if max_mapped_count < 2:
        raise ParseError("Required e-invoice columns (Invoice No, IRN, Date, Value, GSTIN) could not be identified.")

    if best_row_idx > 0:
        # Re-read DataFrame using best_row_idx as header
        new_cols = list(df_raw.iloc[best_row_idx].values)
        df_raw = df_raw.iloc[best_row_idx + 1 :].copy()
        df_raw.columns = new_cols

    col_map = map_einvoice_columns(list(df_raw.columns))

    records: list[dict[str, Any]] = []

    for _, row in df_raw.iterrows():
        # Invoice number
        raw_inv = str(row.get(col_map.get("invoice_number", ""), "") or "").strip()
        if not raw_inv or raw_inv.lower() in ("nan", "none", "total", "grand total"):
            continue
        inv_norm = normalize_invoice(raw_inv)
        if not inv_norm:
            continue

        # Invoice date
        raw_date = row.get(col_map.get("invoice_date", ""), "")
        inv_date = None
        if raw_date and str(raw_date).strip().lower() not in ("nan", "none", ""):
            try:
                norm_d_res = normalize_date(raw_date)
                inv_date = norm_d_res.value
            except NormalizationError:
                inv_date = None

        # GSTIN
        raw_gstin = str(row.get(col_map.get("gstin", ""), "") or "").strip()
        gstin_norm = ""
        if raw_gstin and raw_gstin.lower() not in ("nan", "none"):
            try:
                gstin_norm = normalize_gstin(raw_gstin)
            except NormalizationError:
                # Store cleaned alphanumeric string if checksum fails
                gstin_norm = re.sub(r"[^A-Z0-9]", "", raw_gstin.upper())

        # IRN
        irn = str(row.get(col_map.get("irn", ""), "") or "").strip()
        if irn.lower() in ("nan", "none"):
            irn = ""

        # Ack No & Date
        ack_no = str(row.get(col_map.get("ack_number", ""), "") or "").strip()
        if ack_no.lower() in ("nan", "none"):
            ack_no = ""

        raw_ack_date = row.get(col_map.get("ack_date", ""), "")
        ack_date = None
        if raw_ack_date and str(raw_ack_date).strip().lower() not in ("nan", "none", ""):
            try:
                ack_d_res = normalize_date(raw_ack_date)
                ack_date = ack_d_res.value
            except NormalizationError:
                ack_date = None

        # IRN Status
        raw_status = str(row.get(col_map.get("irn_status", ""), "") or "").strip().lower()
        if "cancel" in raw_status:
            irn_status = "Cancelled"
        else:
            irn_status = "Active"

        # Total Value
        raw_val = row.get(col_map.get("total_value", ""), 0)
        val_paise = 0
        if raw_val and str(raw_val).strip().lower() not in ("nan", "none", ""):
            try:
                val_res = normalize_amount(raw_val)
                val_paise = val_res.value
            except NormalizationError:
                val_paise = 0

        records.append(
            {
                "invoice_number": raw_inv,
                "invoice_number_normalized": inv_norm,
                "invoice_date": inv_date.isoformat() if inv_date else None,
                "gstin": gstin_norm,
                "irn": irn,
                "ack_number": ack_no,
                "ack_date": ack_date.isoformat() if ack_date else None,
                "irn_status": irn_status,
                "value_paise": val_paise,
                "value": round(val_paise / 100.0, 2),
                "total_value": round(val_paise / 100.0, 2),
            }
        )

    return pd.DataFrame(records)
