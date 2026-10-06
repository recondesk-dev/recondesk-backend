"""Volume-scale regression: amount-only / sign-insensitive false pairings.

At multi-thousand invoice scale, same-GSTIN + similar tax is a coincidental
collision — not identity evidence. GSTR invoices with no genuine PR counterpart
(no matching GSTIN + invoice identity) must fall through to Missed ITC, not
Review Required via CREDIBLE_CANDIDATE C1 or VENDOR_FUZZY.

Also covers the CDNR signed-total demotion bug: equal-magnitude opposite-sign
credit notes must stay Matched (L1/L2), not get pushed into AMOUNT_MISMATCH
review by ``abs(g_total - p_total)`` treating 2× signed totals as a mismatch.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import normalize_invoice


GSTIN = "29AAAAA1234A1Z1"
PERIOD = date(2025, 6, 1)
BASE = date(2025, 6, 10)


def _g(i: int, *, taxable: int, tax: int, inv: str | None = None, doc_type=None):
    # Letter-only invoice ids — no digit cores for format-variant intersection.
    # Encode index in base-26 so each side stays unique without shared numbers.
    def _alpha(n: int) -> str:
        chars = []
        n += 1
        while n:
            n, r = divmod(n - 1, 26)
            chars.append(chr(65 + r))
        return "".join(reversed(chars)) or "A"

    inv = inv or f"GSTRONLY{_alpha(i)}QQ"
    return {
        "id": f"g{i}",
        "supplier_gstin": GSTIN,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": BASE + timedelta(days=(i % 20)),
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2,
        "sgst_paise": tax - tax // 2,
        "igst_paise": 0,
        "doc_type": doc_type,
        "section": "cdnr" if doc_type == "CREDIT_NOTE" else "b2b",
    }


def _p(i: int, *, taxable: int, tax: int, inv: str | None = None):
    def _alpha(n: int) -> str:
        chars = []
        n += 1
        while n:
            n, r = divmod(n - 1, 26)
            chars.append(chr(65 + r))
        return "".join(reversed(chars)) or "A"

    inv = inv or f"PRBOOK{_alpha(i)}ZZ"
    return {
        "id": f"p{i}",
        "supplier_gstin": GSTIN,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": BASE + timedelta(days=(i % 20)),
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2 if tax >= 0 else -((-tax) // 2),
        "sgst_paise": (tax - tax // 2) if tax >= 0 else -(abs(tax) - abs(tax) // 2),
        "igst_paise": 0,
    }


def test_volume_same_gstin_similar_amount_without_invoice_is_missed_itc():
    """500 GSTR orphans + 500 unrelated PR rows sharing GSTIN + tax bands.

    Every GSTR must land in Missed ITC. Zero Review Required from amount-only
    collisions. Scale is intentional — small fixtures hide the false-positive rate.
    """
    n = 500
    gstr = []
    pr = []
    for i in range(n):
        # Shared tax band (~Rs 18k) so amount-only matching would collide heavily.
        tax = 1_800_000 + (i % 50) * 100  # within 5% of neighbours
        taxable = tax * 100 // 18
        gstr.append(_g(i, taxable=taxable, tax=tax))
        # Unrelated PR invoice numbers; same tax band + nearby dates.
        pr.append(_p(i, taxable=taxable, tax=tax))

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]
    assert stats["matched_count"] == 0
    assert stats["review_required_count"] == 0, (
        f"Amount-only false positives created {stats['review_required_count']} "
        f"Review rows; sample reasons="
        f"{[r.get('review_reason') for r in res['review_required'][:10]]}"
    )
    assert stats["missed_itc_count"] == n
    assert stats["wrongful_risk_count"] + stats.get("duplicate_entry_count", 0) == n
    assert stats["sanity_passed"] is True


def test_cdnr_opposite_sign_format_variant_stays_matched_not_review():
    """CDNR + negative PR CN with format-variant invoice → Matched, not Review."""
    gstr = [
        _g(
            1,
            taxable=100_000,
            tax=18_000,
            inv="CN-24-25/1019",
            doc_type="CREDIT_NOTE",
        )
    ]
    pr = [_p(1, taxable=-100_000, tax=-18_000, inv="CN24251019")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["matched_count"] == 1
    assert res["stats"]["review_required_count"] == 0
    assert res["stats"]["missed_itc_count"] == 0
    assert res["stats"]["wrongful_risk_count"] == 0
    assert res["matched"][0]["match_level"] in (1, 2)


def test_leading_zero_portal_artifact_normalizes_to_same_key():
    """``0SI-1798`` and ``SI1798`` share one normalized key (not fuzzy review)."""
    assert normalize_invoice("0SI-1798") == normalize_invoice("SI1798") == "SI1798"
    assert normalize_invoice("0INV/24-25/5024") == normalize_invoice("INV24255024")
    gstr = [_g(1, taxable=100_000, tax=18_000, inv="0SI-1798")]
    pr = [_p(1, taxable=100_000, tax=18_000, inv="SI1798")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["matched_count"] == 1
    assert res["stats"]["review_required_count"] == 0
    assert res["stats"]["missed_itc_count"] == 0
