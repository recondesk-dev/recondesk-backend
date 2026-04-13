"""GSTIN normalizer and validator.

All module-level names are immutable constants or compiled patterns.
No global mutable state exists anywhere in this file.
"""

import re

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHAR_INDEX = {c: i for i, c in enumerate(CHARSET)}
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9][Z][0-9A-Z]$")
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
WHITELIST_PATTERN = re.compile(r"[^0-9A-Z]")

# Alternating weight factors for positions 0–13, starting with 1.
_FACTORS = (1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2)


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
    9. Validate Luhn-style checksum (char 14)  → reason "invalid_checksum"

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

    total = sum(CHAR_INDEX[c] * f for c, f in zip(cleaned[:14], _FACTORS))
    expected_checksum = CHARSET[(36 - (total % 36)) % 36]
    if cleaned[14] != expected_checksum:
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
