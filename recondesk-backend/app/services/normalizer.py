"""GSTIN, date, amount, and invoice-number normalizers.

All module-level names are immutable constants or compiled patterns.
No global mutable state exists anywhere in this file.
"""

import datetime
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHAR_INDEX = {c: i for i, c in enumerate(CHARSET)}
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9][Z][0-9A-Z]$")
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
WHITELIST_PATTERN = re.compile(r"[^0-9A-Z]")


def _gstin_expected_checksum_char(first_14: str) -> str:
    """15th GSTIN character: Luhn mod 36 over the first 14 (GST/CBIC rule).

    For each position i (0-based) from the left: factor 1 if i is even else 2.
    ``product = char_index * factor``; while ``product >= 36``, replace with
    ``(product // 36) + (product % 36)``. Sum folded values, then
    ``check_index = (36 - (total % 36)) % 36`` in CHARSET.
    """
    total = 0
    for i, ch in enumerate(first_14):
        factor = 1 if (i % 2 == 0) else 2
        product = CHAR_INDEX[ch] * factor
        while product >= 36:
            product = (product // 36) + (product % 36)
        total += product
    return CHARSET[(36 - (total % 36)) % 36]



class NormalizationError(Exception):
    """Raised when a value fails normalization or validation.

    Attributes:
        field:     Name of the field being validated (e.g. "gstin").
        raw_value: The original value supplied by the caller.
        reason:    One of: "empty", "invalid_length", "invalid_format",
                   "invalid_checksum".
    """

    def __init__(self, field: str, raw_value, reason: str) -> None:
        self.field = field
        self.raw_value = raw_value
        self.reason = reason
        super().__init__(
            f"Normalization failed for field '{field}': {reason} (raw={raw_value!r})"
        )


def normalize_gstin(raw) -> str:
    """Normalize and validate a raw GSTIN string.

    Steps performed in order:
    1. Reject None  → reason "empty"
    2. Reject non-str types  → reason "invalid_format"
    3. Strip surrounding whitespace and upper-case
    4. Silently drop characters outside [0-9A-Z] via whitelist
    5. Reject semantically empty result  → reason "empty"
    6. Reject length ≠ 15  → reason "invalid_length"
    7. Validate overall GSTIN pattern  → reason "invalid_format"
    8. Validate embedded PAN (chars 2–11)  → reason "invalid_format"
    9. Validate 15th character against GSTIN check digit  → "invalid_checksum"

    Returns the cleaned, upper-cased, validated GSTIN string.

    Raises:
        NormalizationError: with field="gstin" and an appropriate reason.
    """
    if raw is None:
        raise NormalizationError("gstin", raw, "empty")

    if not isinstance(raw, str):
        raise NormalizationError("gstin", raw, "invalid_format")

    cleaned = WHITELIST_PATTERN.sub("", raw.strip().upper())

    if not cleaned:
        raise NormalizationError("gstin", raw, "empty")

    if len(cleaned) != 15:
        raise NormalizationError("gstin", raw, "invalid_length")

    if not GSTIN_REGEX.match(cleaned):
        raise NormalizationError("gstin", raw, "invalid_format")

    pan = cleaned[2:12]
    if not PAN_REGEX.match(pan):
        raise NormalizationError("gstin", raw, "invalid_format")

    if cleaned[14] != _gstin_expected_checksum_char(cleaned[:14]):
        raise NormalizationError("gstin", raw, "invalid_checksum")

    return cleaned


def batch_normalize_gstins(raw_list) -> dict:
    """Normalize a list of raw GSTIN strings.

    Returns a dict with three keys:
        "valid"      – list of {"raw": ..., "normalized": ...} in input order.
        "invalid"    – list of {"raw": ..., "reason": ..., "index": i} in input order.
        "duplicates" – unique list of normalized GSTINs that appear more than once
                       in the valid results, in first-occurrence order.

    O(n) implementation: dict/set lookups only, no nested loops over raw_list.
    raw_list is never mutated.
    """
    valid: list = []
    invalid: list = []
    seen: dict = {}

    for i, raw in enumerate(raw_list):
        try:
            normalized = normalize_gstin(raw)
            valid.append({"raw": raw, "normalized": normalized})
            seen[normalized] = seen.get(normalized, 0) + 1
        except NormalizationError as exc:
            invalid.append({"raw": raw, "reason": exc.reason, "index": i})

    duplicates = [n for n, count in seen.items() if count > 1]

    return {
        "valid": valid,
        "invalid": invalid,
        "duplicates": duplicates,
    }


# ---------------------------------------------------------------------------
# Shared constants for date / amount / invoice normalizers
# ---------------------------------------------------------------------------

MONTH_MAP = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}

ALLOWED_NOTES: frozenset = frozenset({
    "symbols_stripped",
    "commas_stripped",
    "internal_spaces_stripped",
    "parentheses_negative",
    "lakh_suffix_converted",
    "crore_suffix_converted",
    "k_suffix_converted",
    "excel_serial_converted",
    "time_stripped",
    "two_digit_year_expanded",
    "leading_zeros_stripped",
    "uppercased",
    "truncated_to_50_chars",
})

# Suffix table: (uppercase_suffix, rupee_multiplier, note_tag)
# Order is significant — longest match must come before any prefix of itself.
_AMOUNT_SUFFIXES = (
    ("CRORE", 10_000_000, "crore_suffix_converted"),
    ("CR",    10_000_000, "crore_suffix_converted"),
    ("LAKHS", 100_000,    "lakh_suffix_converted"),
    ("LAKH",  100_000,    "lakh_suffix_converted"),
    ("L",     100_000,    "lakh_suffix_converted"),
    ("K",     1_000,      "k_suffix_converted"),
)

_PAISE_CAP = 1_000_000_000_000  # 1 lakh crore; values >= this raise overflow


@dataclass
class NormalizationResult:
    """Wraps a normalized value together with a log of transformations applied."""

    value: Any
    notes: list = field(default_factory=list)


def _note(notes: list, tag: str) -> None:
    """Append *tag* to *notes*.

    Raises ValueError (developer error) if *tag* is not in ALLOWED_NOTES.
    """
    if tag not in ALLOWED_NOTES:
        raise ValueError(f"Unknown normalization note: {tag!r}")
    notes.append(tag)


# ---------------------------------------------------------------------------
# normalize_date
# ---------------------------------------------------------------------------

def normalize_date(raw) -> NormalizationResult:
    """Normalize *raw* to a ``datetime.date`` wrapped in a NormalizationResult.

    Supported input forms (in detection order):
    * Python float / int  → treated as Windows-1900 Excel serial
    * Purely numeric string (``"45383"``, ``"45383.0"``) → Excel serial
    * ``"YYYY-MM-DD HH:MM:SS"`` → date extracted, time discarded
    * ``"YYYY-MM-DD"``
    * ``"DD-MM-YYYY"`` / ``"DD/MM/YYYY"`` / ``"DD.MM.YYYY"``
    * ``"DD-MM-YY"`` / ``"DD/MM/YY"`` — 00-69 → 2000-2069, 70-99 → 1970-1999
    * ``"DD MMM YYYY"`` / ``"DD-MMM-YYYY"`` / ``"DD-MMM-YY"`` (month case-insensitive)

    Ambiguous ``DD-MM-YY`` rule: ``01-02-03`` is always day=1, month=2, year=2003.

    Raises:
        NormalizationError: reason ``"invalid_date"`` for logically impossible dates,
            ``"invalid_format"`` when no format matches.
    """
    notes: list = []

    # --- Excel serial supplied as Python numeric type ---
    if not isinstance(raw, bool) and isinstance(raw, (int, float)):
        serial = int(raw)
        try:
            date_val = (
                datetime.datetime(1899, 12, 30) + datetime.timedelta(days=serial)
            ).date()
        except (ValueError, OverflowError):
            raise NormalizationError("date", raw, "invalid_format")
        _note(notes, "excel_serial_converted")
        return NormalizationResult(value=date_val, notes=notes)

    if not isinstance(raw, str):
        raise NormalizationError("date", raw, "invalid_format")

    s = raw.strip()
    if not s:
        raise NormalizationError("date", raw, "invalid_format")

    # --- Excel serial as numeric string: "45383" or "45383.0" ---
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        try:
            serial = int(float(s))
            date_val = (
                datetime.datetime(1899, 12, 30) + datetime.timedelta(days=serial)
            ).date()
        except (ValueError, OverflowError):
            raise NormalizationError("date", raw, "invalid_format")
        _note(notes, "excel_serial_converted")
        return NormalizationResult(value=date_val, notes=notes)

    # --- Excel datetime string: "YYYY-MM-DD HH:MM:SS[...]" ---
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}", s)
    if m:
        _note(notes, "time_stripped")
        try:
            date_val = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            raise NormalizationError("date", raw, "invalid_date")
        return NormalizationResult(value=date_val, notes=notes)

    # --- YYYY-MM-DD (4-digit year first) ---
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date_val = datetime.date(year, month, day)
        except ValueError:
            raise NormalizationError("date", raw, "invalid_date")
        return NormalizationResult(value=date_val, notes=notes)

    # --- DD-MM-YYYY (4-digit year last) ---
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date_val = datetime.date(year, month, day)
        except ValueError:
            raise NormalizationError("date", raw, "invalid_date")
        return NormalizationResult(value=date_val, notes=notes)

    # --- DD-MM-YY (2-digit year — always treated as DD-MM-YY, never YYYY) ---
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2})", s)
    if m:
        day, month, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year = (2000 + yy) if yy <= 69 else (1900 + yy)
        _note(notes, "two_digit_year_expanded")
        try:
            date_val = datetime.date(year, month, day)
        except ValueError:
            raise NormalizationError("date", raw, "invalid_date")
        return NormalizationResult(value=date_val, notes=notes)

    # --- Month-name formats: DD MMM YYYY / DD-MMM-YYYY / DD-MMM-YY ---
    m = re.fullmatch(r"(\d{1,2})[\s-]([A-Za-z]+)[\s-](\d{2,4})", s)
    if m:
        day = int(m.group(1))
        month_key = m.group(2).upper()
        year_str = m.group(3)

        if month_key not in MONTH_MAP:
            raise NormalizationError("date", raw, "invalid_format")

        month = MONTH_MAP[month_key]

        if len(year_str) == 2:
            yy = int(year_str)
            year = (2000 + yy) if yy <= 69 else (1900 + yy)
            _note(notes, "two_digit_year_expanded")
        else:
            year = int(year_str)

        try:
            date_val = datetime.date(year, month, day)
        except ValueError:
            raise NormalizationError("date", raw, "invalid_date")
        return NormalizationResult(value=date_val, notes=notes)

    raise NormalizationError("date", raw, "invalid_format")


# ---------------------------------------------------------------------------
# normalize_amount
# ---------------------------------------------------------------------------

_CURRENCY_PREFIX_RE = re.compile(
    r"(?:₹|Rs\.|RS\.|rs\.|Rs|RS|rs|INR|')+",
    re.IGNORECASE,
)

# Matches accounting Dr / Cr suffix preceded by at least one space.
# The space requirement is critical: "2Cr" (crore) must NOT match,
# but "1000 Cr" (credit notation) must match.
_DR_CR_RE = re.compile(r"\s+([Dd][Rr]|[Cc][Rr])\s*$")


def _amount_strip_suffix(
    s_upper: str,
) -> Tuple[str, int, Optional[str]]:
    for suffix_str, mult, tag in _AMOUNT_SUFFIXES:
        if s_upper.endswith(suffix_str):
            return s_upper[: -len(suffix_str)], mult, tag
    return s_upper, 1, None


def normalize_amount(value) -> NormalizationResult:
    """Normalize a messy monetary value to **integer paise** in a ``NormalizationResult``.

    Raises:
        ``NormalizationError`` (field ``amount``): ``empty``, ``invalid_format``,
        ``overflow``, ``multiple_suffixes``.
    """
    raw = value
    notes: list = []

    if value is None:
        raise NormalizationError("amount", raw, "empty")
    if isinstance(value, bool):
        raise NormalizationError("amount", raw, "invalid_format")
    if isinstance(value, float) and math.isnan(value):
        raise NormalizationError("amount", raw, "invalid_format")

    s = str(value).strip()
    if not s:
        raise NormalizationError("amount", raw, "empty")

    is_negative = False
    if s.startswith("-"):
        is_negative = True
        s = s[1:].strip()

    m = _DR_CR_RE.search(s)
    if m:
        if m.group(1).upper() == "CR":
            is_negative = True
        s = s[: m.start()].strip()

    s2 = _CURRENCY_PREFIX_RE.sub("", s).strip()
    if s2 != s:
        _note(notes, "symbols_stripped")
    s = s2

    s2 = s.replace(",", "")
    if s2 != s:
        _note(notes, "commas_stripped")
    s = s2

    if re.search(r"\d\s+\d", s):
        _note(notes, "internal_spaces_stripped")
    s = s.replace(" ", "")

    if s.startswith("(") and s.endswith(")"):
        is_negative = not is_negative
        s = s[1:-1].strip()
        _note(notes, "parentheses_negative")

    if not s:
        raise NormalizationError("amount", raw, "invalid_format")

    s_upper = s.upper()
    rest, mult, tag = _amount_strip_suffix(s_upper)
    if tag is not None:
        _note(notes, tag)
        s_upper = rest
        if s_upper and _amount_strip_suffix(s_upper)[2] is not None:
            raise NormalizationError("amount", raw, "multiple_suffixes")

    if not s_upper:
        raise NormalizationError("amount", raw, "invalid_format")

    try:
        amount_rupees = float(s_upper)
    except (ValueError, TypeError):
        raise NormalizationError("amount", raw, "invalid_format")

    if not math.isfinite(amount_rupees):
        raise NormalizationError("amount", raw, "invalid_format")

    amount_rupees = amount_rupees * mult
    if is_negative:
        amount_rupees = -amount_rupees

    paise = int(round(amount_rupees * 100.0))
    if abs(paise) >= _PAISE_CAP:
        raise NormalizationError("amount", raw, "overflow")

    return NormalizationResult(value=paise, notes=notes)


# ---------------------------------------------------------------------------
# normalize_invoice_number
# ---------------------------------------------------------------------------

def normalize_invoice_number(raw: str) -> NormalizationResult:
    """Normalize *raw* invoice number to an uppercase alphanumeric string ≤ 50 chars.

    Steps (in order):
    1. Strip all non-alphanumeric characters.
    2. Uppercase.
    3. If result is purely numeric, strip leading zeros.
    4. Raise ``"empty_after_normalization"`` if result is empty.
    5. Truncate to 50 characters.

    Raises:
        NormalizationError: reason ``"invalid_format"`` for non-string input,
            ``"empty_after_normalization"`` when nothing survives normalization.
    """
    if not isinstance(raw, str):
        raise NormalizationError("invoice_number", raw, "invalid_format")

    # 1. Strip non-alphanumeric.
    stripped = re.sub(r"[^A-Za-z0-9]", "", raw)
    did_strip_symbols = stripped != raw

    # 2. Uppercase.
    upper = stripped.upper()
    did_uppercase = upper != stripped

    # 3. Segment-based zero stripping — strip leading zeros from all numeric segments.
    # This normalises "INV-001" → "INV1", "000123" → "123", "INV001" → "INV1".
    parts = re.findall(r'\d+|\D+', upper)
    stripped_zeros = []
    did_strip_leading_zeros = False
    for p in parts:
        if p.isdigit():
            no_zeros = p.lstrip('0') or '0'  # guard: "000000" → "0" (not empty)
            if no_zeros != p:
                did_strip_leading_zeros = True
            stripped_zeros.append(no_zeros)
        else:
            stripped_zeros.append(p)
    upper = ''.join(stripped_zeros)

    # 4. Empty check — catches symbol-only inputs like "@@@" that leave nothing.
    if not upper:
        raise NormalizationError("invoice_number", raw, "empty_after_normalization")

    # 5. Truncate to 50 characters.
    did_truncate = len(upper) > 50
    if did_truncate:
        upper = upper[:50]

    # 6. Build notes in canonical order.
    notes: list = []
    if did_strip_symbols:
        _note(notes, "symbols_stripped")
    if did_strip_leading_zeros:
        _note(notes, "leading_zeros_stripped")
    if did_uppercase:
        _note(notes, "uppercased")
    if did_truncate:
        _note(notes, "truncated_to_50_chars")

    return NormalizationResult(value=upper, notes=notes)
