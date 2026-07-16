"""Sales Register parser — parses .xlsx / .xls / .csv sales registers
into a normalised list of invoice records for GSTR-1 reconciliation.

After reading a sheet into a DataFrame, columns are mapped to a canonical schema
(``gstin``, ``invoice_number_normalized``, ``invoice_date``, ``*_paise``, …)
aligned with GSTR-1 reconciliation expectations.

Follows the same architectural pattern as ``app.parsers.purchase_register_parser``.
Relies on app.services.normalizer for GSTIN, date, and amount normalisation.
"""

import io
import logging
import os
import re
import time
from typing import Any

import pandas as pd

from app.services.normalizer import (
    NormalizationError,
    normalize_amount as normalize_amount_to_paise,
    normalize_date,
    normalize_gstin,
)
from app.services.matcher import normalize_invoice
from app.parsers.tally_register import (
    TALLY_SALES_ALIASES,
    detect_source_software_tally,
    extract_gstin_from_party_cell,
    is_multiline_party_name,
    looks_like_tally_headers,
    merge_aliases,
    validate_tally_export,
)

logger = logging.getLogger(__name__)

# Soft ceiling for multi-sheet SR parse wall-clock. Exceeding raises ParseError
# so the worker fails the import with a clear message instead of hanging forever.
# Override with env SR_PARSE_SOFT_TIMEOUT_SEC (0 disables).
_SR_PARSE_SOFT_TIMEOUT_SEC = float(os.environ.get("SR_PARSE_SOFT_TIMEOUT_SEC", "120"))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Raised when the file cannot be parsed into a usable DataFrame."""


# ---------------------------------------------------------------------------
# Column alias registry
# ---------------------------------------------------------------------------

# Internal detector names → canonical column names.
STANDARD_TO_CANONICAL: dict[str, str] = {
    "gstin": "gstin",
    "invoice_number": "invoice_number_normalized",
    "invoice_date": "invoice_date",
    "taxable_amount": "taxable_amount_paise",
    "igst": "igst_paise",
    "cgst": "cgst_paise",
    "sgst": "sgst_paise",
    "cess": "cess_paise",
    "total_tax": "total_tax_paise",
    "total_amount": "total_amount_paise",
    "recipient_name": "recipient_name",
    "place_of_supply": "place_of_supply",
    "invoice_type": "invoice_type",
    "hsn": "hsn",
    "reverse_charge": "reverse_charge",
    "shipping_port_code": "shipping_port_code",
    "shipping_bill_number": "shipping_bill_number",
    "shipping_bill_date": "shipping_bill_date",
    "export_type": "export_type",
}

# Placeholder GSTIN tokens that mean "no GSTIN" (B2C / unregistered), not a
# literal GSTIN string. Compared case-insensitively after strip.
_ABSENT_GSTIN_TOKENS: frozenset[str] = frozenset(
    {
        "NA",
        "N/A",
        "N.A",
        "N.A.",
        "NONE",
        "NULL",
        "NIL",
        "-",
        "--",
        ".",
        "0",
        "UNREGISTERED",
        "URP",
    }
)

_BASE_COLUMN_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "gstin", "recipient gstin", "party gstin", "buyer gstin",
        "customer gstin", "gst no", "gstn", "gst number",
        "buyer gst", "party gst no", "customer gst", "gstin uin",
        "gstin uin of recipient",
        # Tally / books exports
        "gst reg no", "gst reg. no", "gst registration no",
        "gst registration number", "gstin/uin", "gstin / uin",
    ],
    "invoice_number": [
        "invoice no", "invoice number", "inv no", "bill no",
        "bill number", "voucher no", "voucher number", "vch no",
        "vch number", "vch no.", "invoice #", "tax invoice no",
        "ref no", "doc no", "document number", "sale invoice no",
        "sales invoice no",
    ],
    "invoice_date": [
        "invoice date", "bill date", "bill dt", "date", "voucher date",
        "doc date", "document date", "sale date", "sales date",
    ],
    "taxable_amount": [
        "taxable value", "taxable amount", "base amount", "taxable",
        "assessable value", "value", "net amount",
        "amount", "invoice value", "total amount",
        "taxable amt",
    ],
    "igst": [
        "igst", "integrated tax", "igst amount", "igst tax", "i.g.s.t",
        "igst paid", "igst collected",
    ],
    "cgst": ["cgst", "central tax", "cgst amount", "cgst tax", "c.g.s.t"],
    "sgst": [
        "sgst", "state tax", "sgst amount", "sgst tax", "utgst",
        "s.g.s.t", "u.t.g.s.t",
    ],
    "cess": ["cess", "cess amount", "gst cess", "compensation cess"],
    "total_tax": ["total tax", "gst amount", "tax amount", "total gst"],
    "total_amount": [
        "total invoice value", "total value", "invoice value", "invoice amount",
        "total amount", "gross amount", "gross value", "gross total",
        "bill amount", "bill value",
        "net amount", "net value", "total", "grand total",
    ],
    "recipient_name": [
        "recipient name", "recipient", "buyer name", "buyer",
        "customer name", "customer", "party name", "party",
        "ledger name", "ledger", "sold to", "bill to",
        "consignee", "debtor name", "debtor", "to", "name",
        "particulars",  # Tally sales register
    ],
    "place_of_supply": [
        "place of supply", "pos", "state", "state name",
        "destination state", "supply state",
    ],
    "invoice_type": [
        "invoice type", "document type", "doc type", "type",
        "voucher type name", "transaction type", "supply type",
    ],
    "reverse_charge": ["reverse charge", "rcm", "reverse charge applicable"],
    "hsn": [
        "hsn", "hsn code", "hsn/sac", "sac", "sac code", "hsn code/sac code",
    ],
    "shipping_port_code": ["port code", "shipping port code"],
    "shipping_bill_number": [
        "shipping bill no", "shipping bill number", "sb no", "sb number",
    ],
    "shipping_bill_date": [
        "shipping bill date", "sb date",
    ],
    "export_type": [
        "export type", "type of export",
    ],
}

# Includes the named "Tally Export" alias profile (Particulars, Party's A/c Name, …).
COLUMN_ALIASES: dict[str, list[str]] = merge_aliases(
    _BASE_COLUMN_ALIASES, TALLY_SALES_ALIASES
)

# Sheets whose normalised name contains any of these words are skipped.
_SKIP_SHEET_WORDS: frozenset[str] = frozenset(
    ["summary", "total", "instruction", "readme"]
)

# Row-level skip markers (normalised cell value must start with one of these).
_SKIP_ROW_PREFIXES: tuple[str, ...] = (
    "grand total", "sub total", "subtotal", "total", "sum",
)

# Accounting Dr/Cr suffix (space-separated, e.g. "1,000.00 Cr")
_ACCT_SUFFIX_RE = re.compile(r"\s+(?:cr|dr)\.?\s*$", re.IGNORECASE)

# Indian state code → state name for place_of_supply normalisation
_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (Old)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh",
    "96": "Foreign Country", "97": "Other Territory",
}


# ---------------------------------------------------------------------------
# Header normalisation
# ---------------------------------------------------------------------------

def normalize_header(col: str) -> str:
    """Lower-case, strip, treat underscores/punctuation as spaces, collapse spaces."""
    col = col.lower()
    col = col.strip()
    col = col.replace("_", " ")
    col = re.sub(r"[^\w\s]", " ", col)
    col = re.sub(r"\s+", " ", col)
    return col.strip()


# ---------------------------------------------------------------------------
# Source-software detection
# ---------------------------------------------------------------------------

def detect_source_software(columns: list) -> str:
    """Heuristically identify the source accounting software."""
    tally = detect_source_software_tally(columns)
    if tally:
        return tally
    norm_cols = {normalize_header(str(c)) for c in columns}
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
    ``(Mandatory)``, ``(Rs.)``, or ``of Recipient`` after the core alias text.
    """
    return col_norm == alias_norm or col_norm.startswith(alias_norm + " ")


def _alias_match_quality(col_norm: str, alias_norm: str) -> tuple[int, int] | None:
    """Score how well *alias_norm* matches *col_norm*.

    Returns ``(tier, alias_length)`` where tier ``2`` is an exact header match and
    tier ``1`` is a prefix match (alias plus trailing descriptor words).
    ``None`` when there is no match.
    """
    if col_norm == alias_norm:
        return (2, len(alias_norm))
    if col_norm.startswith(alias_norm + " "):
        return (1, len(alias_norm))
    return None


# When two standard fields share the same alias (e.g. ``"total amount"`` appears in
# both ``taxable_amount`` and ``total_amount``), break ties in favour of the field
# that owns that concept in sales-register exports.
_FIELD_MATCH_PRIORITY: dict[str, int] = {
    "recipient_name": 50,
    "gstin": 40,
    "invoice_number": 50,
    "invoice_date": 50,
    "total_amount": 50,
    "total_tax": 45,
    "taxable_amount": 40,
    "igst": 50,
    "cgst": 50,
    "sgst": 50,
    "cess": 50,
    "place_of_supply": 50,
    "invoice_type": 50,
    "reverse_charge": 50,
    "hsn": 45,
    "shipping_port_code": 40,
    "shipping_bill_number": 40,
    "shipping_bill_date": 40,
    "export_type": 40,
}

def _uniqueify_header_labels(headers: list[Any]) -> list[str]:
    """Make column labels unique the same way pandas does for duplicate headers."""
    seen: dict[str, int] = {}
    unique_headers: list[str] = []
    for h in headers:
        if h is None or (isinstance(h, float) and pd.isna(h)):
            label = ""
        else:
            label = str(h)
        if label in seen:
            seen[label] += 1
            unique_headers.append(f"{label}.{seen[label]}")
        else:
            seen[label] = 0
            unique_headers.append(label)
    return unique_headers


def _find_best_header_from_raw(
    raw_df: pd.DataFrame, max_rows: int = 20
) -> tuple[pd.DataFrame | None, dict[str, str] | None, int]:
    """
    Given a DataFrame parsed without headers (header=None), scan the first
    `max_rows` to find the row that matches the most standard fields.

    Mapping detection uses header labels only (O(max_rows × cols × aliases)).
    The full body is sliced/copied once for the winning header row — never
    once per candidate — so cost stays linear in sheet size.
    """
    best_mapping: dict[str, str] | None = None
    best_headers: list[str] | None = None
    best_header_row = -1
    max_score = -1

    fallback_mapping: dict[str, str] | None = None
    fallback_headers: list[str] | None = None

    max_check = min(max_rows, len(raw_df))
    for header_row in range(max_check):
        unique_headers = _uniqueify_header_labels(
            list(raw_df.iloc[header_row].tolist())
        )
        # detect_column_mapping only inspects column names — do not copy the body.
        stub = pd.DataFrame(columns=unique_headers)
        try:
            mapping = detect_column_mapping(stub)
            score = len(mapping)
            if score > max_score:
                max_score = score
                best_mapping = mapping
                best_headers = unique_headers
                best_header_row = header_row
        except ParseError:
            pass

        if header_row == 0:
            fallback_headers = unique_headers
            try:
                fallback_mapping = detect_column_mapping(stub)
            except ParseError:
                fallback_mapping = None

    def _slice_body(header_row: int, headers: list[str]) -> pd.DataFrame:
        candidate = raw_df.iloc[header_row + 1:].copy()
        candidate.columns = headers
        return candidate.reset_index(drop=True)

    if max_score >= 3 and best_mapping is not None and best_headers is not None:
        return (
            _slice_body(best_header_row, best_headers),
            best_mapping,
            best_header_row,
        )
    if fallback_mapping is not None and fallback_headers is not None:
        return _slice_body(0, fallback_headers), fallback_mapping, 0

    return None, None, -1


def detect_column_mapping(df: pd.DataFrame) -> dict[str, str]:
    """Map standard field names to the actual column names present in *df*.

    Each source column is assigned to the standard field with the best match score:
    exact header match beats prefix match; longer alias beats shorter; on remaining
    ties, ``_FIELD_MATCH_PRIORITY`` prefers the more specific field (e.g.
    ``total_amount`` over ``taxable_amount`` for a column named ``"Total Amount"``).

    Returns a dict ``{standard_name: original_column_name}``.

    Raises:
        ParseError: if neither ``gstin`` nor ``invoice_number`` can be matched.
    """
    original_cols: list[str] = list(df.columns)

    # std_name -> (tier, alias_len, priority, original_column)
    column_matches: dict[str, tuple[int, int, int, str]] = {}

    for orig_col in original_cols:
        col_norm = normalize_header(str(orig_col))
        best: tuple[int, int, int, str] | None = None  # tier, alias_len, priority, std_name

        for std_name, aliases in COLUMN_ALIASES.items():
            priority = _FIELD_MATCH_PRIORITY.get(std_name, 0)
            for alias in aliases:
                alias_norm = normalize_header(alias)
                quality = _alias_match_quality(col_norm, alias_norm)
                if quality is None:
                    continue
                tier, alias_len = quality
                candidate = (tier, alias_len, priority, std_name)
                if best is None or candidate > best:
                    best = candidate

        if best is None:
            continue

        tier, alias_len, priority, std_name = best
        prev = column_matches.get(std_name)
        if prev is not None:
            current = (tier, alias_len, priority)
            previous = prev[:3]
            if current > previous:
                logger.warning(
                    "Field '%s' matched multiple columns [%s, %s] — "
                    "using better match '%s'.",
                    std_name,
                    prev[3],
                    orig_col,
                    orig_col,
                )
                column_matches[std_name] = (tier, alias_len, priority, orig_col)
            else:
                logger.warning(
                    "Field '%s' matched multiple columns [%s, %s] — "
                    "using better match '%s'.",
                    std_name,
                    prev[3],
                    orig_col,
                    prev[3],
                )
        else:
            column_matches[std_name] = (tier, alias_len, priority, orig_col)

    mapping = {std: orig for std, (_, _, _, orig) in column_matches.items()}

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
    if not isinstance(raw, str):
        raw = str(raw)
    s = _ACCT_SUFFIX_RE.sub("", raw)
    return s.replace("₹", "").replace(",", "").replace(" ", "").strip()


def _parse_amount(raw_str: str) -> int | None:
    """Return the amount in paise, or None on normalisation failure."""
    cleaned = _preprocess_amount(raw_str)
    if not cleaned:
        return None
    try:
        return int(normalize_amount_to_paise(cleaned).value)
    except NormalizationError:
        return None


def _is_absent_gstin_token(val: str | None) -> bool:
    """True when *val* is a placeholder meaning no GSTIN (B2C / unregistered)."""
    if val is None:
        return True
    cleaned = val.strip().upper()
    if not cleaned:
        return True
    # Collapse common punctuation variants: "N/A", "N.A.", "N A"
    collapsed = re.sub(r"[\s./\\-]+", "", cleaned)
    if cleaned in _ABSENT_GSTIN_TOKENS or collapsed in {"NA", "NIL", "NULL", "NONE", "URP"}:
        return True
    return False


def _normalize_gstin_cell(val: Any) -> str | None:
    """Upper-case GSTIN text, or ``None`` for blank / NaN / NA-placeholder cells.

    Never returns the literal ``\"NAN\"`` — pandas missing values must not
    leak into matching as a fake GSTIN string.  ``\"NA\"`` / ``\"N/A\"`` are
    treated as absent (same as empty), not as a literal GSTIN to compare.
    """
    s = _safe_cell(val)
    if s is None or _is_absent_gstin_token(s):
        return None
    return s.strip().upper()


def _series_as_optional_str(ser: pd.Series, mapper) -> pd.Series:
    """Map *ser* through *mapper* and keep real ``None`` (object dtype).

    Pandas StringDtype / float upcasting turns Python ``None`` back into
    ``NA`` / ``NaN``.  ``iterrows`` then yields ``nan``, and
    ``str(nan).upper()`` becomes the bogus GSTIN ``\"NAN\"``.
    """
    values = [mapper(v) for v in ser.tolist()]
    # Re-scrub in case mapper returned a pandas NA sentinel
    cleaned: list[Any] = []
    for v in values:
        if v is None:
            cleaned.append(None)
            continue
        try:
            if pd.isna(v):
                cleaned.append(None)
                continue
        except (TypeError, ValueError):
            pass
        cleaned.append(v)
    return pd.Series(cleaned, index=ser.index, dtype=object)


def _coerce_mapped_gstin_column(
    df: pd.DataFrame, column_mapping: dict[str, str]
) -> pd.DataFrame:
    """Force the detected GSTIN column to optional strings before row parse.

    Blank / B2C cells → ``None``.  Populated cells keep their exact text
    (upper-cased), never coerced through a numeric dtype.
    """
    gstin_col = column_mapping.get("gstin")
    if not gstin_col or gstin_col not in df.columns:
        return df
    out = df.copy()
    out[gstin_col] = _series_as_optional_str(out[gstin_col], _normalize_gstin_cell)
    return out


def _normalize_invoice_number_cell(val: Any) -> str | None:
    s = _safe_cell(val)
    if s is None:
        return None
    if isinstance(val, (int, float)) and not pd.isna(val):
        if isinstance(val, float) and val == int(val):
            return normalize_invoice(str(int(val)))
        if isinstance(val, int):
            return normalize_invoice(str(val))
    return normalize_invoice(str(s))


def normalize_amount(value: Any) -> int:
    """Convert input to integer paise safely.

    Handles strings, commas, and floats. Returns ``0`` for ``None`` / empty /
    unparseable input. Kept for callers that imported this helper directly.
    """
    if value is None or value == "":
        return 0
    try:
        return int(normalize_amount_to_paise(_preprocess_amount(str(value))).value)
    except (NormalizationError, TypeError, ValueError):
        return 0


def _amount_int_signed(val: Any) -> int | None:
    """Row helper: return signed integer amount, or None for blank / invalid.

    Preserves sign (used by credit-note classification). Returns paise.
    """
    s = _safe_cell(val)
    if s is None:
        return None
    r = _parse_amount(s)
    if r is None:
        return None
    return int(r)


def _amount_int_unsigned(val: Any) -> int | None:
    """Row helper: return absolute paise amount, or None for blank / invalid."""
    s = _safe_cell(val)
    if s is None:
        return None
    r = _parse_amount(s)
    if r is None:
        return None
    return int(abs(r))


def normalize_dataframe_to_canonical_schema(
    df: pd.DataFrame, column_mapping: dict[str, str]
) -> pd.DataFrame:
    """Build a DataFrame with canonical column names and normalised values.

    Rows match *df*; string columns are stripped; *gstin* is uppercased;
    invoice numbers are strings (upper); numeric amount cells are normalized to
    integer paise via ``normalize_amount``.
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
            out_cols[canon] = _series_as_optional_str(ser, _normalize_gstin_cell)
        elif canon == "invoice_number_normalized":
            out_cols[canon] = ser.map(_normalize_invoice_number_cell)
        elif canon == "invoice_date":
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "taxable_amount_paise":
            out_cols[canon] = ser.map(_amount_int_signed)
        elif canon in (
            "igst_paise",
            "cgst_paise",
            "sgst_paise",
            "cess_paise",
            "total_tax_paise",
            "total_amount_paise",
        ):
            out_cols[canon] = ser.map(_amount_int_unsigned)
        elif canon in (
            "recipient_name", "place_of_supply", "invoice_type",
            "shipping_port_code", "export_type",
        ):
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "reverse_charge":
            out_cols[canon] = ser.map(_normalize_reverse_charge)
        elif canon in ("shipping_bill_number", "shipping_bill_date"):
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "hsn":
            out_cols[canon] = ser.map(_safe_cell)

    if not out_cols:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame(out_cols, index=df.index)


# ---------------------------------------------------------------------------
# Invoice type classification (GSTR-1 categories)
# ---------------------------------------------------------------------------

# GSTIN regex: 15-char alphanumeric pattern
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Keywords for detecting invoice type from an explicit column
_INVOICE_TYPE_KEYWORDS: dict[str, list[str]] = {
    "B2B": [
        "b2b", "business to business", "b 2 b", "regular",
        "tax invoice", "taxable",
    ],
    "B2C_LARGE": [
        "b2c large", "b2c (large)", "b2cl", "b2c-large",
    ],
    "B2C_SMALL": [
        "b2c small", "b2c (small)", "b2cs", "b2c-small",
        "b2c others",
    ],
    "B2C": [
        "b2c", "business to consumer", "b 2 c", "consumer", "cash sale",
        "cash sales", "pos sale", "retail",
    ],
    "EXPORT": [
        "export", "exp", "export with payment", "export without payment",
        "exports", "sez", "deemed export", "sez with payment",
        "sez without payment",
    ],
    "CREDIT_NOTE": [
        "credit note", "cr note", "credit memo", "cn", "sales return",
        "credit", "credit note (b2b)", "credit note (b2c)",
    ],
    "DEBIT_NOTE": [
        "debit note", "dr note", "debit memo", "dn", "debit",
        "debit note (b2b)", "debit note (b2c)",
    ],
    "NIL_RATED": [
        "nil rated", "nil", "nil rated/exempt", "exempt",
        "non gst", "non-gst",
    ],
    "ADVANCES": [
        "advance", "advances received", "advance receipt",
    ],
}


def _normalize_place_of_supply(val: str | None) -> str | None:
    """Normalise place of supply to ``"<code>-<State Name>"`` form.

    Handles:
    - Already formatted "27-Maharashtra"
    - Bare state codes "27"
    - Full state names "Maharashtra"
    - State codes embedded in strings "27 - Maharashtra"
    """
    if val is None:
        return None
    val = val.strip()
    if not val:
        return None

    # Try to extract leading 2-digit state code
    m = re.match(r"^(\d{2})\s*[-–—]?\s*(.*)", val)
    if m:
        code = m.group(1)
        if code in _STATE_CODES:
            return f"{code}-{_STATE_CODES[code]}"
        # Unknown code — return as-is
        return val

    # Try matching full state name to a code
    val_lower = val.lower()
    for code, name in _STATE_CODES.items():
        if val_lower == name.lower():
            return f"{code}-{name}"

    # Return as-is if we can't normalise
    return val


def _classify_invoice_type_from_column(raw_type: str | None) -> str | None:
    """Map an explicit invoice_type column value to a GSTR-1 category.

    Returns None if the value doesn't match any known category.
    """
    if raw_type is None:
        return None
    norm = raw_type.strip().lower()
    if not norm:
        return None

    # Check more specific categories first (B2C_LARGE before B2C, etc.)
    # Order matters: check longer/more-specific keywords first.
    for category in (
        "B2C_LARGE", "B2C_SMALL", "CREDIT_NOTE", "DEBIT_NOTE",
        "NIL_RATED", "ADVANCES", "EXPORT", "B2B", "B2C",
    ):
        for kw in _INVOICE_TYPE_KEYWORDS[category]:
            if norm == kw or norm.startswith(kw + " ") or norm.startswith(kw + "("):
                return category
    return None


def _classify_invoice_type(
    invoice_number: str | None,
    original_taxable: int | None,
    gstin: str | None,
    explicit_type: str | None,
    place_of_supply: str | None,
) -> str:
    """Classify document type for GSTR-1 reporting.

    Priority:
    1. Explicit invoice_type column value (if mapped and recognised).
    2. Invoice number prefix: ``CN`` → CREDIT_NOTE, ``DN`` → DEBIT_NOTE.
    3. Negative taxable value → CREDIT_NOTE.
    4. Place of supply indicates foreign country (code 96/97) → EXPORT.
    5. Valid GSTIN present → B2B.
    6. No valid GSTIN → B2C.
    """
    # 1. Explicit column
    if explicit_type is not None:
        explicit_cat = _classify_invoice_type_from_column(explicit_type)
        if explicit_cat is not None:
            return explicit_cat

    # 2. Invoice number prefix
    inv = (invoice_number or "").strip().upper()
    if inv.startswith("CN") or (
        original_taxable is not None and original_taxable < 0
    ):
        return "CREDIT_NOTE"
    if inv.startswith("DN"):
        return "DEBIT_NOTE"

    # 3. (Negative taxable already handled above with CN prefix check)

    # 4. Export detection via place of supply
    if place_of_supply:
        pos_norm = place_of_supply.strip()
        pos_code = re.match(r"^(\d{2})", pos_norm)
        if pos_code and pos_code.group(1) in ("96", "97"):
            return "EXPORT"

    # 5. B2B if valid GSTIN
    if gstin and _GSTIN_RE.match(gstin.strip().upper()):
        return "B2B"

    # 6. Fallback to B2C
    return "B2C"


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
    invoice_type: str, original_taxable: int | None
) -> list[str]:
    """Return row-level error fragments when sign and type disagree."""
    errs: list[str] = []
    if original_taxable is None:
        return errs
    if invoice_type == "CREDIT_NOTE" and original_taxable > 0:
        errs.append("credit note with positive value")
    if invoice_type in ("B2B", "B2C", "EXPORT") and original_taxable < 0:
        errs.append("invoice with negative value")
    return errs


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def list_candidate_sr_sheet_names(file_content: bytes, filename: str) -> list[str]:
    """Return Excel sheet names excluding skip-word sheets (no header detection).

    Cheap O(sheets) peek used to decide whether to skip single-sheet reshape
    before the full ``parse_sales_register`` pass.
    """
    ext = ""
    dot_idx = filename.rfind(".")
    if dot_idx != -1:
        ext = filename[dot_idx:].lower()
    if ext not in (".xlsx", ".xls"):
        return []
    try:
        xl = pd.ExcelFile(io.BytesIO(file_content))
    except Exception:
        return []
    names: list[str] = []
    for sheet_name in xl.sheet_names:
        norm_sheet = normalize_header(str(sheet_name))
        if any(w in norm_sheet for w in _SKIP_SHEET_WORDS):
            continue
        names.append(str(sheet_name))
    return names


def list_mappable_sr_sheets(file_content: bytes, filename: str) -> list[str]:
    """Return Excel sheet names that have a valid auto-detected column mapping.

    Sheets whose names match ``_SKIP_SHEET_WORDS`` (summary/total/…) are excluded.
    CSV / non-Excel inputs return an empty list.
    """
    ext = ""
    dot_idx = filename.rfind(".")
    if dot_idx != -1:
        ext = filename[dot_idx:].lower()
    if ext not in (".xlsx", ".xls"):
        return []
    try:
        xl = pd.ExcelFile(io.BytesIO(file_content))
    except Exception:
        return []
    names: list[str] = []
    for sheet_name in xl.sheet_names:
        norm_sheet = normalize_header(str(sheet_name))
        if any(w in norm_sheet for w in _SKIP_SHEET_WORDS):
            continue
        try:
            # Reuse the open workbook — do not re-parse bytes per sheet.
            raw_df = pd.read_excel(
                xl,
                sheet_name=sheet_name,
                header=None,
                dtype=object,
            )
        except Exception:
            continue
        best_df, best_mapping, _ = _find_best_header_from_raw(raw_df)
        if best_df is not None and best_mapping:
            names.append(str(sheet_name))
    return names


def _process_sr_sheet_rows(
    *,
    df: pd.DataFrame,
    column_mapping: dict[str, str],
    selected_header_row: int,
    filename: str,
    sheet_name: str | None,
) -> dict[str, Any]:
    """Parse one mapped DataFrame into SR records (no cross-sheet dedupe)."""
    records: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []
    total_rows = 0
    skipped_rows = 0
    skip_reasons: dict[str, int] = {}
    sheet_prefix = f"[{sheet_name}] " if sheet_name else ""

    def _bump_skip(reason: str) -> None:
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    def _is_blank_cell(s: str) -> bool:
        stripped = s.strip().lower()
        return not stripped or stripped in ("nan", "none", "nat")

    # Ensure GSTIN column is optional-str before canonicalisation so blank
    # B2C cells never survive as float NaN → literal "NAN".
    df = _coerce_mapped_gstin_column(df, column_mapping)
    df_canon = normalize_dataframe_to_canonical_schema(df, column_mapping)

    for df_idx, row in df_canon.iterrows():
        total_rows += 1
        row_number: int = selected_header_row + int(df_idx) + 2
        orig_row = df.loc[df_idx]

        row_values = [str(v) if v is not None else "" for v in orig_row]
        if is_total_row(row_values):
            skipped_rows += 1
            _bump_skip("total_or_summary_row")
            continue

        if all(_is_blank_cell(cell) for cell in row_values):
            errors.append(f"{sheet_prefix}Row {row_number}: empty row")
            skipped_rows += 1
            _bump_skip("empty_row")
            continue

        row_errors: list[str] = []

        # Tally quirk: party name may be multiline or embed GSTIN.
        recipient_name = _safe_cell(row.get("recipient_name"))
        embedded: str | None = None
        if "recipient_name" in column_mapping:
            party_raw = orig_row.get(column_mapping["recipient_name"])
            if is_multiline_party_name(party_raw) and recipient_name:
                first_line = next(
                    (
                        ln.strip()
                        for ln in str(party_raw).replace("\r", "\n").split("\n")
                        if ln.strip()
                    ),
                    recipient_name,
                )
                party_clean, embedded = extract_gstin_from_party_cell(first_line)
                recipient_name = party_clean or first_line
            else:
                party_clean, embedded = extract_gstin_from_party_cell(
                    party_raw if party_raw is not None else recipient_name
                )
                if party_clean:
                    recipient_name = party_clean

        # --- GSTIN of recipient ---
        gstin_value: str | None = None
        gstin_valid = False
        if "gstin" in column_mapping:
            # _safe_cell treats pandas/numpy NaN and the strings "nan"/"none"
            # as missing — critical because ``is None`` is False for float nan,
            # and ``str(nan).upper()`` would otherwise become "NAN".
            raw_gstin = _safe_cell(row.get("gstin"))
            if raw_gstin is None or _is_absent_gstin_token(raw_gstin):
                # Fall back to GSTIN embedded in party name (Tally quirk).
                if embedded and not _is_absent_gstin_token(embedded):
                    try:
                        gstin_value = normalize_gstin(embedded)
                        gstin_valid = True
                    except NormalizationError:
                        gstin_value = embedded
                        gstin_valid = False
            else:
                try:
                    gstin_value = normalize_gstin(raw_gstin)
                    gstin_valid = True
                except NormalizationError:
                    # Keep a cleaned upper-case form for display / soft match,
                    # but never retain NA-style placeholders as literal GSTINs.
                    cleaned = re.sub(
                        r"[^0-9A-Z]", "", raw_gstin.strip().upper()
                    )
                    gstin_value = cleaned or None
                    gstin_valid = False
                    if gstin_value is not None and _is_absent_gstin_token(
                        gstin_value
                    ):
                        gstin_value = None
        elif embedded and not _is_absent_gstin_token(embedded):
            try:
                gstin_value = normalize_gstin(embedded)
                gstin_valid = True
            except NormalizationError:
                gstin_value = embedded
                gstin_valid = False

        # --- Invoice number ---
        inv_raw: str | None = None
        if "invoice_number" in column_mapping:
            cell = row.get("invoice_number_normalized")
            if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                inv_raw = None
            else:
                inv_raw = str(cell).strip().upper() if str(cell).strip() else None
            if inv_raw is None:
                row_errors.append("missing invoice number")

        # --- Invoice date ---
        date_value: str | None = None
        if "invoice_date" in column_mapping:
            raw_date = _safe_cell(orig_row.get(column_mapping["invoice_date"]))
            if raw_date is not None:
                try:
                    norm_date = normalize_date(raw_date)
                    date_value = norm_date.value.isoformat()
                except NormalizationError:
                    row_errors.append("invalid date")

        # --- Taxable amount ---
        original_taxable: int | None = None
        taxable_amount_paise: int | None = None
        if "taxable_amount" in column_mapping:
            raw_tax = _safe_cell(orig_row.get(column_mapping["taxable_amount"]))
            taxable_amount_paise = _df_cell_int(row.get("taxable_amount_paise"))
            if raw_tax is not None:
                if taxable_amount_paise is None:
                    row_errors.append("invalid value")
                else:
                    original_taxable = taxable_amount_paise

        # --- Place of supply ---
        pos_raw = _safe_cell(row.get("place_of_supply"))
        place_of_supply = _normalize_place_of_supply(pos_raw)

        # --- Explicit invoice type from column ---
        explicit_invoice_type = _safe_cell(row.get("invoice_type"))

        # --- Classify invoice type ---
        invoice_type = _classify_invoice_type(
            inv_raw, original_taxable, gstin_value,
            explicit_invoice_type, place_of_supply,
        )
        row_errors.extend(
            _invoice_type_consistency_errors(invoice_type, original_taxable)
        )

        # Skip rows that have both missing GSTIN and missing invoice number
        if row_errors:
            gstin_missing = (
                "gstin" in column_mapping and gstin_value is None
            )
            inv_missing = "missing invoice number" in row_errors
            if gstin_missing and inv_missing:
                skipped_rows += 1
                _bump_skip("truly_unparseable_row")
            else:
                errors.append(
                    f"{sheet_prefix}Row {row_number}: {', '.join(row_errors)}"
                )
                skipped_rows += 1
                _bump_skip("invalid_row")
                continue

        # --- Tax amounts ---
        igst_paise = _df_cell_int(row.get("igst_paise"))
        cgst_paise = _df_cell_int(row.get("cgst_paise"))
        sgst_paise = _df_cell_int(row.get("sgst_paise"))
        cess_paise = _df_cell_int(row.get("cess_paise"))
        total_tax_paise = _df_cell_int(row.get("total_tax_paise"))
        if total_tax_paise is None and (
            igst_paise is not None
            or cgst_paise is not None
            or sgst_paise is not None
            or cess_paise is not None
        ):
            total_tax_paise = (
                (igst_paise or 0)
                + (cgst_paise or 0)
                + (sgst_paise or 0)
                + (cess_paise or 0)
            )
        if invoice_type == "CREDIT_NOTE" and total_tax_paise is not None and total_tax_paise > 0:
            total_tax_paise = -total_tax_paise

        # --- Reverse charge ---
        _rcell = row.get("reverse_charge")
        if _rcell is None or (isinstance(_rcell, float) and pd.isna(_rcell)):
            reverse_out: bool | None = None
        else:
            reverse_out = _rcell  # type: ignore[assignment]

        # --- Build output record ---
        out: dict[str, Any] = {
            "row_number": row_number,
            "invoice_number_normalized": inv_raw,
            "invoice_number": inv_raw,
            "document_type": invoice_type,
            "invoice_type": invoice_type,
            "invoice_date": date_value,
            "gstin": gstin_value,
            "gstin_valid": gstin_valid,
            "recipient_name": recipient_name,
            "taxable_amount_paise": taxable_amount_paise,
            "igst_paise": igst_paise,
            "cgst_paise": cgst_paise,
            "sgst_paise": sgst_paise,
            "cess_paise": cess_paise,
            "total_tax_paise": total_tax_paise,
            "total_amount_paise": _df_cell_int(row.get("total_amount_paise")),
            "place_of_supply": place_of_supply,
            "reverse_charge": reverse_out,
            "source_file": filename,
        }
        if sheet_name:
            out["source_sheet"] = sheet_name
        if "hsn" in column_mapping:
            _hsn = row.get("hsn")
            if _hsn is not None and not (isinstance(_hsn, float) and pd.isna(_hsn)):
                out["hsn"] = str(_hsn).strip()
        # Export-specific fields
        if "shipping_port_code" in column_mapping:
            _spc = _safe_cell(row.get("shipping_port_code"))
            if _spc is not None:
                out["shipping_port_code"] = _spc
        if "shipping_bill_number" in column_mapping:
            _sbn = _safe_cell(row.get("shipping_bill_number"))
            if _sbn is not None:
                out["shipping_bill_number"] = _sbn
        if "shipping_bill_date" in column_mapping:
            _sbd = _safe_cell(row.get("shipping_bill_date"))
            if _sbd is not None:
                out["shipping_bill_date"] = _sbd
        if "export_type" in column_mapping:
            _et = _safe_cell(row.get("export_type"))
            if _et is not None:
                out["export_type"] = _et

        records.append(out)

    return {
        "records": records,
        "errors": errors,
        "warnings": warnings,
        "total_rows": total_rows,
        "skipped_rows": skipped_rows,
        "skip_reasons": skip_reasons,
        "df_canon": df_canon,
    }


def parse_sales_register(file_content: bytes, filename: str) -> dict:
    """Parse a sales-register file and return a structured result dict.

    Multi-sheet Excel workbooks: every non-skipped sheet with a valid column
    mapping is parsed and combined. Sheets used vs skipped are returned in
    ``sheets_used`` / ``sheets_skipped`` and mirrored in ``warnings``.

    Returns::

        {
            "success": bool,
            "total_rows": int,
            "valid_rows": int,
            "records": [...],
            "skipped": int,              # alias for skipped_rows
            "skipped_rows": int,
            "detected_columns": {...},
            "source_software": str,
            "errors": [...],
            "warnings": [...],
            ...
        }
    """
    result: dict[str, Any] = {
        "success": False,
        "total_rows": 0,
        "valid_rows": 0,
        "records": [],
        "errors": [],
        "sheets_used": [],
        "sheets_skipped": [],
        "missing_invoice_number_count": 0,
        "warnings": [],
    }
    if not file_content or not file_content.strip():
        result["errors"].append("Empty file")
        return result

    ext = ""
    dot_idx = filename.rfind(".")
    if dot_idx != -1:
        ext = filename[dot_idx:].lower()

    # Each job: (sheet_name|None, df, column_mapping, header_row, source_cols)
    sheet_jobs: list[tuple[str | None, pd.DataFrame, dict[str, str], int, list]] = []
    sheets_skipped: list[dict[str, Any]] = []

    try:
        if ext in (".xlsx", ".xls"):
            try:
                xl = pd.ExcelFile(io.BytesIO(file_content))
                sheet_names: list[str] = xl.sheet_names
            except Exception as exc:
                raise ParseError(f"Cannot open Excel file: {exc}") from exc

            parse_started = time.perf_counter()
            for sheet_name in sheet_names:
                if (
                    _SR_PARSE_SOFT_TIMEOUT_SEC > 0
                    and (time.perf_counter() - parse_started)
                    > _SR_PARSE_SOFT_TIMEOUT_SEC
                ):
                    raise ParseError(
                        f"Sales register parse exceeded soft timeout "
                        f"({_SR_PARSE_SOFT_TIMEOUT_SEC:.0f}s) after "
                        f"{len(sheet_jobs)} sheet(s). Re-upload a smaller file "
                        f"or raise SR_PARSE_SOFT_TIMEOUT_SEC."
                    )
                norm_sheet = normalize_header(str(sheet_name))
                if any(w in norm_sheet for w in _SKIP_SHEET_WORDS):
                    logger.info(
                        "Skipping sheet '%s' (matched skip-word).", sheet_name
                    )
                    sheets_skipped.append(
                        {
                            "sheet": str(sheet_name),
                            "reason": "skip_word",
                            "detail": "name matched summary/total/instruction/readme",
                        }
                    )
                    continue

                sheet_t0 = time.perf_counter()
                try:
                    # Reuse open workbook handle — re-parsing BytesIO per sheet
                    # re-reads the entire xlsx for every sheet.
                    raw_df = pd.read_excel(
                        xl,
                        sheet_name=sheet_name,
                        header=None,
                        dtype=object,
                    )
                except Exception as exc:
                    sheets_skipped.append(
                        {
                            "sheet": str(sheet_name),
                            "reason": "read_error",
                            "detail": str(exc),
                        }
                    )
                    continue

                best_df, best_mapping, best_header_row = _find_best_header_from_raw(
                    raw_df
                )
                sheet_elapsed = time.perf_counter() - sheet_t0
                if best_df is not None and best_mapping:
                    sheet_jobs.append(
                        (
                            str(sheet_name),
                            best_df,
                            best_mapping,
                            best_header_row,
                            list(best_df.columns),
                        )
                    )
                    logger.info(
                        "SR sheet '%s' accepted (header_row=%s, mapped=%s, "
                        "rows=%d, elapsed=%.2fs)",
                        sheet_name,
                        best_header_row,
                        sorted(best_mapping.keys()),
                        len(best_df),
                        sheet_elapsed,
                    )
                else:
                    sheets_skipped.append(
                        {
                            "sheet": str(sheet_name),
                            "reason": "no_column_mapping",
                            "detail": "could not detect required sales-register columns",
                        }
                    )
                    logger.info(
                        "SR sheet '%s' skipped (no mapping, elapsed=%.2fs)",
                        sheet_name,
                        sheet_elapsed,
                    )

            if not sheet_jobs:
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

                try:
                    raw_df = pd.read_csv(
                        io.StringIO(raw_text),
                        header=None,
                        dtype=str,
                    )
                except Exception:
                    continue

                best_df, best_mapping, best_header_row = _find_best_header_from_raw(
                    raw_df
                )
                if best_df is not None and best_mapping:
                    sheet_jobs.append(
                        (
                            None,
                            best_df,
                            best_mapping,
                            best_header_row,
                            list(best_df.columns),
                        )
                    )
                    found = True
                    break

            if not found:
                raise ParseError(
                    "Could not find a valid column mapping in the CSV file"
                )

        else:
            raise ParseError(f"Unsupported file extension: '{ext}'")

    except ParseError as exc:
        result["errors"].append(str(exc))
        result["sheets_skipped"] = sheets_skipped
        return result
    except Exception as exc:
        result["errors"].append(f"read_file: {exc}")
        result["sheets_skipped"] = sheets_skipped
        return result

    records: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []
    total_rows = 0
    skipped_rows = 0
    skip_reasons: dict[str, int] = {}
    sheets_used: list[dict[str, Any]] = []
    source_software = "Excel/Unknown"
    column_mapping: dict[str, str] = {}
    unmapped_columns: list[str] = []
    df_canon_parts: list[pd.DataFrame] = []
    header_detected = True
    missing_invoice_number_count = 0

    try:
        row_phase_started = time.perf_counter()
        for sheet_name, df, mapping, header_row, source_cols in sheet_jobs:
            if (
                _SR_PARSE_SOFT_TIMEOUT_SEC > 0
                and (time.perf_counter() - row_phase_started)
                > _SR_PARSE_SOFT_TIMEOUT_SEC
            ):
                raise ParseError(
                    f"Sales register row processing exceeded soft timeout "
                    f"({_SR_PARSE_SOFT_TIMEOUT_SEC:.0f}s) after "
                    f"{len(records)} record(s). Re-upload a smaller file "
                    f"or raise SR_PARSE_SOFT_TIMEOUT_SEC."
                )
            try:
                source_software = detect_source_software(source_cols) or source_software
                mapped_originals: set[str] = set(mapping.values())
                sheet_unmapped = [c for c in source_cols if c not in mapped_originals]
            except Exception as exc:
                errors.append(f"column_mapping ({sheet_name or 'csv'}): {exc}")
                continue

            # Prefer the richest mapping for top-level detected_columns.
            if len(mapping) >= len(column_mapping):
                column_mapping = mapping
                unmapped_columns = sheet_unmapped

            if "invoice_number" not in mapping:
                sheet_label = sheet_name or "(csv)"
                warnings.append(
                    f"[{sheet_label}] No invoice number column detected "
                    f"(expected headers like Invoice Number / Bill No / Vch No.). "
                    f"Rows from this sheet will be skipped during matching."
                )

            part = _process_sr_sheet_rows(
                df=df,
                column_mapping=mapping,
                selected_header_row=header_row,
                filename=filename,
                sheet_name=sheet_name,
            )
            sheet_rec_count = len(part["records"])
            sheets_used.append(
                {
                    "sheet": sheet_name or "(csv)",
                    "records": sheet_rec_count,
                    "total_rows": part["total_rows"],
                    "mapped_fields": sorted(mapping.keys()),
                    "has_invoice_number": "invoice_number" in mapping,
                }
            )
            records.extend(part["records"])
            errors.extend(part["errors"])
            warnings.extend(part["warnings"])
            total_rows += part["total_rows"]
            skipped_rows += part["skipped_rows"]
            for reason, n in part["skip_reasons"].items():
                skip_reasons[reason] = skip_reasons.get(reason, 0) + n
            if part.get("df_canon") is not None and not part["df_canon"].empty:
                df_canon_parts.append(part["df_canon"])

        if len(sheets_used) > 1:
            used_names = ", ".join(
                f"{s['sheet']} ({s['records']})" for s in sheets_used
            )
            warnings.append(
                f"Combined {len(sheets_used)} sheets into one sales register: "
                f"{used_names}. If sheets overlap, invoices may be double-counted."
            )
            logger.warning("SR multi-sheet combine: %s", used_names)
        if sheets_skipped:
            skipped_names = ", ".join(
                f"{s['sheet']} ({s['reason']})" for s in sheets_skipped
            )
            warnings.append(f"Sheets skipped: {skipped_names}.")

        # Cross-sheet duplicate detection (keep all rows; flag for review).
        seen_keys: dict[tuple, dict] = {}
        clean: list[dict] = []
        for rec in records:
            key = (rec.get("gstin"), rec.get("invoice_number_normalized"))
            if key[0] is None or key[1] is None:
                clean.append(rec)
                continue
            if key not in seen_keys:
                seen_keys[key] = rec
                clean.append(rec)
            else:
                first = seen_keys[key]
                sheet_bit = (
                    f" sheet '{rec.get('source_sheet')}'"
                    if rec.get("source_sheet")
                    else ""
                )
                if rec.get("taxable_amount_paise") != first.get("taxable_amount_paise"):
                    errors.append(
                        f"Row {rec['row_number']}{sheet_bit}: conflicting duplicate invoice "
                        f"'{rec['invoice_number_normalized']}' for GSTIN '{rec['gstin']}' "
                        f"(first seen at row {first['row_number']}; kept for reconciliation)"
                    )
                else:
                    errors.append(
                        f"Row {rec['row_number']}{sheet_bit}: duplicate invoice "
                        f"'{rec['invoice_number_normalized']}' for GSTIN '{rec['gstin']}' "
                        f"(first seen at row {first['row_number']}; kept for reconciliation)"
                    )
                clean.append(rec)
        records = clean

        missing_invoice = [
            rec
            for rec in records
            if not (
                rec.get("invoice_number")
                or rec.get("invoice_number_normalized")
            )
        ]
        missing_invoice_number_count = len(missing_invoice)
        if missing_invoice_number_count:
            by_sheet: dict[str, int] = {}
            for rec in missing_invoice:
                sheet = str(rec.get("source_sheet") or "(csv)")
                by_sheet[sheet] = by_sheet.get(sheet, 0) + 1
            sheet_bits = ", ".join(
                f"{name} ({n})" for name, n in sorted(by_sheet.items())
            )
            warnings.append(
                f"{missing_invoice_number_count} sales register row(s) "
                f"missing invoice number after parsing — will be skipped "
                f"during matching. By sheet: {sheet_bits}."
            )
            logger.warning(
                "SR missing invoice_number: count=%d by_sheet=%s file=%s",
                missing_invoice_number_count,
                by_sheet,
                filename,
            )

    except Exception as exc:
        result["errors"].append(f"row_processing: {exc}")
        result["sheets_used"] = sheets_used
        result["sheets_skipped"] = sheets_skipped
        result["missing_invoice_number_count"] = missing_invoice_number_count
        return result

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
    result["skipped"] = skipped_rows
    result["skipped_rows"] = skipped_rows
    result["skip_reasons"] = skip_reasons
    result["detected_columns"] = column_mapping
    result["unmapped_columns"] = unmapped_columns
    if source_software == "Tally" or looks_like_tally_headers(
        list(column_mapping.values()) if column_mapping else []
    ):
        result["export_profile"] = "Tally Export"
        for issue in validate_tally_export(
            register_type="sales",
            headers=list(column_mapping.values()) if column_mapping else [],
            is_tally_export=True,
        ):
            msg = f"[Tally Export] {issue['message']}"
            if msg not in warnings:
                warnings.append(msg)
    result["warnings"] = warnings
    result["sheets_used"] = sheets_used
    result["sheets_skipped"] = sheets_skipped
    result["missing_invoice_number_count"] = missing_invoice_number_count
    if df_canon_parts:
        result["normalized_columns"] = list(df_canon_parts[0].columns)
        try:
            result["normalized_dataframe"] = pd.concat(
                df_canon_parts, ignore_index=True
            )
        except Exception:
            result["normalized_dataframe"] = df_canon_parts[0]
    else:
        result["normalized_columns"] = []
        result["normalized_dataframe"] = pd.DataFrame()
    return result


def parse_sales_register_dataframe(
    file_content: bytes, filename: str
) -> pd.DataFrame:
    """Parse a sales register and return the canonical DataFrame directly.

    Columns match GSTR-1 reconciliation expectations:
    ``gstin`` (upper), ``invoice_number_normalized`` (str, upper),
    ``invoice_date`` (str), ``taxable_amount_paise`` / ``cgst_paise`` /
    ``sgst_paise`` / ``igst_paise`` / ``total_tax_paise`` /
    ``total_amount_paise`` (ints), ``recipient_name``, ``place_of_supply``,
    ``invoice_type``.

    Raises ParseError on failure (the dict returned by ``parse_sales_register``
    is not used here).
    """
    res = parse_sales_register(file_content, filename)
    if not res.get("success"):
        raise ParseError("; ".join(res.get("errors") or ["parse failed"]))
    df_out = res.get("normalized_dataframe")
    if df_out is None:
        raise ParseError("no normalized dataframe produced")
    return df_out


if __name__ == "__main__":
    for key in ("recipient_name", "total_tax", "total_amount", "invoice_type"):
        print(f"COLUMN_ALIASES[{key!r}]:")
        print(COLUMN_ALIASES[key])
        print()

    mock_headers = [
        "Recipient GSTIN",
        "Recipient Name",
        "Invoice Number",
        "Invoice Date",
        "Taxable Value",
        "IGST",
        "CGST",
        "SGST",
        "Total Invoice Value",
        "Place of Supply",
        "Invoice Type",
    ]
    df = pd.DataFrame(columns=mock_headers)
    mapping = detect_column_mapping(df)
    print("detect_column_mapping(mock headers):")
    for std, col in mapping.items():
        print(f"  {std}: {col!r}")

    assert mapping.get("recipient_name") == "Recipient Name", mapping
    total_col = mapping.get("total_amount") or mapping.get("total_tax")
    assert total_col == "Total Invoice Value", mapping
    assert mapping.get("taxable_amount") == "Taxable Value", mapping
    assert mapping.get("gstin") == "Recipient GSTIN", mapping
    assert mapping.get("place_of_supply") == "Place of Supply", mapping
    assert mapping.get("invoice_type") == "Invoice Type", mapping
    print("\nAll assertions passed.")
