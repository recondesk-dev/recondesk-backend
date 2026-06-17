"""Convert INR amount (rupees + paise) to words for tax invoices."""

from __future__ import annotations

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)

_TENS = (
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
)


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    if o == 0:
        return _TENS[t]
    return f"{_TENS[t]} {_ONES[o]}"


def _below_thousand(n: int) -> str:
    if n < 100:
        return _below_hundred(n)
    h, r = divmod(n, 100)
    parts = [f"{_ONES[h]} Hundred"]
    if r:
        parts.append(_below_hundred(r))
    return " ".join(parts)


def _integer_to_words(n: int) -> str:
    if n == 0:
        return "Zero"
    if n < 0:
        return f"Negative {_integer_to_words(-n)}"

    parts: list[str] = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    hundred, n = divmod(n, 100)

    if crore:
        parts.append(f"{_below_thousand(crore)} Crore")
    if lakh:
        parts.append(f"{_below_thousand(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_thousand(thousand)} Thousand")
    if hundred:
        parts.append(f"{_ONES[hundred]} Hundred")
    if n:
        if parts:
            parts.append("and")
        parts.append(_below_hundred(n))

    return " ".join(parts)


def paise_total_to_words(total_paise: int) -> str:
    """Rupees X and Paise Y Only (Indian English invoice style)."""
    if total_paise < 0:
        total_paise = -total_paise
    rupees, paise = divmod(total_paise, 100)
    r_words = _integer_to_words(rupees)
    if paise == 0:
        return f"Rupees {r_words} Only"
    p_words = _below_hundred(paise)
    return f"Rupees {r_words} and Paise {p_words} Only"
