"""HSN/SAC → valid GST rate reference for G1M9 validation.

IMPORTANT — refresh periodically
--------------------------------
GST rates change via CBIC rate notifications / GST Council decisions.
This table is a **working reference**, not an official gazette extract.
Revisit against the latest CBIC rate schedule (and rate finder tools)
whenever rates are notified — especially for chapters your clients bill.

Lookup strategy
---------------
Keys may be 2-digit chapters, 4-digit headings, or longer HSN/SAC codes.
``lookup_valid_rates()`` tries the longest matching prefix first so a
specific heading can override its chapter default.

Values are frozensets of valid GST rates in percent (e.g. ``18.0``).
"""

from __future__ import annotations

# Aggregate-turnover → minimum HSN digits for B2B reporting
# (Notification No. 78/2020-Central Tax and subsequent amendments).
# Confirm the client's actual slab before treating digit-length flags
# as definitive compliance failures.
HSN_DIGIT_REQUIREMENTS: dict[str, int] = {
    "upto_5cr": 4,   # preceding FY aggregate turnover ≤ ₹5 crore
    "above_5cr": 6,  # preceding FY aggregate turnover > ₹5 crore
}
DEFAULT_TURNOVER_TIER = "upto_5cr"

# Standard GST rates for snapping / documentation.
STANDARD_GST_RATES: frozenset[float] = frozenset(
    {0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0}
)

# Chapter / heading → valid GST rates (%).
# Prefer 4-digit headings for goods you reconcile often; fall back to
# 2-digit chapter defaults. SAC services live under chapter 99.
HSN_RATE_MAP: dict[str, frozenset[float]] = {
    # ── Plastics (Ch. 39) ─────────────────────────────────────────────
    "39": frozenset({18.0}),
    "3901": frozenset({18.0}),  # polymers of ethylene
    "3917": frozenset({18.0}),  # tubes, pipes of plastics
    "3923": frozenset({18.0}),  # packing articles of plastics
    # ── Iron & steel articles (Ch. 73) ────────────────────────────────
    "73": frozenset({18.0}),
    "7306": frozenset({18.0}),  # tubes / pipes of iron or steel
    "7318": frozenset({18.0}),  # screws, bolts, nuts
    # ── Tools (Ch. 82) ────────────────────────────────────────────────
    "82": frozenset({18.0}),
    "8203": frozenset({18.0}),  # files, rasps, pliers
    # ── Machinery (Ch. 84) ────────────────────────────────────────────
    "84": frozenset({18.0}),
    "8448": frozenset({18.0}),  # textile machinery parts
    # ── Electrical machinery (Ch. 85) ─────────────────────────────────
    "85": frozenset({18.0}),
    "8536": frozenset({18.0}),  # electrical apparatus ≤1000V
    # ── Vehicles / parts (Ch. 87) ─────────────────────────────────────
    "87": frozenset({18.0, 28.0}),
    "8708": frozenset({28.0}),  # motor vehicle parts & accessories
    # ── Common chapters (broad defaults) ──────────────────────────────
    "01": frozenset({0.0, 5.0}),
    "04": frozenset({0.0, 5.0, 12.0}),
    "10": frozenset({0.0, 5.0}),
    "17": frozenset({5.0, 18.0, 28.0}),
    "22": frozenset({0.0, 5.0, 12.0, 18.0, 28.0}),
    "27": frozenset({5.0, 12.0, 18.0}),
    "30": frozenset({5.0, 12.0}),
    "33": frozenset({18.0}),
    "34": frozenset({18.0}),
    "38": frozenset({12.0, 18.0}),
    "40": frozenset({5.0, 12.0, 18.0}),
    "48": frozenset({12.0, 18.0}),
    "49": frozenset({0.0, 12.0}),
    "52": frozenset({5.0}),
    "54": frozenset({5.0, 12.0}),
    "61": frozenset({5.0, 12.0}),
    "62": frozenset({5.0, 12.0}),
    "64": frozenset({5.0, 18.0}),
    "68": frozenset({5.0, 18.0}),
    "69": frozenset({5.0, 12.0, 18.0}),
    "70": frozenset({5.0, 12.0, 18.0}),
    "71": frozenset({0.25, 1.5, 3.0, 5.0}),
    "72": frozenset({18.0}),
    "74": frozenset({18.0}),
    "76": frozenset({18.0}),
    "83": frozenset({18.0}),
    "86": frozenset({5.0, 12.0, 18.0}),
    "90": frozenset({5.0, 12.0, 18.0}),
    "94": frozenset({12.0, 18.0, 28.0}),
    "95": frozenset({12.0, 18.0}),
    "96": frozenset({12.0, 18.0}),
    # ── Services (SAC — Ch. 99) ───────────────────────────────────────
    "99": frozenset({0.0, 5.0, 12.0, 18.0}),
    "9954": frozenset({18.0}),  # construction services
    "9961": frozenset({18.0}),  # wholesale trade services
    "9963": frozenset({5.0, 12.0, 18.0}),  # accommodation / F&B
    "9971": frozenset({18.0}),  # financial services
    "9983": frozenset({18.0}),  # other professional services
    "9987": frozenset({18.0}),  # maintenance & repair
    "9992": frozenset({0.0, 18.0}),  # education
    "9993": frozenset({0.0, 5.0, 12.0}),  # human health
}


def normalise_hsn(raw: object) -> str | None:
    """Return digits-only HSN/SAC, or ``None`` if empty / non-numeric."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        s = str(raw)
    elif isinstance(raw, float):
        if raw != raw:  # NaN
            return None
        if raw == int(raw):
            s = str(int(raw))
        else:
            s = str(raw)
    else:
        s = str(raw).strip()
    if not s or s.lower() in {"nan", "none", "null", "na", "n/a", "-"}:
        return None
    # Keep digits only (drop spaces, slashes, dots from "8203.00" / "8203 ")
    if "." in s:
        # Excel sometimes stores HSN as float → "8203.0"
        try:
            as_float = float(s)
            if as_float == int(as_float):
                s = str(int(as_float))
        except (TypeError, ValueError):
            pass
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None


def hsn_raw_is_missing(raw: object) -> bool:
    """True when *raw* represents an absent / placeholder HSN value."""
    if raw is None:
        return True
    if isinstance(raw, bool):
        return True
    if isinstance(raw, float) and raw != raw:  # NaN
        return True
    s = str(raw).strip()
    if not s:
        return True
    return s.lower() in {"nan", "none", "null", "na", "n/a", "-", "--"}


def lookup_valid_rates(hsn: str) -> frozenset[float] | None:
    """Return valid GST rates for *hsn*, longest-prefix match first.

    Returns ``None`` when no chapter/heading in the reference matches.
    """
    code = normalise_hsn(hsn)
    if not code:
        return None
    # Exact, then shorten one digit at a time down to chapter (2 digits).
    for n in range(len(code), 1, -1):
        rates = HSN_RATE_MAP.get(code[:n])
        if rates is not None:
            return rates
    return None


def required_hsn_digits(turnover_tier: str = DEFAULT_TURNOVER_TIER) -> int:
    """Minimum HSN digit length for the given turnover tier."""
    return HSN_DIGIT_REQUIREMENTS.get(
        turnover_tier, HSN_DIGIT_REQUIREMENTS[DEFAULT_TURNOVER_TIER]
    )


__all__ = [
    "HSN_RATE_MAP",
    "HSN_DIGIT_REQUIREMENTS",
    "DEFAULT_TURNOVER_TIER",
    "STANDARD_GST_RATES",
    "normalise_hsn",
    "hsn_raw_is_missing",
    "lookup_valid_rates",
    "required_hsn_digits",
]
