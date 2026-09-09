"""Tally Prime / ERP 9 register export support for Purchase and Sales imports.

Provides:
- Named ``Tally Export`` alias profiles (header variants → canonical fields)
- Register type detection (Purchase vs Sales) from headers, sheet titles, and
  a few data rows
- Quirk helpers (GSTIN embedded in party name, multiline party cells, total rows)
- Type-specific validation messages
- In-app help copy for generating exports from Tally

This module does not parse files end-to-end — it feeds the existing Purchase
Register (GSTR-2B) and Sales Register (GSTR-1/3B) pipelines.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

import pandas as pd

logger = logging.getLogger(__name__)

RegisterType = Literal["purchase", "sales", "ambiguous"]
Confidence = Literal["high", "medium", "low"]

# GSTIN pattern used for extraction from free-text party cells (not full checksum).
_GSTIN_EMBEDDED_RE = re.compile(
    r"(?<![A-Z0-9])([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9][Z][0-9A-Z])(?![A-Z0-9])",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Tally Export alias profiles
# ---------------------------------------------------------------------------

# Extra aliases layered onto each parser's COLUMN_ALIASES. Keys are parser
# standard field names (taxable_amount, supplier_name / recipient_name, …).

TALLY_PURCHASE_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "gstin/uin",
        "gstin / uin",
        "gstin uin",
        "gstin/uin of supplier",
        "gst reg no",
        "gst reg. no",
        "gst registration no",
        "gst registration number",
        "party gstin/uin",
        "supplier gstin/uin",
    ],
    "invoice_number": [
        "inv no",
        "inv. no.",
        "inv no.",
        "invoice no.",
        "supplier invoice no",
        "supplier inv no",
        "bill no.",
        "ref. no.",
        "reference no",
        "original invoice no",
    ],
    "invoice_date": [
        "inv date",
        "inv. date",
        "invoice dt",
        "supplier invoice date",
        "bill dt.",
        "vch date",
        "voucher dt",
    ],
    "taxable_amount": [
        "taxable amt",
        "taxable amt.",
        "taxable amount",
        "assessable amt",
        "assessable amt.",
        "taxable value of supply",
    ],
    "igst": ["igst amt", "igst amt.", "integrated gst"],
    "cgst": ["cgst amt", "cgst amt.", "central gst"],
    "sgst": ["sgst amt", "sgst amt.", "state gst", "utgst amt"],
    "total_amount": [
        "gross total",
        "invoice total",
        "voucher total",
        "total amt",
        "total amt.",
    ],
    "supplier_name": [
        "party's a/c name",
        "party s a/c name",
        "partys a/c name",
        "party's ac name",
        "party a/c name",
        "party account name",
        "particulars",
        "name of party",
        "name of supplier",
        "supplier's name",
    ],
    "place_of_supply": [
        "place of supply",
        "pos",
        "state of supply",
    ],
    "reverse_charge": [
        "reverse charge",
        "is reverse charge",
        "rcm applicable",
    ],
}

TALLY_SALES_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "gstin/uin",
        "gstin / uin",
        "gstin uin",
        "gstin/uin of recipient",
        "gstin uin of recipient",
        "gst reg no",
        "gst reg. no",
        "gst registration no",
        "gst registration number",
        "party gstin/uin",
        "buyer gstin/uin",
        "customer gstin/uin",
    ],
    "invoice_number": [
        "inv no",
        "inv. no.",
        "inv no.",
        "invoice no.",
        "sales invoice no",
        "sale invoice no",
        "bill no.",
        "ref. no.",
        "reference no",
        "original invoice no",
    ],
    "invoice_date": [
        "inv date",
        "inv. date",
        "invoice dt",
        "sales invoice date",
        "bill dt.",
        "vch date",
        "voucher dt",
    ],
    "taxable_amount": [
        "taxable amt",
        "taxable amt.",
        "taxable amount",
        "assessable amt",
        "assessable amt.",
        "taxable value of supply",
    ],
    "igst": ["igst amt", "igst amt.", "integrated gst", "igst collected"],
    "cgst": ["cgst amt", "cgst amt.", "central gst"],
    "sgst": ["sgst amt", "sgst amt.", "state gst", "utgst amt"],
    "total_amount": [
        "gross total",
        "invoice total",
        "voucher total",
        "total amt",
        "total amt.",
    ],
    "recipient_name": [
        "party's a/c name",
        "party s a/c name",
        "partys a/c name",
        "party's ac name",
        "party a/c name",
        "party account name",
        "particulars",
        "name of party",
        "name of recipient",
        "name of customer",
        "buyer's name",
        "customer's name",
    ],
    "invoice_type": [
        "invoice type",
        "nature of transaction",
        "nature of supply",
        "gst registration type",
        "registration type",
        "party type",
        "taxability type",
        "voucher type",
        "vch type",
        "vch. type",
    ],
    "place_of_supply": [
        "place of supply",
        "pos",
        "state of supply",
        "destination state",
    ],
    "reverse_charge": [
        "reverse charge",
        "is reverse charge",
        "rcm applicable",
    ],
}

# Header tokens that strongly suggest a Tally export (after normalize_header).
_TALLY_HEADER_SIGNALS: frozenset[str] = frozenset(
    {
        "voucher type",
        "vch type",
        "vch no",
        "vch number",
        "party s a c name",  # normalize_header("Party's A/c Name")
        "partys a c name",
        "particulars",
        "gstin uin",
        "gst reg no",
        "taxable amt",
        "gross total",
    }
)

_PURCHASE_TITLE_TOKENS: tuple[str, ...] = (
    "purchase register",
    "purchases register",
    "purchase book",
    "gstr-2",
    "gstr 2",
    "gstr-2a",
    "gstr-2b",
    "gstr2b",
    "inward supply",
    "inward supplies",
)

_SALES_TITLE_TOKENS: tuple[str, ...] = (
    "sales register",
    "sale register",
    "sales book",
    "gstr-1",
    "gstr 1",
    "gstr1",
    "outward supply",
    "outward supplies",
)

_PURCHASE_HEADER_TOKENS: frozenset[str] = frozenset(
    {
        "supplier name",
        "supplier",
        "vendor name",
        "vendor",
        "supplier gstin",
        "vendor gstin",
        "supplier invoice no",
        "creditor",
        "creditor name",
        "itc claimed",
        "itc eligibility",
        "eligible for itc",
    }
)

_SALES_HEADER_TOKENS: frozenset[str] = frozenset(
    {
        "customer name",
        "customer",
        "buyer name",
        "buyer",
        "recipient name",
        "recipient",
        "recipient gstin",
        "buyer gstin",
        "customer gstin",
        "invoice type",
        "nature of transaction",
        "export type",
        "shipping bill no",
        "shipping bill number",
        "b2b",
        "b2c",
        "sold to",
        "bill to",
        "debtor",
        "debtor name",
    }
)

_PURCHASE_VOUCHER_VALUES: frozenset[str] = frozenset(
    {
        "purchase",
        "purchases",
        "debit note",
        "purchase debit note",
        "receipt note",
    }
)

_SALES_VOUCHER_VALUES: frozenset[str] = frozenset(
    {
        "sales",
        "sale",
        "credit note",
        "sales credit note",
        "delivery note",
    }
)


# ---------------------------------------------------------------------------
# Help copy (returned to the frontend)
# ---------------------------------------------------------------------------

TALLY_PURCHASE_HELP = (
    "In TallyPrime: Gateway of Tally → Display More Reports → Statutory Reports "
    "→ GST → GSTR-2 / Purchase Register → set period → Alt+E (Export) → Excel or CSV. "
    "In Tally ERP 9: Gateway of Tally → Display → Statutory Reports → GST → "
    "GSTR-2 → Export. Include GSTIN and tax columns in the export configuration."
)

TALLY_SALES_HELP = (
    "In TallyPrime: Gateway of Tally → Display More Reports → Statutory Reports "
    "→ GST → GSTR-1 / Sales Register → set period → Alt+E (Export) → Excel or CSV. "
    "In Tally ERP 9: Gateway of Tally → Display → Statutory Reports → GST → "
    "GSTR-1 → Export. Prefer a columnar register that includes GSTIN/UIN, "
    "Taxable Amt, and Invoice Type (B2B/B2C) when available."
)

TALLY_HELP_COPY: dict[str, str] = {
    "purchase": TALLY_PURCHASE_HELP,
    "sales": TALLY_SALES_HELP,
}


# ---------------------------------------------------------------------------
# Header normalisation (shared with parsers; local copy avoids circular import)
# ---------------------------------------------------------------------------

def normalize_header(col: str) -> str:
    """Lower-case, strip, treat underscores/punctuation as spaces, collapse spaces."""
    col = col.lower().strip().replace("_", " ")
    col = re.sub(r"[^\w\s]", " ", col)
    col = re.sub(r"\s+", " ", col)
    return col.strip()


def merge_aliases(
    base: dict[str, list[str]], extra: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Return a new alias map with *extra* aliases appended (deduped, order kept)."""
    out: dict[str, list[str]] = {k: list(v) for k, v in base.items()}
    for field_name, aliases in extra.items():
        existing = out.setdefault(field_name, [])
        seen = {normalize_header(a) for a in existing}
        for alias in aliases:
            key = normalize_header(alias)
            if key and key not in seen:
                existing.append(alias)
                seen.add(key)
    return out


# ---------------------------------------------------------------------------
# Quirk helpers
# ---------------------------------------------------------------------------

def extract_gstin_from_party_cell(value: Any) -> tuple[Optional[str], Optional[str]]:
    """Split an optional GSTIN embedded in a Tally party-name cell.

    Returns ``(clean_party_name, gstin_or_none)``. Handles forms such as::

        "ABC Traders - 27AABCU9603R1ZM"
        "ABC Traders\\n27AABCU9603R1ZM"
        "27AABCU9603R1ZM - ABC Traders"
    """
    if value is None:
        return None, None
    try:
        if pd.isna(value):
            return None, None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return None, None

    match = _GSTIN_EMBEDDED_RE.search(text)
    if not match:
        return text, None

    gstin = match.group(1).upper()
    # Remove the GSTIN token and tidy separators left behind.
    remainder = (text[: match.start()] + text[match.end() :]).strip()
    remainder = re.sub(r"[\s\-\|/,:;]+$", "", remainder)
    remainder = re.sub(r"^[\s\-\|/,:;]+", "", remainder)
    remainder = re.sub(r"\s{2,}", " ", remainder).strip()
    party = remainder or None
    return party, gstin


def is_multiline_party_name(value: Any) -> bool:
    """True when a party cell contains embedded newlines (common Tally quirk)."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value)
    return "\n" in text or "\r" in text


def looks_like_tally_headers(columns: list[Any]) -> bool:
    """Heuristic: headers look like a Tally columnar register export."""
    norm = {normalize_header(str(c)) for c in columns if c is not None}
    if not norm:
        return False
    hits = sum(1 for sig in _TALLY_HEADER_SIGNALS if sig in norm)
    # Classic Tally daybook/register trio
    has_vch = "vch no" in norm or "vch number" in norm or "voucher no" in norm
    has_party = (
        "particulars" in norm
        or "party s a c name" in norm
        or "partys a c name" in norm
        or "party name" in norm
    )
    has_vch_type = "voucher type" in norm or "vch type" in norm
    if has_vch and has_party and has_vch_type:
        return True
    if has_vch and ("gstin uin" in norm or "gst reg no" in norm) and hits >= 2:
        return True
    return hits >= 3


def detect_source_software_tally(columns: list[Any]) -> Optional[str]:
    """Return ``\"Tally\"`` when headers match the Tally Export profile."""
    if looks_like_tally_headers(columns):
        return "Tally"
    norm = {normalize_header(str(c)) for c in columns if c is not None}
    if "voucher type" in norm or "vch type" in norm:
        return "Tally"
    return None


# ---------------------------------------------------------------------------
# Type detection
# ---------------------------------------------------------------------------

@dataclass
class RegisterTypeDetection:
    """Result of Purchase vs Sales classification for a register file."""

    register_type: RegisterType
    confidence: Confidence
    is_tally_export: bool
    source_software: str
    purchase_score: int = 0
    sales_score: int = 0
    reasons: list[str] = field(default_factory=list)
    suggested_pipeline: Optional[str] = None  # "gstr2b" | "gstr1"
    requires_manual_choice: bool = False
    headers: list[str] = field(default_factory=list)
    sheet_names: list[str] = field(default_factory=list)
    help_copy: Optional[str] = None
    validation_issues: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score_title_text(texts: list[str]) -> tuple[int, int, list[str]]:
    purchase = 0
    sales = 0
    reasons: list[str] = []
    blob = " | ".join(t.lower() for t in texts if t)
    for tok in _PURCHASE_TITLE_TOKENS:
        if tok in blob:
            purchase += 4
            reasons.append(f"Title/sheet mentions “{tok}” → Purchase")
            break
    for tok in _SALES_TITLE_TOKENS:
        if tok in blob:
            sales += 4
            reasons.append(f"Title/sheet mentions “{tok}” → Sales")
            break
    return purchase, sales, reasons


def _score_headers(norm_cols: set[str]) -> tuple[int, int, list[str]]:
    purchase = 0
    sales = 0
    reasons: list[str] = []
    for tok in _PURCHASE_HEADER_TOKENS:
        if tok in norm_cols:
            purchase += 2
            reasons.append(f"Header “{tok}” suggests Purchase Register")
    for tok in _SALES_HEADER_TOKENS:
        if tok in norm_cols:
            sales += 2
            reasons.append(f"Header “{tok}” suggests Sales Register")
    # Particulars alone is common to both Tally registers — weak sales lean
    # only when paired with sales-ish voucher type column (scored in rows).
    if "particulars" in norm_cols and "invoice type" not in norm_cols:
        # Neutral: both Tally PR and SR use Particulars frequently.
        pass
    return purchase, sales, reasons


def _score_sample_rows(
    columns: list[str], sample_rows: list[list[Any]]
) -> tuple[int, int, list[str]]:
    purchase = 0
    sales = 0
    reasons: list[str] = []
    if not sample_rows or not columns:
        return purchase, sales, reasons

    norm_cols = [normalize_header(str(c)) for c in columns]
    vch_type_idx = next(
        (
            i
            for i, c in enumerate(norm_cols)
            if c in ("voucher type", "vch type", "vch type name", "invoice type")
        ),
        None,
    )
    if vch_type_idx is None:
        return purchase, sales, reasons

    p_hits = 0
    s_hits = 0
    for row in sample_rows[:15]:
        if vch_type_idx >= len(row):
            continue
        cell = str(row[vch_type_idx] or "").strip().lower()
        if not cell or cell in ("nan", "none"):
            continue
        # Exact / startswith against known voucher families
        for pv in _PURCHASE_VOUCHER_VALUES:
            if cell == pv or cell.startswith(pv + " "):
                p_hits += 1
                break
        else:
            for sv in _SALES_VOUCHER_VALUES:
                if cell == sv or cell.startswith(sv + " "):
                    s_hits += 1
                    break

    if p_hits > s_hits and p_hits > 0:
        purchase += min(6, p_hits * 2)
        reasons.append(
            f"Voucher/Invoice Type values look like Purchase ({p_hits} sample row(s))"
        )
    elif s_hits > p_hits and s_hits > 0:
        sales += min(6, s_hits * 2)
        reasons.append(
            f"Voucher/Invoice Type values look like Sales ({s_hits} sample row(s))"
        )
    return purchase, sales, reasons


def detect_register_type(
    *,
    headers: list[str],
    sample_rows: Optional[list[list[Any]]] = None,
    sheet_names: Optional[list[str]] = None,
    title_texts: Optional[list[str]] = None,
    expected_type: Optional[Literal["purchase", "sales"]] = None,
) -> RegisterTypeDetection:
    """Classify a register file as Purchase, Sales, or ambiguous.

    When *expected_type* is set (caller is already on a pipeline page), a
    conflicting high-confidence detection still returns the detected type so
    the UI can offer an override / redirect.
    """
    headers = [str(h).strip() for h in headers if h is not None and str(h).strip()]
    norm_cols = {normalize_header(h) for h in headers}
    is_tally = looks_like_tally_headers(headers)
    source = "Tally" if is_tally else "Excel/Unknown"

    titles = list(title_texts or [])
    titles.extend(sheet_names or [])
    # Also peek at filename-like tokens already in titles only

    p_score, s_score, reasons = _score_title_text(titles)
    hp, hs, hr = _score_headers(norm_cols)
    p_score += hp
    s_score += hs
    reasons.extend(hr)

    rp, rs, rr = _score_sample_rows(headers, sample_rows or [])
    p_score += rp
    s_score += rs
    reasons.extend(rr)

    if is_tally:
        reasons.append("Headers match the Tally Export profile")

    # Decide
    register_type: RegisterType = "ambiguous"
    confidence: Confidence = "low"
    if p_score >= s_score + 3 and p_score >= 3:
        register_type = "purchase"
        confidence = "high" if p_score >= s_score + 5 else "medium"
    elif s_score >= p_score + 3 and s_score >= 3:
        register_type = "sales"
        confidence = "high" if s_score >= p_score + 5 else "medium"
    elif p_score > s_score and p_score >= 2:
        register_type = "purchase"
        confidence = "low"
    elif s_score > p_score and s_score >= 2:
        register_type = "sales"
        confidence = "low"
    else:
        register_type = "ambiguous"
        confidence = "low"
        reasons.append(
            "Could not tell Purchase from Sales — please choose the register type"
        )

    requires_manual = register_type == "ambiguous" or confidence == "low"
    suggested: Optional[str] = None
    if register_type == "purchase":
        suggested = "gstr2b"
    elif register_type == "sales":
        suggested = "gstr1"

    help_copy = None
    if register_type in ("purchase", "sales"):
        help_copy = TALLY_HELP_COPY[register_type]
    elif expected_type in ("purchase", "sales"):
        help_copy = TALLY_HELP_COPY[expected_type]

    validation_issues = validate_tally_export(
        register_type=register_type if register_type != "ambiguous" else (expected_type or "purchase"),
        headers=headers,
        sample_rows=sample_rows or [],
        is_tally_export=is_tally,
    )

    # If caller expected a type and we confidently disagree, note it.
    if (
        expected_type
        and register_type in ("purchase", "sales")
        and register_type != expected_type
        and confidence in ("high", "medium")
    ):
        other = "Sales Register (GSTR-1)" if register_type == "sales" else "Purchase Register (GSTR-2B)"
        current = "Purchase Register (GSTR-2B)" if expected_type == "purchase" else "Sales Register (GSTR-1)"
        reasons.append(
            f"This file looks like a {other}, but you are on the {current} import."
        )

    return RegisterTypeDetection(
        register_type=register_type,
        confidence=confidence,
        is_tally_export=is_tally,
        source_software=source,
        purchase_score=p_score,
        sales_score=s_score,
        reasons=reasons[:12],
        suggested_pipeline=suggested,
        requires_manual_choice=requires_manual,
        headers=headers,
        sheet_names=list(sheet_names or []),
        help_copy=help_copy,
        validation_issues=validation_issues,
    )


# ---------------------------------------------------------------------------
# Validation (Tally-specific, user-facing)
# ---------------------------------------------------------------------------

def validate_tally_export(
    *,
    register_type: Literal["purchase", "sales"],
    headers: list[str],
    sample_rows: Optional[list[list[Any]]] = None,
    is_tally_export: bool = False,
) -> list[dict[str, str]]:
    """Return user-facing validation issues for a Tally-style register.

    Each issue is ``{severity, code, message}``.
    """
    issues: list[dict[str, str]] = []
    if not is_tally_export and not looks_like_tally_headers(headers):
        # Still run light checks when headers look register-like.
        pass

    norm_cols = [normalize_header(h) for h in headers]
    norm_set = set(norm_cols)

    has_gstin = any(
        c.startswith("gstin") or "gst reg" in c or c.endswith(" gstin") or c == "gstin"
        for c in norm_set
    )
    if not has_gstin:
        issues.append(
            {
                "severity": "error" if register_type == "purchase" else "warning",
                "code": "tally_missing_gstin_column",
                "message": (
                    "No GSTIN/UIN column found. In Tally, re-export with GST details "
                    "enabled (Configure → show GSTIN/UIN / GST Reg No). "
                    + (
                        "Purchase Register imports need a supplier GSTIN column for GSTR-2B recon."
                        if register_type == "purchase"
                        else "Sales Register B2B rows need recipient GSTIN for GSTR-1 matching; B2C may be blank."
                    )
                ),
            }
        )

    party_idx = next(
        (
            i
            for i, c in enumerate(norm_cols)
            if c
            in (
                "particulars",
                "party s a c name",
                "partys a c name",
                "party name",
                "party",
                "supplier name",
                "customer name",
                "recipient name",
            )
        ),
        None,
    )

    if sample_rows and party_idx is not None:
        multiline = 0
        embedded_gstin = 0
        for row in sample_rows[:40]:
            if party_idx >= len(row):
                continue
            cell = row[party_idx]
            if is_multiline_party_name(cell):
                multiline += 1
            _, g = extract_gstin_from_party_cell(cell)
            if g:
                embedded_gstin += 1
        if multiline:
            issues.append(
                {
                    "severity": "warning",
                    "code": "tally_multiline_party_names",
                    "message": (
                        f"{multiline} party name cell(s) look multi-line. Tally sometimes "
                        "puts address lines in the same cell — ReconDesk will use the first "
                        "line as the party name, but verify odd matches."
                    ),
                }
            )
        if embedded_gstin and not has_gstin:
            issues.append(
                {
                    "severity": "info",
                    "code": "tally_gstin_embedded_in_party",
                    "message": (
                        f"Found GSTIN inside {embedded_gstin} party name cell(s). "
                        "ReconDesk will extract these automatically. For cleaner imports, "
                        "export with a separate GSTIN/UIN column from Tally."
                    ),
                }
            )

    # Blank / Grand Total trailer awareness
    if sample_rows:
        total_like = 0
        for row in sample_rows:
            joined = " ".join(str(c or "").strip().lower() for c in row)
            if joined.startswith("grand total") or joined.strip() == "total":
                total_like += 1
        if total_like:
            issues.append(
                {
                    "severity": "info",
                    "code": "tally_total_rows_present",
                    "message": (
                        "Export includes Grand Total / subtotal rows — these are skipped "
                        "automatically. If totals appear as unmerged invoice rows, remove "
                        "them in Excel before uploading."
                    ),
                }
            )

    if register_type == "sales":
        has_inv_type = any(
            "invoice type" in c
            or "nature of transaction" in c
            or c in ("voucher type", "vch type", "vch type name")
            for c in norm_set
        )
        if is_tally_export and not has_inv_type:
            issues.append(
                {
                    "severity": "warning",
                    "code": "tally_missing_invoice_type",
                    "message": (
                        "No Invoice Type / Voucher Type column found. GSTR-1 recon will "
                        "infer B2B vs B2C from GSTIN presence, but export Invoice Type "
                        "(B2B/B2C/Export) from Tally when available for fewer Review Required rows."
                    ),
                }
            )

    if register_type == "purchase" and is_tally_export:
        has_inv = any(
            c in ("invoice no", "invoice number", "inv no", "bill no", "vch no", "voucher no")
            or c.startswith("invoice no")
            for c in norm_set
        )
        if not has_inv:
            issues.append(
                {
                    "severity": "error",
                    "code": "tally_missing_invoice_number",
                    "message": (
                        "No Invoice No. / Vch No. column found. Re-export the Purchase "
                        "Register from Tally with voucher/invoice numbers included."
                    ),
                }
            )

    return issues


# ---------------------------------------------------------------------------
# File inspection (headers + sample rows + sheet names)
# ---------------------------------------------------------------------------

def _uniqueify_header_labels(headers: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for h in headers:
        if h is None or (isinstance(h, float) and pd.isna(h)):
            label = ""
        else:
            label = str(h).strip()
        if label in seen:
            seen[label] += 1
            unique.append(f"{label}.{seen[label]}")
        else:
            seen[label] = 0
            unique.append(label)
    return unique


def _header_score(headers: list[str]) -> int:
    """Rough score: how many cells look like column headers vs data."""
    score = 0
    for h in headers:
        n = normalize_header(h)
        if not n:
            continue
        if any(
            tok in n
            for tok in (
                "gstin",
                "invoice",
                "vch",
                "voucher",
                "party",
                "particulars",
                "taxable",
                "cgst",
                "sgst",
                "igst",
                "date",
                "amount",
                "total",
            )
        ):
            score += 1
    return score


def inspect_register_file(
    file_content: bytes,
    filename: str,
    *,
    expected_type: Optional[Literal["purchase", "sales"]] = None,
    max_sample_rows: int = 20,
) -> RegisterTypeDetection:
    """Read a CSV/Excel register and return type-detection + validation."""
    if not file_content or not file_content.strip():
        return RegisterTypeDetection(
            register_type="ambiguous",
            confidence="low",
            is_tally_export=False,
            source_software="Excel/Unknown",
            reasons=["Empty file"],
            requires_manual_choice=True,
            help_copy=TALLY_HELP_COPY.get(expected_type or "purchase"),
            validation_issues=[
                {
                    "severity": "error",
                    "code": "empty_file",
                    "message": "The uploaded file is empty.",
                }
            ],
        )

    ext = ""
    dot = filename.rfind(".")
    if dot != -1:
        ext = filename[dot:].lower()

    sheet_names: list[str] = []
    title_texts: list[str] = [filename]
    headers: list[str] = []
    sample_rows: list[list[Any]] = []

    try:
        if ext in (".xlsx", ".xls"):
            xl = pd.ExcelFile(io.BytesIO(file_content))
            sheet_names = [str(s) for s in xl.sheet_names]
            # Prefer a sheet whose name looks like a register; else first usable.
            ordered = sorted(
                sheet_names,
                key=lambda s: (
                    0
                    if any(
                        t in s.lower()
                        for t in (
                            "purchase",
                            "sales",
                            "sale",
                            "gstr",
                            "register",
                        )
                    )
                    else 1,
                    sheet_names.index(s),
                ),
            )
            best_headers: list[str] = []
            best_samples: list[list[Any]] = []
            best_score = -1
            best_sheet_titles: list[str] = []
            for sheet in ordered[:5]:
                raw = pd.read_excel(
                    xl, sheet_name=sheet, header=None, dtype=object, nrows=40
                )
                if raw.empty:
                    continue
                local_best = -1
                local_headers: list[str] = []
                local_samples: list[list[Any]] = []
                local_title_rows: list[str] = []
                max_check = min(12, len(raw))
                for hr in range(max_check):
                    cand = _uniqueify_header_labels(list(raw.iloc[hr].tolist()))
                    sc = _header_score(cand)
                    if sc > local_best:
                        local_best = sc
                        local_headers = cand
                        body = raw.iloc[hr + 1 : hr + 1 + max_sample_rows]
                        local_samples = [
                            list(r) for r in body.values.tolist()
                        ]
                        # Rows above the header often hold report titles.
                        local_title_rows = []
                        for r in range(hr):
                            cells = [
                                str(v).strip()
                                for v in raw.iloc[r].tolist()
                                if v is not None
                                and not (isinstance(v, float) and pd.isna(v))
                                and str(v).strip()
                            ]
                            if cells:
                                local_title_rows.append(" ".join(cells))
                if local_best > best_score:
                    best_score = local_best
                    best_headers = local_headers
                    best_samples = local_samples
                    best_sheet_titles = [sheet, *local_title_rows]
            headers = best_headers
            sample_rows = best_samples
            title_texts.extend(best_sheet_titles)
        elif ext == ".csv":
            # Try common encodings; header may not be row 0.
            raw = None
            for enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    raw = pd.read_csv(
                        io.BytesIO(file_content),
                        header=None,
                        dtype=object,
                        nrows=40,
                        encoding=enc,
                    )
                    break
                except Exception:
                    continue
            if raw is not None and not raw.empty:
                best_score = -1
                for hr in range(min(12, len(raw))):
                    cand = _uniqueify_header_labels(list(raw.iloc[hr].tolist()))
                    sc = _header_score(cand)
                    if sc > best_score:
                        best_score = sc
                        headers = cand
                        body = raw.iloc[hr + 1 : hr + 1 + max_sample_rows]
                        sample_rows = [list(r) for r in body.values.tolist()]
                        for r in range(hr):
                            cells = [
                                str(v).strip()
                                for v in raw.iloc[r].tolist()
                                if v is not None
                                and not (isinstance(v, float) and pd.isna(v))
                                and str(v).strip()
                            ]
                            if cells:
                                title_texts.append(" ".join(cells))
        else:
            return RegisterTypeDetection(
                register_type="ambiguous",
                confidence="low",
                is_tally_export=False,
                source_software="Excel/Unknown",
                reasons=[f"Unsupported file type: {ext or '(none)'}"],
                requires_manual_choice=True,
                help_copy=TALLY_HELP_COPY.get(expected_type or "purchase"),
                validation_issues=[
                    {
                        "severity": "error",
                        "code": "unsupported_type",
                        "message": "Use .xlsx, .xls, or .csv exports from Tally.",
                    }
                ],
            )
    except Exception as exc:
        logger.warning("inspect_register_file failed for %s: %s", filename, exc)
        return RegisterTypeDetection(
            register_type="ambiguous",
            confidence="low",
            is_tally_export=False,
            source_software="Excel/Unknown",
            reasons=[f"Could not read file: {exc}"],
            requires_manual_choice=True,
            help_copy=TALLY_HELP_COPY.get(expected_type or "purchase"),
            validation_issues=[
                {
                    "severity": "error",
                    "code": "read_failed",
                    "message": "Could not read this file. Re-export from Tally as Excel or CSV.",
                }
            ],
        )

    if not headers:
        return RegisterTypeDetection(
            register_type="ambiguous",
            confidence="low",
            is_tally_export=False,
            source_software="Excel/Unknown",
            reasons=["No column headers detected"],
            requires_manual_choice=True,
            sheet_names=sheet_names,
            help_copy=TALLY_HELP_COPY.get(expected_type or "purchase"),
            validation_issues=[
                {
                    "severity": "error",
                    "code": "no_headers",
                    "message": (
                        "Could not find a header row. If this is a Tally export with a "
                        "merged title block, re-export with a columnar layout or delete "
                        "title rows above the column headers."
                    ),
                }
            ],
        )

    return detect_register_type(
        headers=headers,
        sample_rows=sample_rows,
        sheet_names=sheet_names,
        title_texts=title_texts,
        expected_type=expected_type,
    )
