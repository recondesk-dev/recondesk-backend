"""Purchase Register parser — parses .xlsx / .xls / .csv purchase registers
into a normalised list of invoice records.

After reading a sheet into a DataFrame, columns are mapped to a canonical schema
(``gstin``, ``invoice_number_normalized``, ``invoice_date``, ``*_paise``, …)
aligned with ``app.services.sanity`` expectations.

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

# Internal detector names → canonical column names (aligned with app.services.sanity).
STANDARD_TO_CANONICAL: dict[str, str] = {
    "gstin": "gstin",
    "invoice_number": "invoice_number_normalized",
    "invoice_date": "invoice_date",
    "taxable_amount": "taxable_amount_paise",
    "igst": "igst_paise",
    "cgst": "cgst_paise",
    "sgst": "sgst_paise",
    "total_tax": "total_tax_paise",
    "total_amount": "total_amount_paise",
    "supplier_name": "supplier_name",
    "place_of_supply": "place_of_supply",
    "reverse_charge": "reverse_charge",
}

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


def _normalize_gstin_cell(val: Any) -> str | None:
    s = _safe_cell(val)
    if s is None:
        return None
    return s.strip().upper()


def _normalize_invoice_number_cell(val: Any) -> str | None:
    s = _safe_cell(val)
    if s is None:
        return None
    if isinstance(val, (int, float)) and not pd.isna(val):
        if isinstance(val, float) and val == int(val):
            return str(int(val)).strip().upper()
        if isinstance(val, int):
            return str(val).strip().upper()
    return str(s).strip().upper()


def _rupees_to_paise_int_signed(val: Any) -> int | None:
    s = _safe_cell(val)
    if s is None:
        return None
    r = _parse_amount(s)
    if r is None:
        return None
    return int(round(r * 100))


def _rupees_to_paise_int_unsigned(val: Any) -> int | None:
    s = _safe_cell(val)
    if s is None:
        return None
    r = _parse_amount(s)
    if r is None:
        return None
    return int(round(abs(r) * 100))


def normalize_dataframe_to_canonical_schema(
    df: pd.DataFrame, column_mapping: dict[str, str]
) -> pd.DataFrame:
    """Build a DataFrame with canonical column names and sanity-aligned values.

    Rows match *df*; string columns are stripped; *gstin* is uppercased;
    invoice numbers are strings (upper); rupee amounts in source cells become
    integer paise (signed for taxable; unsigned for tax components).
    """
    out_cols: dict[str, pd.Series] = {}
    for std_name, orig_col in column_mapping.items():
        if std_name not in STANDARD_TO_CANONICAL:
            continue
        if orig_col not in df.columns:
            continue
        canon = STANDARD_TO_CANONICAL[std_name]
        ser = df[orig_col]
        if canon == "gstin":
            out_cols[canon] = ser.map(_normalize_gstin_cell)
        elif canon == "invoice_number_normalized":
            out_cols[canon] = ser.map(_normalize_invoice_number_cell)
        elif canon == "invoice_date":
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "taxable_amount_paise":
            out_cols[canon] = ser.map(_rupees_to_paise_int_signed)
        elif canon in (
            "igst_paise",
            "cgst_paise",
            "sgst_paise",
            "total_tax_paise",
            "total_amount_paise",
        ):
            out_cols[canon] = ser.map(_rupees_to_paise_int_unsigned)
        elif canon in ("supplier_name", "place_of_supply"):
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "reverse_charge":
            out_cols[canon] = ser.map(_normalize_reverse_charge)

    if not out_cols:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame(out_cols, index=df.index)


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


def _df_cell_int(val: Any) -> int | None:
    """Return int from a DataFrame cell, or None for missing/NaN."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, bool):
        return None
    return int(val)


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
        Always includes ``success``, ``total_rows``, ``valid_rows``, ``records``,
        and ``errors``. On a full parse, also includes ``source_software``,
        ``skipped_rows``, ``skip_reasons``, ``detected_columns``, ``unmapped_columns``,
        and ``warnings``.
    """
    result: dict[str, Any] = {
        "success": False,
        "total_rows": 0,
        "valid_rows": 0,
        "records": [],
        "errors": [],
    }
    if not file_content or not file_content.strip():
        result["errors"].append("Empty file")
        return result

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

    except ParseError as exc:
        result["errors"].append(str(exc))
        return result
    except Exception as exc:
        result["errors"].append(f"read_file: {exc}")
        return result

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
        result["errors"].append(f"column_mapping: {exc}")
        return result

    header_detected = True

    # Canonical schema (renamed columns, GSTIN uppercased, amounts as paise ints).
    df_canon = normalize_dataframe_to_canonical_schema(df, column_mapping)

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
        for df_idx, row in df_canon.iterrows():
            total_rows += 1
            # 1-indexed position in the source file (header row accounts for 1 row).
            row_number: int = selected_header_row + int(df_idx) + 2
            orig_row = df.loc[df_idx]

            # Skip totals / summary rows (use raw row for detection).
            row_values = [str(v) if v is not None else "" for v in orig_row]
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

            # GSTIN (canonical column is uppercased; validate with normaliser)
            gstin_value: str | None = None
            gstin_valid = False
            if "gstin" in column_mapping:
                raw_gstin = row.get("gstin")
                if raw_gstin is None:
                    row_errors.append("missing GSTIN")
                else:
                    try:
                        gstin_value = normalize_gstin(str(raw_gstin))
                        gstin_valid = True
                    except NormalizationError:
                        row_errors.append("invalid GSTIN")

            # invoice_number_normalized
            inv_raw: str | None = None
            if "invoice_number" in column_mapping:
                cell = row.get("invoice_number_normalized")
                if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                    inv_raw = None
                else:
                    inv_raw = str(cell).strip().upper() if str(cell).strip() else None
                if inv_raw is None:
                    row_errors.append("missing invoice number")

            # invoice_date
            date_value: str | None = None
            if "invoice_date" in column_mapping:
                raw_date = _safe_cell(orig_row.get(column_mapping["invoice_date"]))
                if raw_date is not None:
                    try:
                        norm_date = normalize_date(raw_date)
                        date_value = norm_date.value.isoformat()
                    except NormalizationError:
                        row_errors.append("invalid date")

            # taxable_amount_paise — sign preserved for classification (rupees in source).
            original_taxable: float | None = None
            taxable_amount_paise: int | None = None
            if "taxable_amount" in column_mapping:
                raw_tax = _safe_cell(orig_row.get(column_mapping["taxable_amount"]))
                taxable_amount_paise = _df_cell_int(row.get("taxable_amount_paise"))
                if raw_tax is not None:
                    if taxable_amount_paise is None:
                        row_errors.append("invalid value")
                    else:
                        original_taxable = taxable_amount_paise / 100.0

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

            igst_paise = _df_cell_int(row.get("igst_paise"))
            cgst_paise = _df_cell_int(row.get("cgst_paise"))
            sgst_paise = _df_cell_int(row.get("sgst_paise"))
            total_tax_paise = _df_cell_int(row.get("total_tax_paise"))
            if total_tax_paise is None and (
                igst_paise is not None or cgst_paise is not None or sgst_paise is not None
            ):
                total_tax_paise = (igst_paise or 0) + (cgst_paise or 0) + (sgst_paise or 0)

            _rcell = row.get("reverse_charge")
            if _rcell is None or (isinstance(_rcell, float) and pd.isna(_rcell)):
                reverse_out: bool | None = None
            else:
                reverse_out = _rcell  # type: ignore[assignment]

            # ---- Build output record (only reached when row is fully valid) ----
            out: dict[str, Any] = {
                "row_number": row_number,
                "invoice_number_normalized": inv_raw,
                "invoice_number": inv_raw,
                "document_type": invoice_type,
                "invoice_type": invoice_type,
                "invoice_date": date_value,
                "gstin": gstin_value,
                "gstin_valid": gstin_valid,
                "supplier_name": _safe_cell(row.get("supplier_name")),
                "taxable_amount_paise": taxable_amount_paise,
                "igst_paise": igst_paise,
                "cgst_paise": cgst_paise,
                "sgst_paise": sgst_paise,
                "total_tax_paise": total_tax_paise,
                "total_amount_paise": _df_cell_int(row.get("total_amount_paise")),
                "place_of_supply": _safe_cell(row.get("place_of_supply")),
                "reverse_charge": reverse_out,
                "source_file": filename,
            }

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
            key = (rec.get("gstin"), rec.get("invoice_number_normalized"))
            if key[0] is None or key[1] is None:
                clean.append(rec)          # cannot deduplicate without both fields
                continue
            if key not in seen_keys:
                seen_keys[key] = rec       # first occurrence → keep
                clean.append(rec)
            else:
                # Subsequent occurrence — decide conflict vs exact duplicate
                first = seen_keys[key]
                if rec.get("taxable_amount_paise") != first.get("taxable_amount_paise"):
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
                    f"'{rec['invoice_number_normalized']}' for GSTIN '{rec['gstin']}' "
                    f"(first seen at row {first['row_number']})"
                )
                skipped_rows += 1
                _bump_skip(reason_key)

        records = clean

    except Exception as exc:
        result["errors"].append(f"row_processing: {exc}")
        return result

    # ------------------------------------------------------------------
    # STEP 4 — RETURN
    # ------------------------------------------------------------------
    result["total_rows"] = total_rows
    result["valid_rows"] = len(records)
    result["records"] = records
    result["errors"] = errors
    if result["total_rows"] == 0 and header_detected:
        result["errors"].append("No data rows found")
        result["success"] = False
    else:
        result["success"] = result["valid_rows"] > 0
    result["source_software"] = source_software
    result["skipped_rows"] = skipped_rows
    result["skip_reasons"] = skip_reasons
    result["detected_columns"] = column_mapping
    result["unmapped_columns"] = unmapped_columns
    result["warnings"] = warnings
    return result
