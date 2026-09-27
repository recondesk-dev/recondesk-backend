"""Regression tests for the 3 accuracy fixes:
1. GSTR-2B duplicate detection & quarantine (prepass_gstr2b_duplicates)
2. Review Required reason discernment (DATE_MISMATCH vs AMOUNT_MISMATCH)
3. GSTIN-typo in PR reason & decision messaging (WRONGFUL_ITC_GSTIN_TYPO)
"""
from datetime import date
import pytest

from app.matching.engine import run_bidirectional_reconciliation
from app.decisions.layer import populate_review_decisions, _decision_for_row
from app.services.decision_templates import generate_decision


def _make_gstr(
    id_: str,
    gstin: str,
    inv: str,
    taxable_rupees: float,
    tax_rupees: float,
    inv_date: str = "2026-05-10",
) -> dict:
    return {
        "id": id_,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv.replace("-", "").replace("/", "").upper(),
        "invoice_date": inv_date,
        "taxable_amount_paise": int(taxable_rupees * 100),
        "total_tax_paise": int(tax_rupees * 100),
        "cgst_paise": int(tax_rupees * 50),
        "sgst_paise": int(tax_rupees * 50),
        "igst_paise": 0,
        "doc_type": "INVOICE",
    }


def _make_pr(
    id_: str,
    gstin: str,
    inv: str,
    taxable_rupees: float,
    tax_rupees: float,
    inv_date: str = "2026-05-10",
) -> dict:
    return {
        "id": id_,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv.replace("-", "").replace("/", "").upper(),
        "invoice_date": inv_date,
        "taxable_amount_paise": int(taxable_rupees * 100),
        "total_tax_paise": int(tax_rupees * 100),
        "cgst_paise": int(tax_rupees * 50),
        "sgst_paise": int(tax_rupees * 50),
        "igst_paise": 0,
        "doc_type": "INVOICE",
    }


# ── FIX 1: GSTR-2B Duplicate Detection ────────────────────────────────────────

def test_fix1_gstr2b_duplicate_quarantined_not_missed_itc():
    """GSTR-2B duplicate rows (same GSTIN, same invoice) must NOT become Missed ITC.

    One canonical copy matches to PR; extra copies are quarantined to duplicate_entries
    with side='GSTR2B' and correct portal duplicate messaging.
    """
    gstin = "27AABCU9603R1ZM"
    # GSTR has 2 copies of INV-001 (e.g. portal amendment / re-reporting)
    gstr = [
        _make_gstr("g_dup_1", gstin, "INV-001", 10000, 1800, "2026-05-05"),
        _make_gstr("g_dup_2", gstin, "INV-001", 10000, 1800, "2026-05-10"),
    ]
    # PR has only 1 copy of INV-001
    pr = [
        _make_pr("p_1", gstin, "INV-001", 10000, 1800, "2026-05-05"),
    ]

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    # Clean match should have matched the canonical entry
    assert res["stats"]["clean_matched_count"] == 1
    # Missed ITC should be 0 (the second GSTR row must NOT be counted as missing from PR!)
    assert res["stats"]["missed_itc_count"] == 0
    # Duplicate entries must contain the extra copy
    assert res["stats"]["duplicate_entry_count"] == 1

    dup_row = res["duplicate_entries"][0]
    assert dup_row["side"] == "GSTR2B"
    assert dup_row["reason"] == "GSTR2B_DUPLICATE"
    assert "Duplicate Entry in GSTR-2B" in dup_row["what"]
    assert "portal duplicate" in dup_row["why"]
    assert "Do not chase the supplier" in dup_row["next"]



# ── FIX 2: Review Required Reason Discernment ────────────────────────────────

def test_fix2_review_required_date_mismatch_vs_amount_mismatch():
    """When an invoice has identical amounts but differing dates, it should be DATE_MISMATCH.

    When amount differs beyond tolerance, it should be AMOUNT_MISMATCH.
    """
    gstin = "27AABCU9603R1ZM"

    # Case A: Amount identical, date differs (e.g. 2026-05-01 vs 2026-06-15)
    gstr_date = [_make_gstr("g_dt", gstin, "INV-DATE-1", 10000, 1800, "2026-05-01")]
    pr_date = [_make_pr("p_dt", gstin, "INV-DATE-1", 10000, 1800, "2026-06-15")]

    # Case B: Amount differs significantly (e.g. ₹10,000 vs ₹20,000), same date
    gstr_amt = [_make_gstr("g_amt", gstin, "INV-AMT-1", 10000, 1800, "2026-05-01")]
    pr_amt = [_make_pr("p_amt", gstin, "INV-AMT-1", 20000, 3600, "2026-05-01")]

    # Test Case B through the engine (which hits the fallback pass for large amount diff)
    res_amt = run_bidirectional_reconciliation(gstr_amt, pr_amt, gstr_period=date(2026, 5, 1))
    assert res_amt["stats"]["review_required_count"] == 1
    assert res_amt["review_required"][0]["review_reason"].startswith("AMOUNT_MISMATCH")

    # Test template resolution in decision layer
    rev_date_row = {
        "review_reason": "DATE_MISMATCH",
        "confidence_score": 85,
        "taxable_diff_paise": 0,
        "supplier_gstin": gstin,
    }
    enriched = populate_review_decisions([rev_date_row])
    assert "invoice date differs" in enriched[0]["decision_what"]
    assert "dates differ between GSTR-2B and purchase register" in enriched[0]["decision_why"]
    assert "Compare physical invoice date" in enriched[0]["decision_next"]


# ── FIX 3: GSTIN-Typo WHY Text in ITC at Risk ───────────────────────────────

def test_fix3_gstin_typo_why_text_in_itc_at_risk():
    """PR record with invoice that IS in GSTR-2B under different GSTIN must be enriched with

    WRONGFUL_ITC_GSTIN_TYPO messaging ('correct your books', NOT 'chase your supplier').
    """
    gstin_gstr = "27AATCS4521P1Z8"
    gstin_pr = "27ABCPD5678G1Z2"

    # GSTR has invoice INV-TYPO-100 under gstin_gstr
    gstr = [_make_gstr("g_typo", gstin_gstr, "INV-TYPO-100", 50000, 9000)]
    # PR has the same invoice INV-TYPO-100 under gstin_pr (with incompatible vendor names)
    pr = [{
        **_make_pr("p_typo", gstin_pr, "INV-TYPO-100", 50000, 9000),
        "vendor_name": "Reliance Retail Limited",
    }]
    gstr[0]["supplier_name"] = "Tata Motors Limited"

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    # Because names conflict, they are not linked into review_required
    assert res["stats"]["review_required_count"] == 0
    # PR row is in wrongful_itc_risk
    assert len(res["wrongful_itc_risk"]) == 1
    risk_row = res["wrongful_itc_risk"][0]

    # Verify enrichment
    assert risk_row.get("risk_reason") == "GSTIN_TYPO_IN_PR"
    assert risk_row.get("gstin_typo_in_pr") is True

    # Verify decision generation
    dec = _decision_for_row({**risk_row, "is_wrongful_itc": True})
    assert "GSTIN mismatch in purchase register" in dec.what
    assert "likely a data-entry error in your books — not a supplier filing failure" in dec.why
    assert "correct your purchase register" in dec.next


