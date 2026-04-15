"""Purchase Register parser — parses .xlsx / .xls / .csv purchase registers
into a normalised list of invoice records.

Relies on app.services.normalizer for GSTIN, date, and amount normalisation.
"""

import io
import logging
import re
from typing import Any

import pandas as pd

from app.services.normalizer import (
    NormalizationError,
    normalize_amount,
    normalize_date,
    normalize_gstin,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Raised when the file cannot be parsed into a usable DataFrame."""


# ---------------------------------------------------------------------------
# Column alias registry
# ---------------------------------------------------------------------------

COLUMN_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "gstin", "supplier gstin", "party gstin", "vendor gstin", "gst no",
        "gstn", "gst number", "vendor gst", "party gst no", "buyer gst",
    ],
    "invoice_number": [
        "invoice no", "invoice number", "inv no", "bill no",
        "bill number", "voucher no", "invoice #", "tax invoice no",
        "ref no", "doc no",
    ],
    "invoice_date": [
        "invoice date", "bill date", "bill dt", "date", "voucher date", "doc date",
    ],
    "taxable_amount": [
        "taxable value", "taxable amount", "base amount", "taxable",
        "assessable value", "value", "net amount",
    ],
    "igst": ["igst", "integrated tax", "igst amount", "igst paid"],
    "cgst": ["cgst", "central tax", "cgst amount"],
    "sgst": ["sgst", "state tax", "sgst amount", "utgst"],
    "total_tax": ["total tax", "gst amount", "tax amount", "total gst"],
    "total_amount": [
        "total", "total amount", "invoice value", "gross amount", "grand total",
    ],
    "supplier_name": [
        "supplier name", "party name", "vendor name", "name",
        "ledger name", "party",
    ],
    "place_of_supply": ["place of supply", "pos", "state"],
    "reverse_charge": ["reverse charge", "rcm", "reverse charge applicable"],
}

# Sheets whose normalised name contains any of these words are skipped.
_SKIP_SHEET_WORDS: frozenset[str] = frozenset(
    ["summary", "total", "instruction", "readme", "sheet"]
)

# Row-level skip markers (normalised cell value must start with one of these).
_SKIP_ROW_PREFIXES: tuple[str, ...] = (
    "grand total", "sub total", "subtotal", "total", "sum",
)

# Accounting Dr/Cr suffix (space-separated, e.g. "1,000.00 Cr")
_ACCT_SUFFIX_RE = re.compile(r"\s+(?:cr|dr)\.?\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Header normalisation
# ---------------------------------------------------------------------------

def normalize_header(col: str) -> str:
    """Lower-case, strip, remove punctuation, collapse spaces."""
    col = col.lower()
    col = col.strip()
    col = re.sub(r"[^\w\s]", "", col)
    col = re.sub(r"\s+", " ", col)
    return col.strip()


# ---------------------------------------------------------------------------
# Source-software detection
# ---------------------------------------------------------------------------

def detect_source_software(columns: list) -> str:
    """Heuristically identify the source accounting software."""
    norm_cols = {normalize_header(str(c)) for c in columns}
    if "voucher type" in norm_cols:
        return "Tally"
    if "narration" in norm_cols:
        return "Busy"
    return "Excel/Unknown"


# ---------------------------------------------------------------------------
# Column-mapping detection
# ---------------------------------------------------------------------------

def _alias_matches(col_norm: str, alias_norm: str) -> bool:
    """Return True when *alias_norm* matches *col_norm* at a word boundary.

    Accepts exact matches (``col_norm == alias_norm``) and prefix matches where
    the alias is followed by a space in the column name
    (``"invoice no mandatory"`` matches alias ``"invoice no"``).
    This handles real-world column headers that append extra descriptors such as
    ``(Mandatory)``, ``(Rs.)``, or ``of Supplier`` after the core alias text.
    """
    return col_norm == alias_norm or col_norm.startswith(alias_norm + " ")


def detect_column_mapping(df: pd.DataFrame) -> dict[str, str]:
    """Map standard field names to the actual column names present in *df*.

    Matching uses a longest-alias-wins strategy so that a column named
    ``"total tax"`` is preferred for ``total_tax`` (alias length 9) over
    ``total_amount`` (alias ``"total"``, length 5).

    Returns a dict ``{standard_name: original_column_name}``.

    Raises:
        ParseError: if neither ``gstin`` nor ``invoice_number`` can be matched.
    """
    original_cols: list[str] = list(df.columns)

    # Flatten all (std_name, alias_norm) pairs sorted longest alias first.
    # Longest-first guarantees the most specific alias wins when multiple
    # standard fields could match the same column.
    all_aliases: list[tuple[str, str]] = sorted(
        (
            (std, normalize_header(a))
            for std, aliases in COLUMN_ALIASES.items()
            for a in aliases
        ),
        key=lambda t: len(t[1]),
        reverse=True,
    )

    # For each column, find the single best (longest) matching standard field.
    mapping: dict[str, str] = {}  # std_name -> first matched original column
    for orig_col in original_cols:
        col_norm = normalize_header(str(orig_col))
        for std_name, alias_norm in all_aliases:
            if _alias_matches(col_norm, alias_norm):
                if std_name in mapping:
                    logger.warning(
                        "Field '%s' matched multiple columns [%s, %s] — "
                        "using first occurrence.",
                        std_name,
                        mapping[std_name],
                        orig_col,
                    )
                else:
                    mapping[std_name] = orig_col
                break  # stop at the longest match for this column

    if "gstin" not in mapping and "invoice_number" not in mapping:
        raise ParseError("Cannot identify GSTIN or invoice number columns")

    return mapping


# ---------------------------------------------------------------------------
# Row-level helpers
# ---------------------------------------------------------------------------

def _safe_cell(val: Any) -> str | None:
    """Return a stripped non-empty string, or None for blank / NaN cells."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    return s


_NUMERIC_REMAINDER_RE = re.compile(r"^[\d,. ]+$")

_TOTAL_KEYWORDS: tuple[str, ...] = (
    "grand total",
    "sub total",
    "subtotal",
    "total",
    "sum",
)


def is_total_row(row_values: list[str]) -> bool:
    """Return True only when a cell is an actual totals/summary marker.

    Rules (applied to each non-empty cell):
    - Exact match against a keyword → True.
    - Starts with a keyword AND the remainder is empty or purely numeric
      (digits, commas, decimals, spaces) → True.
    - "Total Solutions Pvt Ltd" — remainder is " Solutions Pvt Ltd" which is
      not numeric → False.
    """
    for raw in row_values:
        cell = raw.strip().lower()
        if not cell or cell in ("nan", "none", "nat"):
            continue
        for kw in _TOTAL_KEYWORDS:
            if cell == kw:
                return True
            if cell.startswith(kw):
                remainder = cell[len(kw):]
                if not remainder or _NUMERIC_REMAINDER_RE.match(remainder):
                    return True
    return False


def _normalize_reverse_charge(val: Any) -> bool | None:
    """Return True/False for RC flags, or None if the cell was empty."""
    s = _safe_cell(val)
    if s is None:
        return None
    return s.lower().strip() in {"y", "yes", "1", "true", "applicable"}


def _preprocess_amount(raw: str) -> str:
    """Strip trailing accounting Dr/Cr suffixes before passing to the normaliser."""
    return _ACCT_SUFFIX_RE.sub("", raw).strip()


def _parse_amount(raw_str: str) -> float | None:
    """Return the amount in rupees (float) or None on normalisation failure."""
    cleaned = _preprocess_amount(raw_str)
    if not cleaned:
        return None
    # normalize_amount now returns float rupees directly (or None on failure).
    return normalize_amount(cleaned)


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_purchase_register(file_content: bytes, filename: str) -> dict:
    """Parse a purchase-register file and return a structured result dict.

    Parameters
    ----------
    file_content:
        Raw bytes of the uploaded file.
    filename:
        Original filename (used to determine the parser and returned in records).

    Returns
    -------
    dict
        On success: ``{"success": True, "records": [...], ...}``
        On failure: ``{"success": False, "error": "...", "error_stage": "...", "records": []}``
    """
    ext = ""
    dot_idx = filename.rfind(".")
    if dot_idx != -1:
        ext = filename[dot_idx:].lower()

    df: pd.DataFrame | None = None
    column_mapping: dict[str, str] | None = None
    selected_header_row: int = 0
    source_cols: list = []

    # ------------------------------------------------------------------
    # STEP 1 — READ FILE
    # ------------------------------------------------------------------
    try:
        if ext in (".xlsx", ".xls"):
            try:
                xl = pd.ExcelFile(io.BytesIO(file_content))
                sheet_names: list[str] = xl.sheet_names
            except Exception as exc:
                raise ParseError(f"Cannot open Excel file: {exc}") from exc

            found = False
            for sheet_name in sheet_names:
                norm_sheet = normalize_header(str(sheet_name))
                if any(w in norm_sheet for w in _SKIP_SHEET_WORDS):
                    logger.debug("Skipping sheet '%s' (matched skip-word).", sheet_name)
                    continue

                for header_row in (0, 1, 2, 3):
                    try:
                        candidate = pd.read_excel(
                            io.BytesIO(file_content),
                            sheet_name=sheet_name,
                            header=header_row,
                            dtype=str,
                        ).reset_index(drop=True)
                        mapping = detect_column_mapping(candidate)
                        df = candidate
                        column_mapping = mapping
                        selected_header_row = header_row
                        source_cols = list(candidate.columns)
                        found = True
                        break
                    except ParseError:
                        continue

                if found:
                    break

            if not found:
                raise ParseError(
                    "Could not find a valid column mapping in any sheet or header row"
                )

        elif ext == ".csv":
            found = False
            for encoding in ("utf-8", "latin-1"):
                if found:
                    break
                try:
                    raw_text = file_content.decode(encoding, errors="replace")
                except Exception:
                    continue
                for header_row in (0, 1, 2):
                    try:
                        candidate = pd.read_csv(
                            io.StringIO(raw_text),
                            header=header_row,
                            dtype=str,
                        ).reset_index(drop=True)
                        mapping = detect_column_mapping(candidate)
                        df = candidate
                        column_mapping = mapping
                        selected_header_row = header_row
                        source_cols = list(candidate.columns)
                        found = True
                        break
                    except ParseError:
                        continue

            if not found:
                raise ParseError(
                    "Could not find a valid column mapping in the CSV file"
                )

        else:
            raise ParseError(f"Unsupported file extension: '{ext}'")

    except ParseError:
        raise
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "error_stage": "read_file",
            "records": [],
        }

    # ------------------------------------------------------------------
    # STEP 2 — COLUMN MAPPING
    # ------------------------------------------------------------------
    try:
        source_software = detect_source_software(source_cols)
        mapped_originals: set[str] = set(column_mapping.values())
        unmapped_columns: list[str] = [
            c for c in source_cols if c not in mapped_originals
        ]
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "error_stage": "column_mapping",
            "records": [],
        }

    # ------------------------------------------------------------------
    # STEP 3 — ROW PROCESSING
    # ------------------------------------------------------------------
    records: list[dict] = []
    warnings: list[str] = []
    total_rows: int = 0
    skipped_rows: int = 0

    try:
        for df_idx, row in df.iterrows():
            total_rows += 1
            # 1-indexed position in the source file (header row accounts for 1 row).
            row_number: int = selected_header_row + int(df_idx) + 2

            # Skip totals / summary rows.
            row_values = [str(v) if v is not None else "" for v in row]
            if is_total_row(row_values):
                skipped_rows += 1
                continue

            # Fetch raw values needed for the empty-row guard.
            inv_raw = (
                _safe_cell(row.get(column_mapping["invoice_number"]))
                if "invoice_number" in column_mapping
                else None
            )
            tax_raw = (
                _safe_cell(row.get(column_mapping["taxable_amount"]))
                if "taxable_amount" in column_mapping
                else None
            )
            if inv_raw is None and tax_raw is None:
                skipped_rows += 1
                continue

            # ---- Build output record ----
            out: dict[str, Any] = {
                "row_number": row_number,
                "invoice_number": None,
                "invoice_date": None,
                "gstin": None,
                "gstin_valid": False,
                "supplier_name": None,
                "taxable_value": None,
                "igst": None,
                "cgst": None,
                "sgst": None,
                "total_tax": None,
                "total_amount": None,
                "place_of_supply": None,
                "reverse_charge": None,
                "source_file": filename,
            }

            # invoice_number
            if inv_raw is not None:
                out["invoice_number"] = inv_raw

            # invoice_date
            if "invoice_date" in column_mapping:
                raw = _safe_cell(row.get(column_mapping["invoice_date"]))
                if raw is not None:
                    try:
                        result = normalize_date(raw)
                        out["invoice_date"] = result.value.isoformat()
                    except NormalizationError as exc:
                        warnings.append(
                            f"Row {row_number}: invalid date '{raw}' ({exc.reason})"
                        )

            # gstin — always store the raw value so callers can see it even when
            # validation fails; overwrite with the normalised form on success.
            if "gstin" in column_mapping:
                raw = _safe_cell(row.get(column_mapping["gstin"]))
                if raw is not None:
                    out["gstin"] = raw  # raw preserved regardless of validity
                    try:
                        out["gstin"] = normalize_gstin(raw)
                        out["gstin_valid"] = True
                    except NormalizationError as exc:
                        out["gstin_valid"] = False
                        warnings.append(
                            f"Row {row_number}: invalid GSTIN '{raw}' ({exc.reason})"
                        )

            # supplier_name
            if "supplier_name" in column_mapping:
                out["supplier_name"] = _safe_cell(
                    row.get(column_mapping["supplier_name"])
                )

            # Monetary amounts
            for std_field, out_key in (
                ("taxable_amount", "taxable_value"),
                ("igst", "igst"),
                ("cgst", "cgst"),
                ("sgst", "sgst"),
                ("total_tax", "total_tax"),
                ("total_amount", "total_amount"),
            ):
                if std_field in column_mapping:
                    raw = _safe_cell(row.get(column_mapping[std_field]))
                    if raw is not None:
                        # _parse_amount never raises; returns None on failure.
                        out[out_key] = _parse_amount(raw)

            # place_of_supply
            if "place_of_supply" in column_mapping:
                out["place_of_supply"] = _safe_cell(
                    row.get(column_mapping["place_of_supply"])
                )

            # reverse_charge
            if "reverse_charge" in column_mapping:
                out["reverse_charge"] = _normalize_reverse_charge(
                    row.get(column_mapping["reverse_charge"])
                )

            records.append(out)

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "error_stage": "row_processing",
            "records": [],
        }

    # ------------------------------------------------------------------
    # STEP 4 — RETURN
    # ------------------------------------------------------------------
    return {
        "success": True,
        "source_software": source_software,
        "total_rows": total_rows,
        "valid_rows": len(records),
        "skipped_rows": skipped_rows,
        "detected_columns": column_mapping,
        "unmapped_columns": unmapped_columns,
        "warnings": warnings,
        "records": records,
        "errors": [],
    }
