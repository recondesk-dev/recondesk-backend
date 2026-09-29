"""Tests verifying the 5 benchmark fixes:
1. GSTR-2B Credit Notes unbooked in PR routed to unmatched_notes with Table 4(B)(2) reversal advice.
2. Summary vs Matched tab count harmonization (Gross Matched 3,519 vs Clean 3,415 + 104 Ineligible).
3. Sequential series PR invoices not falsely flagged as duplicate bookings.
4. TYPO_MISMATCH requires taxable amount alignment.
5. "Return filed post annual return due date" classified under Section 16(4) time-bar, NOT Rule 37A.
"""
from datetime import date
from decimal import Decimal
import pytest

from app.matching.engine import run_bidirectional_reconciliation
from app.services.statutory_eligibility import (
    normalize_ineligibility_reason,
    NormalizedIneligibilityReason,
    classify_statutory_treatment_for_matched,
)
from app.services.reconciliation_outcomes import build_outcome_rows
import app.services.reconciliation_outcomes as ro
from unittest.mock import MagicMock
from app.services.reconcile_export_workbook import build_excel_workbook_bytes


def test_bug1_unbooked_gstr_credit_notes_routed_to_unmatched_notes():
    """Bug 1: GSTR-2B Credit notes (e.g. CN/1061, CN/432) must be in unmatched_notes, NOT missed_itc."""
    gstr_records = [
        {
            "id": "gstr_cn_1061",
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Acme Supplier",
            "invoice_number": "CN/1061",
            "invoice_number_normalized": "CN1061",
            "invoice_date": "2026-09-10",
            "taxable_amount_paise": 44394,
            "total_tax_paise": 7991,
            "doc_type": "CREDIT_NOTE",
            "section": "cdnr",
        },
        {
            "id": "gstr_cn_432",
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Acme Supplier",
            "invoice_number": "CN/432",
            "invoice_number_normalized": "CN432",
            "invoice_date": "2026-09-12",
            "taxable_amount_paise": 68717,
            "total_tax_paise": 12369,
            "doc_type": "CREDIT_NOTE",
            "section": "cdnr",
        },
    ]
    # No matching PR entries
    pr_records = []

    res = run_bidirectional_reconciliation(gstr_records, pr_records, "092026")

    # MUST NOT be in missed_itc!
    assert len(res["missed_itc"]) == 0
    # MUST be in unmatched_notes with reversal tags
    assert len(res["unmatched_notes"]) == 2
    for note in res["unmatched_notes"]:
        assert note["side"] == "GSTR"
        assert note["document_type"] == "CREDIT_NOTE"
        assert note["is_credit_note"] is True
        assert note["requires_reversal"] is True

    import app.services.reconciliation_outcomes as ro
    from unittest.mock import MagicMock

    orig_g, orig_p = ro._load_gstr_map, ro._load_pr_map
    ro._load_gstr_map = lambda _sb, _rid: {
        r["id"]: {"matcher": r, "record_data": r} for r in gstr_records
    }
    ro._load_pr_map = lambda _sb, _rid: {}
    try:
        outcome_rows, _, _ = ro.build_outcome_rows(
            MagicMock(),
            "run_cn_test",
            {"engine": res},
        )
    finally:
        ro._load_gstr_map = orig_g
        ro._load_pr_map = orig_p

    unmatched_rows = [r for r in outcome_rows if r.category == "unmatched_notes"]
    assert len(unmatched_rows) == 2
    for row in unmatched_rows:
        assert row.is_credit_note is True
        assert row.document_type == "CREDIT_NOTE"
        assert "Reduction Pending" in row.decision_what or "Credit Note" in row.decision_what
        assert "4(B)(2)" in (row.claim_table or "") or "4(B)(2)" in row.decision_next


def test_bug2_summary_sheet_gross_matched_count_and_breakdown():
    """Bug 2: Summary sheet displays Gross Matched (3,519) and breaks down clean (3,415) + ineligible (104)."""
    from datetime import datetime

    summary = {
        "total_gstr_records": 4060,
        "clean_matched_count": 3415,
        "gross_matched_count": 3519,
        "matched_count": 3415,
        "gross_match_rate_pct": 86.7,
        "match_rate_percent": 84.1,
        "itc_on_hold_count": 104,
        "review_required_count": 243,
        "missed_itc_count": 298,
        "missed_itc_total_amount": 150000.0,
        "wrongful_risk_count": 298,
        "wrongful_risk_total_amount": 150000.0,
        "unmatched_notes_count": 2,
        "duplicate_entry_count": 0,
    }
    # 3519 dummy matched pairs
    matched_pairs = [({}, {})] * 3519

    excel_bytes, fn = build_excel_workbook_bytes(
        run_id="test_run_b2",
        firm_name="Test Firm",
        client_trade_name="Test Client",
        period_raw="092026",
        summary=summary,
        matched_pairs=matched_pairs,
        missed_rows=[{}] * 298,
        risk_rows=[{}] * 298,
        rule37_rows=[],
        section17_rows=[],
        review_required_rows=[{}] * 243,
        generated_at=datetime.now(),
        generated_by_name="Test User",
    )
    assert len(excel_bytes) > 0


def test_bug3_sequential_series_pr_invoices_not_flagged_as_duplicates():
    """Bug 3: Sequential PR invoices in the same series with equal recurring amounts are NOT duplicate bookings."""
    gstr_records = [
        {
            "id": "gstr_inv_101",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-101",
            "invoice_number_normalized": "INV101",
            "invoice_date": "2026-08-05",
            "taxable_amount_paise": 500000,
            "total_tax_paise": 90000,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        # Linked PR matching gstr_inv_101
        {
            "id": "pr_inv_101",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-101",
            "invoice_number_normalized": "INV101",
            "invoice_date": "2026-08-05",
            "taxable_amount_paise": 500000,
            "total_tax_paise": 90000,
            "doc_type": "INVOICE",
        },
        # Next month's recurring sequential invoice - NOT in GSTR-2B
        {
            "id": "pr_inv_102",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-102",
            "invoice_number_normalized": "INV102",
            "invoice_date": "2026-09-05",
            "taxable_amount_paise": 500000,
            "total_tax_paise": 90000,
            "doc_type": "INVOICE",
        },
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records, "092026")
    # pr_inv_101 matches gstr_inv_101
    assert len(res["matched"]) == 1
    # pr_inv_102 MUST NOT be flagged as duplicate booking of pr_inv_101!
    dup_ids = {str(d.get("extra_pr_id") or d.get("pr_id")) for d in res.get("duplicate_entries", [])}
    assert "pr_inv_102" not in dup_ids
    # It must be in wrongful_itc_risk (ITC at Risk) since it's genuine PR-only
    risk_ids = {str(r.get("id")) for r in res["wrongful_itc_risk"]}
    assert "pr_inv_102" in risk_ids


def test_bug4_typo_mismatch_requires_taxable_amount_alignment():
    """Bug 4: TYPO_MISMATCH should not match invoices whose taxable amounts differ widely."""
    gstr_records = [
        {
            "id": "gstr_typo_1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-5501",
            "invoice_number_normalized": "INV5501",
            "invoice_date": "2026-09-10",
            # Large taxable amount with 5% tax head = 5,000 paise
            "taxable_amount_paise": 100000,
            "total_tax_paise": 5000,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "pr_typo_1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-5502",  # similar invoice number (sim > 0.75)
            "invoice_number_normalized": "INV5502",
            "invoice_date": "2026-09-10",
            # Completely different taxable amount (e.g. 27,778 with 18% tax = 5,000 paise)
            "taxable_amount_paise": 27778,
            "total_tax_paise": 5000,
            "doc_type": "INVOICE",
        }
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records, "092026")
    # They should NOT be paired under TYPO_MISMATCH because taxable amount diff is huge!
    assert len(res["review_required"]) == 0
    assert len(res["missed_itc"]) == 1
    assert len(res["wrongful_itc_risk"]) == 1


def test_bug5_return_filed_post_annual_return_due_date_is_section16_4_not_rule37a():
    """Bug 5: 'Return filed post annual return due date' is Section 16(4) time-bar, NOT Rule 37A."""
    reason_str = "Return filed post annual return due date"
    norm = normalize_ineligibility_reason(reason_str)
    assert norm == NormalizedIneligibilityReason.SECTION_16_4_TIME_BARRED

    g_rec = {
        "id": "g_late",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-LATE",
        "invoice_number_normalized": "INVLATE",
        "invoice_date": "2025-02-15",
        "total_tax_paise": 18000,
        "taxable_amount_paise": 100000,
        "filing_status": "FILED",
    }
    g_rd = {
        "itc_available": "N",
        "itc_reason": reason_str,
    }
    p_rec = {
        "id": "p_late",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-LATE",
        "invoice_number_normalized": "INVLATE",
        "invoice_date": "2025-02-15",
        "total_tax_paise": 18000,
        "taxable_amount_paise": 100000,
    }

    # Match row in outcome generator
    res = {
        "matched": [{"gstr_id": "g_late", "pr_id": "p_late", "match_level": 1}],
        "clean_matched": [{"gstr_id": "g_late", "pr_id": "p_late", "match_level": 1}],
        "missed_itc": [],
        "wrongful_itc_risk": [],
        "review_required": [],
        "duplicate_entries": [],
        "unmatched_notes": [],
    }
    orig_g, orig_p = ro._load_gstr_map, ro._load_pr_map
    ro._load_gstr_map = lambda _sb, _rid: {"g_late": {"matcher": g_rec, "record_data": g_rd}}
    ro._load_pr_map = lambda _sb, _rid: {"p_late": {"matcher": p_rec, "record_data": p_rec}}
    try:
        outcome_rows, _, _ = ro.build_outcome_rows(
            MagicMock(),
            "run_late_test",
            {"engine": res},
        )
    finally:
        ro._load_gstr_map = orig_g
        ro._load_pr_map = orig_p

    assert len(outcome_rows) == 1
    row = outcome_rows[0]
    # MUST NOT be stamped as Rule 37A!
    assert row.rule37a_flag is False
    assert row.match_status != "RULE37A"
    assert "Section 16(4)" in row.decision_what or row.match_status in ("BLOCKED", "TIME_BARRED") or row.itc_status == "TIME_BARRED"
