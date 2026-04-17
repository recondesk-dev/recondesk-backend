"""Helpers for tests (synthetic data that matches app validation rules)."""

from __future__ import annotations

# Matches GSTIN_STRICT_REGEX in app.services.sanity: state (2) + PAN-like core (10) +
# entity [1-9A-Z] + literal Z + checksum [0-9A-Z].
_STATE_MH = "27"
_PAN_CORE = "AABCU9603R"  # 5 letters + 4 digits + 1 letter — known valid PAN pattern

# 35 values for entity slot [1-9A-Z]
_ENTITY_CHARS = [str(d) for d in range(1, 10)] + [chr(ord("A") + i) for i in range(26)]

# 36 values for trailing checksum slot [0-9A-Z]
_CHECK_CHARS = [str(d) for d in range(10)] + [chr(ord("A") + i) for i in range(26)]


def make_valid_test_gstin(index: int) -> str:
    """Return a 15-character GSTIN that passes :func:`app.services.sanity.is_valid_gstin`.

    Uses Maharashtra state code ``27`` and PAN core ``AABCU9603R``. Entity and checksum
    positions are filled so each *index* maps to a distinct GSTIN (for at least 15
    consecutive indices, and broadly for ``index`` in ``0 .. 35*36-1``).
    """
    e = _ENTITY_CHARS[index % 35]
    c = _CHECK_CHARS[(index // 35) % 36]
    return f"{_STATE_MH}{_PAN_CORE}{e}Z{c}"
