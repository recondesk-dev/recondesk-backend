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


def _classify_invoice_type(
    invoice_number: str | None, original_taxable: float | None
) -> str:
    """Classify document type from invoice number prefix and signed taxable value.

    Rules (same order as product spec):
    * ``CN`` prefix OR negative taxable → ``CREDIT_NOTE``
    * ``DN`` prefix → ``DEBIT_NOTE``
    * else → ``INVOICE``
    """
    inv = (invoice_number or "").strip().upper()
    if inv.startswith("CN") or (
        original_taxable is not None and original_taxable < 0
    ):
        return "CREDIT_NOTE"
    if inv.startswith("DN"):
        return "DEBIT_NOTE"
    return "INVOICE"


def _invoice_type_consistency_errors(
    invoice_type: str, original_taxable: float | None
) -> list[str]:
    """Return row-level error fragments when sign and type disagree."""
    errs: list[str] = []
    if original_taxable is None:
        return errs
    if invoice_type == "CREDIT_NOTE" and original_taxable > 0:
        errs.append("credit note with positive value")
    if invoice_type == "INVOICE" and original_taxable < 0:
        errs.append("invoice with negative value")
    return errs


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
        On success: includes ``skip_reasons`` (counts per skip category) alongside
        ``errors`` (row-level messages). Rows are either fully validated into
        ``records`` or omitted with a matching ``skip_reasons`` entry.
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
    errors: list[str] = []
    total_rows: int = 0
    skipped_rows: int = 0
    skip_reasons: dict[str, int] = {}

    def _bump_skip(reason: str) -> None:
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    def _is_blank_cell(s: str) -> bool:
        """Return True for cells that carry no meaningful value."""
        stripped = s.strip().lower()
        return not stripped or stripped in ("nan", "none", "nat")

    try:
        for df_idx, row in df.iterrows():
            total_rows += 1
            # 1-indexed position in the source file (header row accounts for 1 row).
            row_number: int = selected_header_row + int(df_idx) + 2

            # Skip totals / summary rows.
            row_values = [str(v) if v is not None else "" for v in row]
            if is_total_row(row_values):
                skipped_rows += 1
                _bump_skip("total_or_summary_row")
                continue

            # Empty row — every cell is blank / whitespace / NaN equivalent.
            if all(_is_blank_cell(cell) for cell in row_values):
                errors.append(f"Row {row_number}: empty row")
                skipped_rows += 1
                _bump_skip("empty_row")
                continue

            # ---- Collect ALL field-level errors before deciding row fate ----
            row_errors: list[str] = []

            # GSTIN
            gstin_value: str | None = None
            gstin_valid = False
            if "gstin" in column_mapping:
                raw_gstin = _safe_cell(row.get(column_mapping["gstin"]))
                if raw_gstin is None:
                    row_errors.append("missing GSTIN")
                else:
                    try:
                        gstin_value = normalize_gstin(raw_gstin)
                        gstin_valid = True
                    except NormalizationError:
                        row_errors.append("invalid GSTIN")

            # invoice_number
            inv_raw: str | None = None
            if "invoice_number" in column_mapping:
                inv_raw = _safe_cell(row.get(column_mapping["invoice_number"]))
                if inv_raw is None:
                    row_errors.append("missing invoice number")

            # invoice_date
            date_value: str | None = None
            if "invoice_date" in column_mapping:
                raw_date = _safe_cell(row.get(column_mapping["invoice_date"]))
                if raw_date is not None:
                    try:
                        result = normalize_date(raw_date)
                        date_value = result.value.isoformat()
                    except NormalizationError:
                        row_errors.append("invalid date")

            # taxable_value — non-empty but non-numeric is an explicit error.
            # Keep the parsed sign as *original_taxable* for type + validation; store abs().
            original_taxable: float | None = None
            taxable_value: float | None = None
            if "taxable_amount" in column_mapping:
                raw_tax = _safe_cell(row.get(column_mapping["taxable_amount"]))
                if raw_tax is not None:
                    parsed = _parse_amount(raw_tax)
                    if parsed is None:
                        row_errors.append("invalid value")
                    else:
                        original_taxable = parsed
                        taxable_value = abs(parsed)

            invoice_type = _classify_invoice_type(inv_raw, original_taxable)
            row_errors.extend(
                _invoice_type_consistency_errors(invoice_type, original_taxable)
            )

            # ---- Row decision: any error → reject the whole row ----
            if row_errors:
                errors.append(f"Row {row_number}: {', '.join(row_errors)}")
                skipped_rows += 1
                _bump_skip("invalid_row")
                continue

            # ---- Build output record (only reached when row is fully valid) ----
            out: dict[str, Any] = {
                "row_number": row_number,
                "invoice_number": inv_raw.upper() if inv_raw else None,
                "invoice_type": invoice_type,
                "invoice_date": date_value,
                "gstin": gstin_value,
                "gstin_valid": gstin_valid,
                "supplier_name": None,
                "taxable_value": taxable_value,
                "igst": None,
                "cgst": None,
                "sgst": None,
                "total_tax": None,
                "total_amount": None,
                "place_of_supply": None,
                "reverse_charge": None,
                "source_file": filename,
            }

            # supplier_name
            if "supplier_name" in column_mapping:
                out["supplier_name"] = _safe_cell(
                    row.get(column_mapping["supplier_name"])
                )

            # Remaining monetary amounts
            for std_field, out_key in (
                ("igst", "igst"),
                ("cgst", "cgst"),
                ("sgst", "sgst"),
                ("total_tax", "total_tax"),
                ("total_amount", "total_amount"),
            ):
                if std_field in column_mapping:
                    raw = _safe_cell(row.get(column_mapping[std_field]))
                    if raw is not None:
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

        # ------------------------------------------------------------------
        # STEP 3b — DUPLICATE DETECTION
        # First occurrence of a (gstin, invoice_number) key is kept as the
        # canonical record.  Every subsequent occurrence is an error — if
        # the values differ it is a conflict; if identical it is a redundant
        # duplicate.  Either way only the later rows are rejected.
        # ------------------------------------------------------------------
        seen_keys: dict[tuple, dict] = {}  # key → first record seen
        clean: list[dict] = []

        for rec in records:
            key = (rec.get("gstin"), rec.get("invoice_number"))
            if key[0] is None or key[1] is None:
                clean.append(rec)          # cannot deduplicate without both fields
                continue
            if key not in seen_keys:
                seen_keys[key] = rec       # first occurrence → keep
                clean.append(rec)
            else:
                # Subsequent occurrence — decide conflict vs exact duplicate
                first = seen_keys[key]
                if rec.get("taxable_value") != first.get("taxable_value"):
                    label = "conflicting duplicate"
                else:
                    label = "duplicate"
                reason_key = (
                    "conflicting_duplicate_invoice"
                    if label == "conflicting duplicate"
                    else "duplicate_invoice"
                )
                errors.append(
                    f"Row {rec['row_number']}: {label} invoice "
                    f"'{rec['invoice_number']}' for GSTIN '{rec['gstin']}' "
                    f"(first seen at row {first['row_number']})"
                )
                skipped_rows += 1
                _bump_skip(reason_key)

        records = clean

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
        "skip_reasons": skip_reasons,
        "detected_columns": column_mapping,
        "unmapped_columns": unmapped_columns,
        "warnings": warnings,
        "records": records,
        "errors": errors,
    }
