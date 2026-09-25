"""Purchase Register parser — parses .xlsx / .xls / .csv purchase registers
into a normalised list of invoice records.

After reading a sheet into a DataFrame, columns are mapped to a canonical schema
(``gstin``, ``invoice_number_normalized``, ``invoice_date``, ``*_paise``, …)
aligned with ``app.services.sanity`` expectations.

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
    is_urp_gstin,
    URP_NORMALIZED,
    normalize_amount as normalize_amount_to_paise,
    normalize_date,
    normalize_gstin,
)
from app.services.matcher import normalize_invoice
from app.parsers.tally_register import (
    TALLY_PURCHASE_ALIASES,
    detect_source_software_tally,
    extract_gstin_from_party_cell,
    is_multiline_party_name,
    looks_like_tally_headers,
    merge_aliases,
    validate_tally_export,
)

logger = logging.getLogger(__name__)

# Soft ceiling for multi-sheet PR parse wall-clock. Exceeding raises ParseError
# so the worker fails the import with a clear message instead of hanging forever.
# Override with env PR_PARSE_SOFT_TIMEOUT_SEC (0 disables).
_PR_PARSE_SOFT_TIMEOUT_SEC = float(os.environ.get("PR_PARSE_SOFT_TIMEOUT_SEC", "120"))


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
    "cess": "cess_paise",
    "total_tax": "total_tax_paise",
    "total_amount": "total_amount_paise",
    "supplier_name": "supplier_name",
    "place_of_supply": "place_of_supply",
    "reverse_charge": "reverse_charge",
    "payment_status": "payment_status",
    "payment_date": "payment_date",
    "amount_paid": "amount_paid_paise",
    "itc_eligibility": "itc_eligibility",
    "hsn": "hsn",
    # Credit/debit note sheets (quarantined from invoice matching).
    "note_number": "note_number",
    "note_amount": "note_amount_paise",
    "note_type": "note_type",
    "note_reason": "note_reason",
    "original_invoice_number": "original_invoice_number",
}

_BASE_COLUMN_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "gstin", "supplier gstin", "party gstin", "vendor gstin", "gst no",
        "gstn", "gst number", "vendor gst", "party gst no", "buyer gst",
        "gstin uin", "gstin of supplier", "gstin of the supplier",
        "gstin uin of supplier", "supplier gstin uin", "party s gstin",
        "party gstin uin", "supplier gstin number", "supplier gst no",
        "party gst in", "supplier gst in",
        "party tin", "tin", "vendor gst no", "vendor gstin no",
        "party gst number", "supplier gst", "cparty gstin", "counter party gstin",
        "tax id", "gst identification no", "gst identification number",
        "party gstin / uin", "supplier gstin / uin", "tin / gstin", "gst / tin",
        "vat / gst no", "party's gstin/uin", "party gstin/uin", "gstin / uin of supplier",
    ],
    "invoice_number": [
        "invoice no", "invoice number", "inv no", "bill no",
        "bill number", "voucher no", "voucher number", "vch no",
        "vch number", "vch no.", "invoice #", "tax invoice no",
        "ref no", "doc no",
        "inv num", "invoice num", "inv #", "bill num", "voucher num",
        "vch num", "document no", "document number", "doc num", "doc number",
        "doc #", "reference no", "reference number", "ref num", "ref #",
        "bill ref no", "bill / ref no", "purchase invoice no", "purchase inv no",
        "purchase no", "bill / inv no", "bill/inv no", "vch no / inv no",
        "vch no / bill no", "txn no", "transaction no", "transaction number",
        "inv id", "invoice id",
    ],
    "invoice_date": [
        "invoice date", "bill date", "bill dt", "date", "voucher date", "doc date",
        "inv date", "inv dt", "invoice dt", "document date", "posting date",
        "entry date", "voucher dt", "bill dt.", "invoice date / bill date",
        "bill date / invoice date", "date of invoice", "tx date", "transaction date",
    ],
    "taxable_amount": [
        "taxable value", "taxable amount", "base amount", "taxable",
        "assessable value", "value", "net amount",
        "amount", "invoice value", "total amount",
        "taxable amt", "taxable amt.", "taxable val", "taxable turnover",
        "assessable amt", "assessable amt.", "assessable val", "assessable value rs",
        "assessable value (rs.)", "taxable value rs", "taxable value (rs.)",
        "taxable value (rs)", "net taxable amount", "taxable goods value",
        "basic amount", "basic amt", "basic value", "net purchase",
        "purchase amount", "purchase value", "taxable amt rs", "taxable amt (rs)",
    ],
    "igst": [
        "igst", "integrated tax", "igst amount", "igst tax", "i.g.s.t", "igst paid",
        "igst amt", "igst amt.", "integrated gst", "igst tax amount",
        "integrated tax amount", "igst (rs)", "igst (rs.)", "igst amt (rs)",
    ],
    "cgst": [
        "cgst", "central tax", "cgst amount", "cgst tax", "c.g.s.t",
        "cgst amt", "cgst amt.", "central gst", "cgst tax amount",
        "central tax amount", "cgst (rs)", "cgst (rs.)", "cgst amt (rs)",
    ],
    "sgst": [
        "sgst", "state tax", "sgst amount", "sgst tax", "utgst", "s.g.s.t", "u.t.g.s.t",
        "state ut tax", "state/ut tax", "state / ut tax", "state ut tax amount",
        "state/ut tax amount", "ut tax", "state tax amount", "sgst/utgst",
        "sgst / utgst", "sgst utgst", "state gst", "utgst amt", "sgst amt",
        "sgst amt.", "utgst amt.", "state gst amt", "state/utgst",
        "sgst / ut tax", "sgst / ut tax amount", "sgst (rs)", "sgst (rs.)", "sgst amt (rs)",
    ],
    "cess": [
        "cess", "cess amount", "gst cess", "compensation cess",
        "cess amt", "cess amt.", "compensation cess amt", "compensation cess amount",
        "cess (rs)", "cess (rs.)",
    ],
    "total_tax": [
        "total tax", "gst amount", "tax amount", "total gst",
        "tax amt", "tax amt.", "total tax amt", "total tax amt.",
        "total tax amount", "total gst amount", "total gst amt",
        "gst amt", "gst amt.", "total tax rs", "total gst rs",
    ],
    "total_amount": [
        "total invoice value", "total value", "invoice value", "invoice amount",
        "total amount", "gross amount", "gross value", "bill amount", "bill value",
        "net amount", "net value", "total", "grand total",
        "inv total", "invoice total", "bill total", "bill amt", "bill amt.",
        "gross amt", "gross amt.", "invoice gross amount", "invoice net amount",
        "invoice total amount", "total amt", "total amt.", "total inv value",
        "total bill amount", "net bill amount", "final amount", "payable amount",
    ],
    "supplier_name": [
        "supplier name", "supplier", "vendor name", "vendor", "party name",
        "party", "ledger name", "ledger", "seller name", "seller",
        "creditor name", "creditor", "from", "name",
        "trade/legal name", "trade legal name", "legal name", "trade name",
        "trade/legal name of supplier", "trade legal name of supplier",
        "supplier trade name", "supplier legal name",
        "party's name", "party s name", "party's a/c name", "party s a c name",
        "party a/c name", "party ac name", "party account name", "account name",
        "particulars", "vendor / supplier name", "supplier / vendor name",
        "creditor's name", "seller's name", "party legal name", "company name",
    ],
    "place_of_supply": [
        "place of supply", "pos", "state",
        "place of delivery", "supply state", "pos state", "destination state", "state code",
    ],
    "reverse_charge": [
        "reverse charge", "rcm", "reverse charge applicable",
        "reverse charge flag", "is reverse charge", "rcm applicable", "reverse charge yn", "rev charge",
    ],
    "payment_status": [
        "payment status", "paid status", "paid/unpaid", "payment flag",
        "supplier payment status", "vendor payment status",
    ],
    "payment_date": [
        "payment date", "paid date", "date of payment", "payment dt",
        "supplier payment date", "vendor payment date",
    ],
    "amount_paid": [
        "amount paid", "paid amount", "payment amount", "amount remitted",
        "supplier payment amount",
    ],
    "itc_eligibility": [
        "itc eligible", "itc eligibility", "is itc eligible", "eligible for itc",
        "itc status", "eligible",
        "itc claimed", "itc claim", "itc availed", "itc availed yn",
        "itc availability", "itc available", "itc available yn", "itc avl", "itcavl",
    ],
    "hsn": [
        "hsn", "hsn code", "hsn/sac", "sac", "sac code", "hsn code/sac code",
    ],
    # Distinct from Invoice No / Voucher No / Bill No — note sheets only.
    "note_number": [
        "note no", "note number", "note #", "note num",
        "credit note no", "credit note number", "debit note no",
        "debit note number", "cn no", "dn no", "cdn no",
    ],
    "note_amount": [
        "note amount", "note value", "cdn amount",
    ],
    "note_type": [
        "note type", "cn dn", "cndn",
        "voucher type", "vch type", "document type", "doc type",
        "transaction type", "trans type", "type",
    ],
    "note_reason": [
        "reason", "note reason", "remarks", "remark",
    ],
    "original_invoice_number": [
        "original invoice no", "original invoice number", "original invoice",
        "original inv no", "original inv number", "against invoice number",
        "against invoice no", "against inv no", "against inv number",
        "orig inv no", "orig inv num", "oinum", "ont num", "ointnum",
    ],
}

# Includes the named "Tally Export" alias profile (Party's A/c Name, Vch No., …).
COLUMN_ALIASES: dict[str, list[str]] = merge_aliases(
    _BASE_COLUMN_ALIASES, TALLY_PURCHASE_ALIASES
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
    ``(Mandatory)``, ``(Rs.)``, or ``of Supplier`` after the core alias text.
    """
    if alias_norm == "state" and col_norm.startswith(("state tax", "state ut", "state gst", "state / ut", "state cess")):
        return False
    return col_norm == alias_norm or col_norm.startswith(alias_norm + " ")


def _alias_match_quality(col_norm: str, alias_norm: str) -> tuple[int, int] | None:
    """Score how well *alias_norm* matches *col_norm*.

    Returns ``(tier, alias_length)`` where tier ``2`` is an exact header match and
    tier ``1`` is a prefix match (alias plus trailing descriptor words).
    ``None`` when there is no match.
    """
    if alias_norm == "state" and col_norm.startswith(("state tax", "state ut", "state gst", "state / ut", "state cess")):
        return None
    if col_norm == alias_norm:
        return (2, len(alias_norm))
    if col_norm.startswith(alias_norm + " "):
        return (1, len(alias_norm))
    return None


# When two standard fields share the same alias (e.g. ``"total amount"`` appears in
# both ``taxable_amount`` and ``total_amount``), break ties in favour of the field
# that owns that concept in purchase-register exports.
_FIELD_MATCH_PRIORITY: dict[str, int] = {
    "supplier_name": 50,
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
    "reverse_charge": 50,
    "payment_status": 50,
    "payment_date": 50,
    "amount_paid": 45,
    "hsn": 45,
    "note_number": 55,
    "note_amount": 45,
    "note_type": 50,
    "note_reason": 30,
    "original_invoice_number": 35,
}

# Sheet / header signals that a PR sheet is credit/debit notes, not invoices.
_NOTE_SHEET_NAME_RE = re.compile(
    r"credit\s*notes?|debit\s*notes?|\bcdn\b",
    re.IGNORECASE,
)
_NOTE_NUMBER_HEADER_RE = re.compile(
    r"^(note\s*no|note\s*number|credit\s*note\s*no|credit\s*note\s*number|"
    r"debit\s*note\s*no|debit\s*note\s*number|cn\s*no|dn\s*no|cdn\s*no)"
    r"(\s|$)",
    re.IGNORECASE,
)
_NOTE_TYPE_HEADER_RE = re.compile(
    r"^(note\s*type|cn\s*dn|cndn)(\s|$)",
    re.IGNORECASE,
)

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


_GSTIN_FORMAT_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _is_valid_gstin_str(val: Any) -> bool:
    if not val or not isinstance(val, str):
        return False
    s = val.strip().upper()
    if len(s) != 15:
        return False
    return bool(_GSTIN_FORMAT_RE.match(s))


def refine_gstin_column_mapping(
    df: pd.DataFrame,
    mapping: dict[str, str],
    client_gstin: str | None = None,
) -> dict[str, str]:
    """Refine column mapping for GSTIN if the mapped column is inverted or mislabeled.

    Detects if the column mapped to 'gstin' is monochromatic (e.g. 1 unique GSTIN
    across all rows) or matches the client's own registered GSTIN, while another
    column in the DataFrame (e.g. customer_gstin, counterparty_gstin, party_gstin)
    contains multiple unique valid GSTINs. In such cases, remaps 'gstin' to the
    true supplier GSTIN column.
    """
    if "gstin" not in mapping or df is None or len(df) == 0:
        if "gstin" not in mapping and df is not None and len(df) > 0:
            norm_client = client_gstin.strip().upper() if client_gstin else None
            for col in df.columns:
                vals = df[col].dropna().astype(str).str.strip().str.upper()
                clean_vals = [v for v in vals if v and v not in ("NAN", "NONE", "NAT")]
                if not clean_vals:
                    continue
                valid_gstins = [v for v in clean_vals if _is_valid_gstin_str(v)]
                if valid_gstins and (len(valid_gstins) / len(clean_vals) >= 0.5):
                    if norm_client and len(set(valid_gstins)) == 1 and norm_client in valid_gstins:
                        continue
                    new_mapping = dict(mapping)
                    new_mapping["gstin"] = col
                    return new_mapping
        return mapping

    current_col = mapping["gstin"]
    if current_col not in df.columns:
        return mapping

    current_series = df[current_col].dropna().astype(str).str.strip().str.upper()
    current_vals = [v for v in current_series if v and v not in ("NAN", "NONE", "NAT")]
    if not current_vals:
        return mapping

    current_unique = set(current_vals)
    norm_client = client_gstin.strip().upper() if client_gstin else None

    is_client_match = (
        norm_client is not None
        and (sum(1 for v in current_vals if v == norm_client) / len(current_vals) >= 0.9)
    )
    is_monochromatic = len(current_unique) == 1

    if not is_client_match and not is_monochromatic:
        return mapping

    best_candidate: str | None = None
    best_unique_count = 0

    _COUNTERPARTY_HINTS = (
        "customer", "counterparty", "party", "vendor", "ctin", "buyer", "supplier"
    )

    for col in df.columns:
        if col == current_col:
            continue

        col_norm = normalize_header(str(col))
        vals = df[col].dropna().astype(str).str.strip().str.upper()
        clean_vals = [v for v in vals if v and v not in ("NAN", "NONE", "NAT")]
        if not clean_vals:
            continue

        valid_gstins = [v for v in clean_vals if _is_valid_gstin_str(v)]
        if not valid_gstins:
            continue

        unique_valid = set(valid_gstins)
        if norm_client and len(unique_valid) == 1 and norm_client in unique_valid:
            continue

        if len(unique_valid) > len(current_unique) or (
            is_client_match and len(valid_gstins) / len(clean_vals) >= 0.5
        ):
            score = len(unique_valid)
            if any(hint in col_norm for hint in _COUNTERPARTY_HINTS):
                score += 1000
            if score > best_unique_count:
                best_candidate = col
                best_unique_count = score

    if best_candidate is not None:
        logger.warning(
            "PR column refinement: remapping 'gstin' from '%s' to '%s' "
            "(detected %d unique valid vendor GSTINs vs %d in current column).",
            current_col,
            best_candidate,
            best_unique_count if best_unique_count < 1000 else best_unique_count - 1000,
            len(current_unique),
        )
        new_mapping = dict(mapping)
        new_mapping["gstin"] = best_candidate
        return new_mapping

    return mapping


def _find_best_header_from_raw(
    raw_df: pd.DataFrame, max_rows: int = 20, client_gstin: str | None = None
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
        body = _slice_body(best_header_row, best_headers)
        best_mapping = refine_gstin_column_mapping(body, best_mapping, client_gstin=client_gstin)
        return (
            body,
            best_mapping,
            best_header_row,
        )
    if fallback_mapping is not None and fallback_headers is not None:
        body = _slice_body(0, fallback_headers)
        fallback_mapping = refine_gstin_column_mapping(body, fallback_mapping, client_gstin=client_gstin)
        return body, fallback_mapping, 0

    return None, None, -1


def _invoice_col_specificity(col: str) -> int:
    """Prefer supplier invoice/bill/ref columns over internal voucher numbers."""
    norm = normalize_header(col)
    if any(k in norm for k in ("supplier inv", "supplier invoice", "original inv", "bill no", "ref no", "reference no")):
        return 20
    if any(k in norm for k in ("inv no", "invoice no", "invoice number", "tax invoice")):
        return 10
    if any(k in norm for k in ("vch no", "voucher no", "vch number", "voucher number")):
        return 1
    return 5


def extract_column_sample_values(df: pd.DataFrame, max_samples: int = 3) -> dict[str, list[str]]:
    """Return up to max_samples non-empty string values for each column in df."""
    if df is None or len(df.columns) == 0:
        return {}
    samples: dict[str, list[str]] = {}
    for col in df.columns:
        col_str = str(col).strip()
        vals: list[str] = []
        try:
            for val in df[col].dropna():
                s = str(val).strip()
                if s and s.lower() not in ("nan", "none", "nat") and s not in vals:
                    vals.append(s)
                    if len(vals) >= max_samples:
                        break
        except Exception:
            pass
        samples[col_str] = vals
    return samples


def detect_column_mapping(df: pd.DataFrame, client_gstin: str | None = None) -> dict[str, str]:
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
            spec_cur = _invoice_col_specificity(orig_col) if std_name == "invoice_number" else 0
            spec_prev = _invoice_col_specificity(prev[3]) if std_name == "invoice_number" else 0
            current = (spec_cur, tier, alias_len, priority)
            previous = (spec_prev, prev[0], prev[1], prev[2])
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

    if len(df) > 0:
        mapping = refine_gstin_column_mapping(df, mapping, client_gstin=client_gstin)

    if (
        "gstin" not in mapping
        and "invoice_number" not in mapping
        and "note_number" not in mapping
    ):
        raise ParseError(
            "Cannot identify GSTIN, invoice number, or note number columns"
        )

    return mapping


def is_note_sheet_name(sheet_name: str | None) -> bool:
    """True when the Excel sheet name looks like a credit/debit notes tab."""
    if not sheet_name:
        return False
    return bool(_NOTE_SHEET_NAME_RE.search(str(sheet_name)))


def headers_indicate_notes(columns: list[Any]) -> bool:
    """True when headers include Note No / Note Type (not Invoice/Bill/Voucher No)."""
    for col in columns:
        col_norm = normalize_header(str(col))
        if not col_norm:
            continue
        if _NOTE_NUMBER_HEADER_RE.match(col_norm) or _NOTE_TYPE_HEADER_RE.match(
            col_norm
        ):
            return True
        # Alias-backed note_number / note_type also count.
        for alias in COLUMN_ALIASES.get("note_number", []):
            if _alias_matches(col_norm, normalize_header(alias)):
                return True
        for alias in ("note type", "cn dn", "cndn", "credit debit note", "cr dr note"):
            if _alias_matches(col_norm, normalize_header(alias)):
                return True
    return False


def infer_note_document_type(
    *,
    sheet_name: str | None = None,
    note_type_value: str | None = None,
    column_headers: list[Any] | None = None,
) -> str:
    """Return CREDIT_NOTE or DEBIT_NOTE; default DEBIT_NOTE (common purchase-side case)."""
    blobs: list[str] = []
    if sheet_name:
        blobs.append(str(sheet_name))
    if note_type_value:
        blobs.append(str(note_type_value))
    if column_headers:
        blobs.extend(str(c) for c in column_headers)
    joined = " ".join(blobs).lower()
    if re.search(r"credit|\bcn\b", joined) and not re.search(
        r"debit|\bdn\b", joined
    ):
        return "CREDIT_NOTE"
    if re.search(r"debit|\bdn\b", joined):
        return "DEBIT_NOTE"
    if re.search(r"credit|\bcn\b", joined):
        return "CREDIT_NOTE"
    return "DEBIT_NOTE"


def apply_note_mode_column_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """Remap bare Amount → note_amount when a sheet is in note quarantine mode.

    Note files often have a single ``Amount`` column (no CGST/SGST/IGST). On
    invoice sheets that alias maps to ``taxable_amount``; for notes we want
    ``note_amount`` instead so tax/ITC fields stay empty rather than forced ₹0.
    """
    out = dict(mapping)
    if "note_amount" not in out and "taxable_amount" in out:
        out["note_amount"] = out.pop("taxable_amount")
    if "note_amount" not in out and "total_amount" in out:
        out["note_amount"] = out.pop("total_amount")
    return out


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
    # Strip invisible unicode chars (non-breaking spaces, zero-width spaces, BOM)
    s = (
        s.replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\u200e", "")
        .replace("\ufeff", "")
        .strip()
    )
    # Excel formula error codes
    if s.upper() in (
        "#N/A",
        "#REF!",
        "#VALUE!",
        "#DIV/0!",
        "#NAME?",
        "#NUM!",
        "#NULL!",
        "NULL",
    ):
        return None
    return s or None


_NUMERIC_REMAINDER_RE = re.compile(r"^[\d,. ]+$")

_TOTAL_KEYWORDS: tuple[str, ...] = (
    "grand total",
    "sub total",
    "subtotal",
    "total",
    "sum",
    "closing balance",
    "opening balance",
    "carried over",
    "carried forward",
    "brought forward",
    "balance c/f",
    "balance b/f",
    "page total",
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


def _normalize_payment_status(val: Any) -> str | None:
    """Return ``paid`` / ``unpaid`` / ``partial``, or None when blank/unknown."""
    s = _safe_cell(val)
    if s is None:
        return None
    low = s.lower().strip()
    if low in {"paid", "yes", "y", "p", "1", "true", "received", "cleared"}:
        return "paid"
    if low in {"unpaid", "no", "n", "0", "false", "pending", "outstanding", "due"}:
        return "unpaid"
    if low in {"partial", "part", "partly paid", "partially paid"} or "partial" in low:
        return "partial"
    if low.startswith("paid"):
        return "paid"
    if low.startswith("unpaid"):
        return "unpaid"
    return None


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


def _normalize_gstin_cell(val: Any) -> str | None:
    s = _safe_cell(val)
    if s is None:
        return None
    raw = s.strip().upper()
    if is_urp_gstin(raw):
        return URP_NORMALIZED
    return raw


def _normalize_invoice_number_cell(val: Any) -> str | None:
    s = _safe_cell(val)
    if s is None:
        return None
    if isinstance(val, (int, float)) and not pd.isna(val):
        if isinstance(val, float) and val == int(val):
            return normalize_invoice(str(int(val)))
        if isinstance(val, int):
            return normalize_invoice(str(val))
    # Strip Excel floating point artifacts (e.g. "12345.0" -> "12345")
    s_clean = re.sub(r"\.0+$", "", s)
    # Convert scientific notation strings (e.g. "1.23E+04" -> "12300")
    if re.fullmatch(r"^\d+(?:\.\d+)?[eE][+-]?\d+$", s_clean):
        try:
            f_val = float(s_clean)
            if f_val == int(f_val):
                s_clean = str(int(f_val))
        except (ValueError, OverflowError):
            pass
    return normalize_invoice(s_clean)


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
    """Build a DataFrame with canonical column names and sanity-aligned values.

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
            out_cols[canon] = ser.map(_normalize_gstin_cell)
        elif canon == "invoice_number_normalized":
            out_cols["invoice_number_raw"] = ser.map(_safe_cell)
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
        elif canon in ("supplier_name", "place_of_supply"):
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "reverse_charge":
            out_cols[canon] = ser.map(_normalize_reverse_charge)
        elif canon == "payment_status":
            out_cols[canon] = ser.map(_normalize_payment_status)
        elif canon == "payment_date":
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "amount_paid_paise":
            out_cols[canon] = ser.map(_amount_int_unsigned)
        elif canon == "itc_eligibility":
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "hsn":
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "note_number":
            out_cols[canon] = ser.map(
                lambda v: (s.upper() if (s := _safe_cell(v)) else None)
            )
        elif canon == "note_amount_paise":
            out_cols[canon] = ser.map(_amount_int_signed)
        elif canon in ("note_type", "note_reason"):
            out_cols[canon] = ser.map(_safe_cell)
        elif canon == "original_invoice_number":
            out_cols[canon] = ser.map(
                lambda v: (s.upper() if (s := _safe_cell(v)) else None)
            )

    if not out_cols:
        return pd.DataFrame(index=df.index)
    return pd.DataFrame(out_cols, index=df.index)


_CREDIT_NOTE_PREFIXES: tuple[str, ...] = ("CREDIT", "CRN", "CN", "CR")
_DEBIT_NOTE_PREFIXES: tuple[str, ...] = ("DEBIT", "DRN", "DN", "DR")


def _classify_invoice_type(
    invoice_number: str | None,
    original_taxable: int | None,
    note_type_hint: str | None = None,
) -> str:
    """Classify document type from invoice number prefix, signed taxable value, or note hint.

    Rules:
    * explicit note_type_hint containing "credit"/"cn"/"return" -> CREDIT_NOTE
    * explicit note_type_hint containing "debit"/"dn" -> DEBIT_NOTE
    * credit note prefix (CN, CRN, CR, CREDIT) OR negative taxable -> CREDIT_NOTE
    * debit note prefix (DN, DRN, DR, DEBIT) -> DEBIT_NOTE
    * else -> INVOICE
    """
    if note_type_hint:
        hint_clean = str(note_type_hint).strip().lower()
        if re.search(r"credit|\bcn\b|return", hint_clean) and not re.search(r"debit|\bdn\b", hint_clean):
            return "CREDIT_NOTE"
        if re.search(r"debit|\bdn\b", hint_clean):
            return "DEBIT_NOTE"

    inv = (invoice_number or "").strip().upper()
    norm_inv = re.sub(r"[^A-Z0-9]", "", inv)
    if any(norm_inv.startswith(p) for p in _CREDIT_NOTE_PREFIXES) or (
        original_taxable is not None and original_taxable < 0
    ):
        return "CREDIT_NOTE"
    if any(norm_inv.startswith(p) for p in _DEBIT_NOTE_PREFIXES):
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
    invoice_type: str, original_taxable: int | None
) -> list[str]:
    """Return row-level error fragments when sign and type disagree.

    Credit notes with positive values and invoices with negative values (auto-promoted)
    are supported and never fatal.
    """
    return []


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def list_candidate_pr_sheet_names(file_content: bytes, filename: str) -> list[str]:
    """Return Excel sheet names excluding skip-word sheets (no header detection).

    Cheap O(sheets) peek used to decide whether to skip single-sheet reshape
    before the full ``parse_purchase_register`` pass.
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


def list_mappable_pr_sheets(file_content: bytes, filename: str) -> list[str]:
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


def _process_pr_sheet_rows(
    *,
    df: pd.DataFrame,
    column_mapping: dict[str, str],
    selected_header_row: int,
    filename: str,
    sheet_name: str | None,
    note_mode: bool = False,
    default_note_type: str = "DEBIT_NOTE",
) -> dict[str, Any]:
    """Parse one mapped DataFrame into PR records (no cross-sheet dedupe).

    When *note_mode* is True the sheet is treated as credit/debit notes: rows
    get ``document_type`` CREDIT_NOTE/DEBIT_NOTE, ``note_number`` /
    ``note_amount_paise``, and ``pr_note_quarantine=True`` so reconciliation
    keeps them out of invoice matching and ITC at Risk.
    """
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

    mapping = (
        apply_note_mode_column_mapping(column_mapping) if note_mode else column_mapping
    )
    df_canon = normalize_dataframe_to_canonical_schema(df, mapping)

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

        # Tally quirk: GSTIN sometimes lives inside the party-name cell.
        supplier_name = _safe_cell(row.get("supplier_name"))
        party_raw_for_gstin: Any = None
        if "supplier_name" in mapping:
            party_raw_for_gstin = orig_row.get(mapping["supplier_name"])
            if is_multiline_party_name(party_raw_for_gstin) and supplier_name:
                # Keep first non-empty line as the display name.
                first_line = next(
                    (
                        ln.strip()
                        for ln in str(party_raw_for_gstin).replace("\r", "\n").split("\n")
                        if ln.strip()
                    ),
                    supplier_name,
                )
                party_clean, embedded = extract_gstin_from_party_cell(first_line)
                supplier_name = party_clean or first_line
            else:
                party_clean, embedded = extract_gstin_from_party_cell(
                    party_raw_for_gstin if party_raw_for_gstin is not None else supplier_name
                )
                if party_clean:
                    supplier_name = party_clean
        else:
            embedded = None

        gstin_value: str | None = None
        gstin_valid = False
        if "gstin" in mapping:
            raw_gstin = row.get("gstin")
            if raw_gstin is None:
                if embedded:
                    if is_urp_gstin(embedded):
                        gstin_value = URP_NORMALIZED
                        gstin_valid = True
                    else:
                        try:
                            gstin_value = normalize_gstin(embedded)
                            gstin_valid = True
                        except NormalizationError:
                            gstin_value = embedded
                            gstin_valid = False
                else:
                    row_errors.append("missing GSTIN")
            else:
                raw_s = str(raw_gstin).strip()
                if is_urp_gstin(raw_s):
                    gstin_value = URP_NORMALIZED
                    gstin_valid = True
                else:
                    try:
                        gstin_value = normalize_gstin(raw_s)
                        gstin_valid = True
                    except NormalizationError:
                        gstin_value = raw_s.upper() or None
                        gstin_valid = False
        elif embedded:
            # No dedicated GSTIN column (common Tally quirk) — use embedded value.
            if is_urp_gstin(embedded):
                gstin_value = URP_NORMALIZED
                gstin_valid = True
            else:
                try:
                    gstin_value = normalize_gstin(embedded)
                    gstin_valid = True
                except NormalizationError:
                    gstin_value = embedded
                    gstin_valid = False

        note_raw: str | None = None
        if note_mode and "note_number" in mapping:
            cell = row.get("note_number")
            if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                note_raw = None
            else:
                note_raw = str(cell).strip().upper() if str(cell).strip() else None
            if note_raw is None:
                row_errors.append("missing note number")

        inv_raw: str | None = None
        inv_norm: str | None = None
        if (not note_mode) and "invoice_number" in mapping:
            raw_val = row.get("invoice_number_raw")
            norm_val = row.get("invoice_number_normalized")
            inv_raw = (
                str(raw_val).strip().upper()
                if (raw_val is not None and not (isinstance(raw_val, float) and pd.isna(raw_val)) and str(raw_val).strip())
                else None
            )
            inv_norm = (
                str(norm_val).strip().upper()
                if (norm_val is not None and not (isinstance(norm_val, float) and pd.isna(norm_val)) and str(norm_val).strip())
                else None
            )
            if inv_raw is None and inv_norm is not None:
                inv_raw = inv_norm
            if inv_norm is None and inv_raw is not None:
                inv_norm = normalize_invoice(inv_raw)
            if inv_raw is None:
                row_errors.append("missing invoice number")

        date_value: str | None = None
        if "invoice_date" in mapping:
            raw_date = _safe_cell(orig_row.get(mapping["invoice_date"]))
            if raw_date is not None:
                try:
                    norm_date = normalize_date(raw_date)
                    date_value = norm_date.value.isoformat()
                except NormalizationError:
                    row_errors.append("invalid date")

        note_type_cell = _safe_cell(row.get("note_type")) if note_mode else None
        if note_mode:
            invoice_type = infer_note_document_type(
                sheet_name=sheet_name,
                note_type_value=note_type_cell,
                column_headers=list(df.columns),
            )
            # Prefer explicit default when nothing in sheet/headers/cells is decisive.
            if invoice_type == "DEBIT_NOTE" and default_note_type == "CREDIT_NOTE":
                if not (
                    (sheet_name and re.search(r"credit|debit|cn|dn", str(sheet_name), re.I))
                    or note_type_cell
                ):
                    invoice_type = default_note_type
        else:
            original_taxable_peek: int | None = None
            if "taxable_amount" in mapping:
                original_taxable_peek = _df_cell_int(row.get("taxable_amount_paise"))
            note_type_hint = _safe_cell(row.get("note_type")) if "note_type" in mapping else None
            invoice_type = _classify_invoice_type(inv_raw, original_taxable_peek, note_type_hint)

        taxable_amount_paise: int | None = None
        note_amount_paise: int | None = None
        if note_mode:
            if "note_amount" in mapping:
                raw_amt = _safe_cell(orig_row.get(mapping["note_amount"]))
                note_amount_paise = _df_cell_int(row.get("note_amount_paise"))
                if raw_amt is not None and note_amount_paise is None:
                    row_errors.append("invalid value")
        elif "taxable_amount" in mapping:
            raw_tax = _safe_cell(orig_row.get(mapping["taxable_amount"]))
            taxable_amount_paise = _df_cell_int(row.get("taxable_amount_paise"))
            if raw_tax is not None:
                if taxable_amount_paise is None:
                    row_errors.append("invalid value")
            # Auto-promote negative taxable rows to CREDIT_NOTE
            if not note_mode and taxable_amount_paise is not None and taxable_amount_paise < 0 and invoice_type == "INVOICE":
                invoice_type = "CREDIT_NOTE"

        if row_errors:
            if "missing GSTIN" in row_errors and (
                "missing invoice number" in row_errors
                or "missing note number" in row_errors
            ):
                # Truly unparseable: no GSTIN *and* no invoice reference.
                skipped_rows += 1
                _bump_skip("truly_unparseable_row")
                continue
            elif row_errors == ["missing GSTIN"]:
                # Has an invoice number but no GSTIN (unregistered vendor,
                # Tally EDU test data, etc.). Import with gstin=None — row
                # will appear as unmatched in reconciliation, not dropped.
                errors.append(
                    f"{sheet_prefix}Row {row_number}: missing GSTIN (imported without GSTIN)"
                )
                # Fall through — do NOT skip this row.
            else:
                errors.append(
                    f"{sheet_prefix}Row {row_number}: {', '.join(row_errors)}"
                )
                skipped_rows += 1
                _bump_skip("invalid_row")
                continue

        igst_paise = None if note_mode else _df_cell_int(row.get("igst_paise"))
        cgst_paise = None if note_mode else _df_cell_int(row.get("cgst_paise"))
        sgst_paise = None if note_mode else _df_cell_int(row.get("sgst_paise"))
        cess_paise = None if note_mode else _df_cell_int(row.get("cess_paise"))
        total_tax_paise = None if note_mode else _df_cell_int(row.get("total_tax_paise"))
        if not note_mode and total_tax_paise is None and (
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
        total_amount_paise = (
            None if note_mode else _df_cell_int(row.get("total_amount_paise"))
        )
        if not note_mode:
            if total_amount_paise is None and taxable_amount_paise is not None and total_tax_paise is not None:
                total_amount_paise = taxable_amount_paise + total_tax_paise
            elif taxable_amount_paise is None and total_amount_paise is not None and total_tax_paise is not None:
                taxable_amount_paise = total_amount_paise - total_tax_paise
        if (
            not note_mode
            and invoice_type == "CREDIT_NOTE"
        ):
            if total_tax_paise is not None and total_tax_paise > 0:
                total_tax_paise = -total_tax_paise
            if igst_paise is not None and igst_paise > 0:
                igst_paise = -igst_paise
            if cgst_paise is not None and cgst_paise > 0:
                cgst_paise = -cgst_paise
            if sgst_paise is not None and sgst_paise > 0:
                sgst_paise = -sgst_paise
            if cess_paise is not None and cess_paise > 0:
                cess_paise = -cess_paise
            if taxable_amount_paise is not None and taxable_amount_paise > 0:
                taxable_amount_paise = -taxable_amount_paise
            if total_amount_paise is not None and total_amount_paise > 0:
                total_amount_paise = -total_amount_paise

        _rcell = row.get("reverse_charge")
        if _rcell is None or (isinstance(_rcell, float) and pd.isna(_rcell)):
            reverse_out: bool | None = None
        else:
            reverse_out = _rcell  # type: ignore[assignment]

        payment_status: str | None = None
        if "payment_status" in mapping:
            _ps = row.get("payment_status")
            if _ps is None or (isinstance(_ps, float) and pd.isna(_ps)):
                payment_status = None
            else:
                payment_status = str(_ps)

        payment_date: str | None = None
        if "payment_date" in mapping:
            raw_pay_date = _safe_cell(
                orig_row.get(mapping["payment_date"])
            )
            if raw_pay_date is not None:
                try:
                    payment_date = normalize_date(raw_pay_date).value.isoformat()
                except NormalizationError:
                    errors.append(
                        f"{sheet_prefix}Row {row_number}: invalid payment date "
                        f"(ignored for Rule 37)"
                    )

        amount_paid_paise: int | None = None
        if "amount_paid" in mapping:
            amount_paid_paise = _df_cell_int(row.get("amount_paid_paise"))

        out: dict[str, Any] = {
            "row_number": row_number,
            "invoice_number_normalized": None if note_mode else inv_norm,
            "invoice_number": None if note_mode else inv_raw,
            "document_type": invoice_type,
            "invoice_type": invoice_type,
            "is_credit_note": (invoice_type == "CREDIT_NOTE" or (taxable_amount_paise is not None and taxable_amount_paise < 0)),
            "is_debit_note": (invoice_type == "DEBIT_NOTE"),
            "invoice_date": date_value,
            "gstin": gstin_value,
            "gstin_valid": gstin_valid,
            "supplier_name": supplier_name,
            "taxable_amount_paise": None if note_mode else taxable_amount_paise,
            "igst_paise": igst_paise,
            "cgst_paise": cgst_paise,
            "sgst_paise": sgst_paise,
            "cess_paise": cess_paise,
            "total_tax_paise": total_tax_paise,
            "total_amount_paise": total_amount_paise,
            "place_of_supply": _safe_cell(row.get("place_of_supply")),
            "reverse_charge": reverse_out,
            "source_file": filename,
        }
        if note_mode:
            out["note_number"] = note_raw
            out["note_amount_paise"] = note_amount_paise
            out["pr_note_quarantine"] = True
            note_reason = _safe_cell(row.get("note_reason"))
            if note_reason:
                out["note_reason"] = note_reason
            if note_type_cell:
                out["note_type"] = note_type_cell
        if sheet_name:
            out["source_sheet"] = sheet_name
        if payment_status is not None:
            out["payment_status"] = payment_status
        if payment_date is not None:
            out["payment_date"] = payment_date
        if amount_paid_paise is not None:
            out["amount_paid_paise"] = amount_paid_paise
        if "itc_eligibility" in mapping:
            _itc = row.get("itc_eligibility")
            if _itc is not None and not (isinstance(_itc, float) and pd.isna(_itc)):
                out["itc_eligibility"] = str(_itc)
        if "hsn" in mapping:
            _hsn = row.get("hsn")
            if _hsn is not None and not (isinstance(_hsn, float) and pd.isna(_hsn)):
                out["hsn"] = str(_hsn).strip()
        if "original_invoice_number" in mapping:
            _orig_inv = _safe_cell(row.get("original_invoice_number"))
            if _orig_inv:
                out["original_invoice_number"] = _orig_inv

        records.append(out)

    return {
        "records": records,
        "errors": errors,
        "warnings": warnings,
        "total_rows": total_rows,
        "skipped_rows": skipped_rows,
        "skip_reasons": skip_reasons,
        "df_canon": df_canon,
        "note_mode": note_mode,
    }


def parse_purchase_register(
    file_content: bytes, filename: str, client_gstin: str | None = None
) -> dict:
    """Parse a purchase-register file and return a structured result dict.

    Multi-sheet Excel workbooks: every non-skipped sheet with a valid column
    mapping is parsed and combined. Sheets used vs skipped are returned in
    ``sheets_used`` / ``sheets_skipped`` and mirrored in ``warnings``.
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

    import zipfile
    if (ext == ".zip" or file_content[:4] == b"PK\x03\x04") and ext not in (".xlsx", ".xls"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
                if any(n.startswith("xl/") or n == "[Content_Types].xml" for n in zf.namelist()):
                    ext = ".xlsx"
                else:
                    members = [
                        m for m in zf.namelist()
                        if not m.startswith("__MACOSX/") and not os.path.basename(m).startswith(".") and not m.endswith("/")
                    ]
                    doc_members = [
                        m for m in members
                        if any(m.lower().endswith(e) for e in (".xlsx", ".xls", ".csv"))
                    ]
                    if doc_members:
                        chosen = doc_members[0]
                        file_content = zf.read(chosen)
                        filename = os.path.basename(chosen)
                        dot_idx = filename.rfind(".")
                        ext = filename[dot_idx:].lower() if dot_idx != -1 else ""
        except (zipfile.BadZipFile, Exception):
            pass

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
                    _PR_PARSE_SOFT_TIMEOUT_SEC > 0
                    and (time.perf_counter() - parse_started)
                    > _PR_PARSE_SOFT_TIMEOUT_SEC
                ):
                    raise ParseError(
                        f"Purchase register parse exceeded soft timeout "
                        f"({_PR_PARSE_SOFT_TIMEOUT_SEC:.0f}s) after "
                        f"{len(sheet_jobs)} sheet(s). Re-upload a smaller file "
                        f"or raise PR_PARSE_SOFT_TIMEOUT_SEC."
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
                    raw_df, client_gstin=client_gstin
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
                        "PR sheet '%s' accepted (header_row=%s, mapped=%s, "
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
                            "detail": "could not detect required purchase-register columns",
                        }
                    )
                    logger.info(
                        "PR sheet '%s' skipped (no mapping, elapsed=%.2fs)",
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
                    raw_df, client_gstin=client_gstin
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
                _PR_PARSE_SOFT_TIMEOUT_SEC > 0
                and (time.perf_counter() - row_phase_started)
                > _PR_PARSE_SOFT_TIMEOUT_SEC
            ):
                raise ParseError(
                    f"Purchase register row processing exceeded soft timeout "
                    f"({_PR_PARSE_SOFT_TIMEOUT_SEC:.0f}s) after "
                    f"{len(records)} record(s). Re-upload a smaller file "
                    f"or raise PR_PARSE_SOFT_TIMEOUT_SEC."
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

            if "invoice_number" not in mapping and "note_number" not in mapping:
                sheet_label = sheet_name or "(csv)"
                warnings.append(
                    f"[{sheet_label}] No invoice number column detected "
                    f"(expected headers like Invoice Number / Bill No / Vch No.). "
                    f"Rows from this sheet will be skipped during matching."
                )

            note_mode = is_note_sheet_name(sheet_name) or headers_indicate_notes(
                source_cols
            )
            # Mapping may already carry note_number from alias detection.
            if "note_number" in mapping and "invoice_number" not in mapping:
                note_mode = True
            default_note_type = infer_note_document_type(
                sheet_name=sheet_name,
                column_headers=source_cols,
            )
            if note_mode:
                sheet_label = sheet_name or "(csv)"
                warnings.append(
                    f"[{sheet_label}] Detected credit/debit note sheet — "
                    f"rows quarantined from invoice matching "
                    f"(document_type={default_note_type}). Full CDN↔GSTR-2B "
                    f"note matching is not implemented yet."
                )

            part = _process_pr_sheet_rows(
                df=df,
                column_mapping=mapping,
                selected_header_row=header_row,
                filename=filename,
                sheet_name=sheet_name,
                note_mode=note_mode,
                default_note_type=default_note_type,
            )
            sheet_rec_count = len(part["records"])
            sheets_used.append(
                {
                    "sheet": sheet_name or "(csv)",
                    "records": sheet_rec_count,
                    "total_rows": part["total_rows"],
                    "mapped_fields": sorted(
                        (
                            apply_note_mode_column_mapping(mapping)
                            if note_mode
                            else mapping
                        ).keys()
                    ),
                    "has_invoice_number": "invoice_number" in mapping,
                    "note_mode": note_mode,
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
                f"Combined {len(sheets_used)} sheets into one purchase register: "
                f"{used_names}. If sheets overlap, invoices may be double-counted."
            )
            logger.warning("PR multi-sheet combine: %s", used_names)
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
            if not rec.get("pr_note_quarantine")
            and not (
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
                f"{missing_invoice_number_count} purchase register row(s) "
                f"missing invoice number after parsing — will be skipped "
                f"during matching. By sheet: {sheet_bits}."
            )
            logger.warning(
                "PR missing invoice_number: count=%d by_sheet=%s file=%s",
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
    result["skipped_rows"] = skipped_rows
    result["skip_reasons"] = skip_reasons
    result["detected_columns"] = column_mapping
    result["unmapped_columns"] = unmapped_columns
    if source_software == "Tally" or looks_like_tally_headers(
        list(column_mapping.values()) if column_mapping else []
    ):
        result["export_profile"] = "Tally Export"
        for issue in validate_tally_export(
            register_type="purchase",
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


def parse_purchase_register_dataframe(
    file_content: bytes, filename: str, client_gstin: str | None = None
) -> pd.DataFrame:
    """Parse a purchase register and return the canonical DataFrame directly.

    Columns match ``app.services.sanity`` expectations:
    ``gstin`` (upper), ``invoice_number_normalized`` (str, upper),
    ``invoice_date`` (str), ``taxable_amount_paise`` / ``cgst_paise`` /
    ``sgst_paise`` / ``igst_paise`` / ``total_tax_paise`` /
    ``total_amount_paise`` (ints).

    Raises ParseError on failure (the dict returned by ``parse_purchase_register``
    is not used here).
    """
    res = parse_purchase_register(file_content, filename, client_gstin=client_gstin)
    if not res.get("success"):
        raise ParseError("; ".join(res.get("errors") or ["parse failed"]))
    df_out = res.get("normalized_dataframe")
    if df_out is None:
        raise ParseError("no normalized dataframe produced")
    return df_out


if __name__ == "__main__":
    for key in ("supplier_name", "total_tax", "total_amount"):
        print(f"COLUMN_ALIASES[{key!r}]:")
        print(COLUMN_ALIASES[key])
        print()

    mock_headers = [
        "Supplier GSTIN",
        "Supplier Name",
        "Invoice Number",
        "Invoice Date",
        "Taxable Amount",
        "IGST",
        "CGST",
        "SGST",
        "Total Invoice Value",
    ]
    df = pd.DataFrame(columns=mock_headers)
    mapping = detect_column_mapping(df)
    print("detect_column_mapping(mock headers):")
    for std, col in mapping.items():
        print(f"  {std}: {col!r}")

    assert mapping.get("supplier_name") == "Supplier Name", mapping
    total_col = mapping.get("total_amount") or mapping.get("total_tax")
    assert total_col == "Total Invoice Value", mapping
    assert mapping.get("taxable_amount") == "Taxable Amount", mapping
    assert mapping.get("gstin") == "Supplier GSTIN", mapping
    print("\nAll assertions passed.")
