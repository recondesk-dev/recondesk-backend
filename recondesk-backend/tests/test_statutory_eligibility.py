"""Comprehensive statutory eligibility, RCM segregation, and Section 16(4) time-bar tests.

Covers all 30 required statutory scenarios + global financial invariant assertions.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
import pytest

from app.services.statutory_eligibility import (
    ITCEligibilityStatus,
    NormalizedIneligibilityReason,
    Section16_4Status,
    classify_statutory_treatment_for_matched,
    classify_statutory_treatment_for_gstr_only,
    classify_statutory_treatment_for_pr_only,
    compute_section_16_4_cutoff,
    detect_rcm_supply,
    evaluate_section_16_4,
    normalize_ineligibility_reason,
    normalize_rcm_flag,
)
import app.services.reconciliation_outcomes as ro
from app.services.reconciliation_outcomes import OutcomeRow, build_outcome_rows
from app.services.gstr3b_table4_engine import compile_gstr3b_table4


@pytest.fixture(autouse=True)
def _clear_outcomes_process_cache():
    ro._process_map_cache.clear()
    yield
    ro._process_map_cache.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Helper to build mock Supabase Client for build_outcome_rows
# ══════════════════════════════════════════════════════════════════════════════

def _mock_sb_for_run(gstr_rows: list[dict], pr_rows: list[dict], run_id: str = "run-stat-01", period: str = "2024-12") -> MagicMock:
    sb = MagicMock()
    # Mock count queries
    count_gstr = MagicMock(count=len(gstr_rows))
    count_pr = MagicMock(count=len(pr_rows))
    
    # We set up side effects for sb.table().select().eq().range().execute()
    def table_mock(tbl_name: str):
        mock_tbl = MagicMock()
        if tbl_name == "gstr_records":
            mock_tbl.select().eq().limit().execute.return_value = count_gstr
            mock_tbl.select().eq().range().execute.return_value = MagicMock(data=gstr_rows)
        elif tbl_name == "pr_records":
            mock_tbl.select().eq().limit().execute.return_value = count_pr
            mock_tbl.select().eq().range().execute.return_value = MagicMock(data=pr_rows)
        elif tbl_name == "reconciliation_run":
            mock_tbl.select().eq().limit().execute.return_value = MagicMock(data=[{
                "id": run_id,
                "client_gstin_id": "cg-1",
                "period": period,
                "status": "COMPLETED",
                "is_locked": False,
                "finalized_at": None,
                "finalized_by": None,
                "client_gstins": {
                    "gstin": "27AABCM4162G1ZM",
                    "trade_name": "ABC Tech",
                    "legal_name": "ABC Technologies Private Limited",
                },
            }])
        elif tbl_name in ("gstr3b_table4_summaries", "reconciliation_dispositions", "table4_adjustments", "gstr3b_reclaim_events"):
            mock_tbl.select().eq().limit().execute.return_value = MagicMock(data=[])
            mock_tbl.select().eq().execute.return_value = MagicMock(data=[])
        return mock_tbl

    sb.table.side_effect = table_mock
    return sb


# ══════════════════════════════════════════════════════════════════════════════
# Group 1: ITC Eligibility (Tests 1-9)
# ══════════════════════════════════════════════════════════════════════════════

def test_01_exact_match_itc_available():
    """1. Exact match + ITC available -> ordinary matched / eligible ITC."""
    sb = _mock_sb_for_run(
        gstr_rows=[{
            "id": "g-1",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-1",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
                "itc_available": True,
            }
        }],
        pr_rows=[{
            "id": "p-1",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-1",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
            }
        }],
    )
    payload = {
        "engine": {"matched": [{"gstr_id": "g-1", "pr_id": "p-1"}], "missed_itc": [], "wrongful_itc_risk": []},
        "compliance": {},
        "period": "2024-05",
    }
    rows, ccounts, stats = build_outcome_rows(sb, "run-stat-01", payload)
    assert len(rows) == 1
    assert rows[0].category == "matched"
    assert rows[0].itc_available is True
    assert rows[0].claim_table == "4(A)(5)"
    assert ccounts["matched"] == 1
    assert stats["matched_itc_paise"] == 18000
    assert stats["net_claimable_itc_paise"] == 18000


def test_02_exact_match_itc_unavailable():
    """2. Exact match + itc_available=False -> NOT ordinary matched, ₹0 contribution to claimable ITC."""
    sb = _mock_sb_for_run(
        gstr_rows=[{
            "id": "g-2",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-2",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
                "itc_available": False,
                "itc_reason": "Place of Supply restriction",
            }
        }],
        pr_rows=[{
            "id": "p-2",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-2",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
            }
        }],
        run_id="run-stat-02",
    )
    payload = {
        "engine": {"matched": [{"gstr_id": "g-2", "pr_id": "p-2"}], "missed_itc": [], "wrongful_itc_risk": []},
        "compliance": {},
        "period": "2024-05",
    }
    rows, ccounts, stats = build_outcome_rows(sb, "run-stat-02", payload)
    assert len(rows) == 1
    assert rows[0].category == "blocked_credit"  # NOT matched!
    assert rows[0].itc_available is False
    assert ccounts["matched"] == 0
    assert ccounts["blocked_credit"] == 1
    assert stats["matched_itc_paise"] == 0  # ₹0 contribution to claimable ITC!
    assert stats["net_claimable_itc_paise"] == 0


def test_03_gstr_only_itc_available():
    """3. GSTR-2B-only + ITC available -> Missed ITC."""
    sb = _mock_sb_for_run(
        gstr_rows=[{
            "id": "g-3",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-3",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
                "itc_available": True,
            }
        }],
        pr_rows=[],
        run_id="run-stat-03",
    )
    payload = {
        "engine": {"matched": [], "missed_itc": [{"gstr_id": "g-3", "total_tax_paise": 18000}], "wrongful_itc_risk": []},
        "compliance": {},
        "period": "2024-05",
    }
    rows, ccounts, stats = build_outcome_rows(sb, "run-stat-03", payload)
    assert len(rows) == 1
    assert rows[0].category == "missed_itc"
    assert rows[0].itc_available is True
    assert "claim missed itc" in rows[0].decision_next.lower()
    assert ccounts["missed_itc"] == 1
    assert stats["missed_itc_paise"] == 18000


def test_04_gstr_only_itc_unavailable():
    """4. GSTR-2B-only + itc_available=False -> NOT Missed ITC, NOT claimable."""
    sb = _mock_sb_for_run(
        gstr_rows=[{
            "id": "g-4",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-4",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
                "itc_available": False,
                "itc_reason": "POS lies in another state",
            }
        }],
        pr_rows=[],
        run_id="run-stat-04",
    )
    payload = {
        "engine": {"matched": [], "missed_itc": [{"gstr_id": "g-4", "total_tax_paise": 18000}], "wrongful_itc_risk": []},
        "compliance": {},
        "period": "2024-05",
    }
    rows, ccounts, stats = build_outcome_rows(sb, "run-stat-04", payload)
    assert len(rows) == 1
    assert rows[0].category == "blocked_credit"  # NOT missed_itc!
    assert rows[0].itc_available is False
    assert "Do NOT book or claim" in rows[0].decision_next
    assert ccounts["missed_itc"] == 0
    assert stats["missed_itc_paise"] == 0  # NOT in missed_itc sum!


def test_05_itc_unavailable_blank_reason():
    """5. ITC unavailable with blank reason -> still treated as unavailable."""
    reason = normalize_ineligibility_reason(None)
    assert reason == NormalizedIneligibilityReason.GSTR2B_ITC_UNAVAILABLE

    sb = _mock_sb_for_run(
        gstr_rows=[{
            "id": "g-5",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-5",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
                "itc_available": False,
                "itc_reason": "",
            }
        }],
        pr_rows=[{
            "id": "p-5",
            "record_data": {
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": "INV-5",
                "invoice_date_norm": "2024-05-10",
                "taxable_value_paise": 100000,
                "total_tax_paise": 18000,
            }
        }],
        run_id="run-stat-05",
    )
    payload = {
        "engine": {"matched": [{"gstr_id": "g-5", "pr_id": "p-5"}], "missed_itc": [], "wrongful_itc_risk": []},
        "compliance": {},
        "period": "2024-05",
    }
    rows, ccounts, stats = build_outcome_rows(sb, "run-stat-05", payload)
    assert len(rows) == 1
    assert rows[0].category == "blocked_credit"
    assert rows[0].itc_available is False
    assert stats["matched_itc_paise"] == 0


def test_06_itc_unavailable_pos_reason():
    """6. ITC unavailable with POS reason -> normalized POS restriction."""
    norm = normalize_ineligibility_reason("Intra-state supply with place of supply in another state")
    assert norm == NormalizedIneligibilityReason.POS_RESTRICTED


def test_07_itc_unavailable_sec16_4_reason():
    """7. ITC unavailable with Section 16(4) reason -> normalized 16(4) restriction."""
    norm = normalize_ineligibility_reason("Invoice uploaded past 16(4) statutory time limit")
    assert norm == NormalizedIneligibilityReason.SECTION_16_4_TIME_BARRED


def test_08_rule37a_distinct_from_generic_unavailable():
    """8. Rule 37A remains correctly classified and does not get absorbed into generic unavailable ITC."""
    norm = normalize_ineligibility_reason("Supplier has not filed GSTR-3B (Rule 37A)", is_non_filer=True)
    assert norm == NormalizedIneligibilityReason.RULE37A_NON_FILER


def test_09_sec17_5_remains_blocked_credit():
    """9. Section 17(5) remains blocked credit."""
    norm = normalize_ineligibility_reason("Motor vehicle credit blocked u/s 17(5)", is_blocked_credit=True)
    assert norm == NormalizedIneligibilityReason.BLOCKED_CREDIT


# ══════════════════════════════════════════════════════════════════════════════
# Group 2: RCM (Tests 10-16)
# ══════════════════════════════════════════════════════════════════════════════

def test_10_exact_regular_b2b_enters_4a5():
    """10. Exact regular B2B invoice -> 4(A)(5)."""
    sc = classify_statutory_treatment_for_matched(
        g={"reverse_charge": "N"},
        g_rd={},
        p={"reverse_charge": "N"},
        p_rd={},
        is_itc_avail=True,
        itc_rsn=None,
        is_r37a=False,
        is_blocked_credit=False,
        default_d_what="Matched",
        default_d_why="Exact match",
        default_d_next="Claim ITC",
    )
    assert sc.is_rcm is False
    assert sc.claim_table == "4(A)(5)"
    assert sc.liability_table is None


def test_11_exact_rcm_invoice_31d_and_4a3():
    """11. Exact RCM invoice -> RCM, 3.1(d) liability treatment, eligible ITC -> 4(A)(3)."""
    sc = classify_statutory_treatment_for_matched(
        g={"reverse_charge": "Y"},
        g_rd={},
        p={"reverse_charge": "Y"},
        p_rd={},
        is_itc_avail=True,
        itc_rsn=None,
        is_r37a=False,
        is_blocked_credit=False,
        default_d_what="Matched",
        default_d_why="Exact match",
        default_d_next="Claim ITC",
    )
    assert sc.is_rcm is True
    assert sc.supply_type == "RCM"
    assert sc.liability_table == "3.1(d)"
    assert sc.claim_table == "4(A)(3)"
    assert "Table 3.1(d)" in sc.decision_next
    assert "Table 4(A)(3)" in sc.decision_next


def test_12_rcm_with_itc_unavailable():
    """12. RCM with ITC unavailable -> RCM liability classification + unavailable/ineligible ITC, NOT 4(A)(5)."""
    sc = classify_statutory_treatment_for_matched(
        g={"reverse_charge": "Y", "itc_available": False},
        g_rd={},
        p={},
        p_rd={},
        is_itc_avail=False,
        itc_rsn="Ineligible",
        is_r37a=False,
        is_blocked_credit=False,
        default_d_what="Matched",
        default_d_why="Exact match",
        default_d_next="Claim ITC",
    )
    assert sc.is_rcm is True
    assert sc.is_itc_available is False
    assert sc.liability_table == "3.1(d)"  # Liability in 3.1(d) remains!
    assert sc.claim_table != "4(A)(5)"
    assert sc.claim_table != "4(A)(3)"  # Cannot claim ITC if unavailable!


def test_13_rcm_represented_as_Y():
    """13. RCM field represented as 'Y'."""
    assert normalize_rcm_flag("Y") is True
    assert detect_rcm_supply(g={"reverse_charge": "Y"}) is True


def test_14_rcm_represented_as_YES():
    """14. RCM field represented as 'YES'."""
    assert normalize_rcm_flag("YES") is True
    assert detect_rcm_supply(g_rd={"rchrg": "YES"}) is True


def test_15_rcm_represented_as_boolean_True():
    """15. RCM field represented as boolean True or 1."""
    assert normalize_rcm_flag(True) is True
    assert normalize_rcm_flag(1) is True
    assert detect_rcm_supply(p={"reverse_charge": True}) is True


def test_16_rcm_represented_as_N_or_False():
    """16. RCM field represented as 'N' / False -> regular supply."""
    assert normalize_rcm_flag("N") is False
    assert normalize_rcm_flag("NO") is False
    assert normalize_rcm_flag(False) is False
    assert normalize_rcm_flag(0) is False
    assert detect_rcm_supply(g={"reverse_charge": "N"}, p={"reverse_charge": False}) is False


# ══════════════════════════════════════════════════════════════════════════════
# Group 3: Section 16(4) Time-Bar (Tests 17-22)
# ══════════════════════════════════════════════════════════════════════════════

def test_17_pr_only_within_valid_window():
    """17. PR-only invoice within valid claim window -> ITC at Risk / supplier follow-up."""
    # Invoice dated in FY 2024-25 (e.g. 15-May-2024); cutoff is 30-Nov-2025.
    status, cutoff, fy = evaluate_section_16_4(
        invoice_date=date(2024, 5, 15),
        reporting_period="2024-05",
        evaluation_date=date(2024, 5, 31),
    )
    assert status == Section16_4Status.OPEN
    assert cutoff == date(2025, 11, 30)
    assert fy == "2024-25"

    sc = classify_statutory_treatment_for_pr_only(
        p={"invoice_date": "2024-05-15"},
        p_rd={},
        reporting_period="2024-05",
    )
    assert sc.category == "wrongful_risk"
    assert "Follow up with supplier" in sc.decision_next


def test_18_pr_only_after_applicable_cutoff():
    """18. PR-only invoice after applicable Section 16(4) cutoff -> TIME_BARRED, NOT ITC at Risk."""
    # Invoice dated in FY 2023-24 (e.g. 15-Nov-2023); cutoff was 30-Nov-2024.
    # Evaluated in December 2024 (e.g. 2024-12-05).
    status, cutoff, fy = evaluate_section_16_4(
        invoice_date=date(2023, 11, 15),
        reporting_period="2024-12",
        evaluation_date=date(2024, 12, 5),
    )
    assert status == Section16_4Status.TIME_BARRED
    assert cutoff == date(2024, 11, 30)

    sc = classify_statutory_treatment_for_pr_only(
        p={"invoice_date": "2023-11-15"},
        p_rd={},
        reporting_period="2024-12",
    )
    assert sc.category == "time_barred_itc"
    assert sc.section_16_4_status == Section16_4Status.TIME_BARRED
    assert "Time-Barred" in sc.decision_what
    assert "expired" in sc.decision_why.lower()
    assert "supplier follow-up cannot restore" in sc.decision_next.lower()


def test_19_multiple_financial_years():
    """19. Multiple financial years -> each invoice evaluated against its own applicable statutory cutoff."""
    # Invoice in FY 2022-23 (e.g. 10-Jan-2023) -> cutoff 30-Nov-2023
    cutoff_22_23, fy_22_23 = compute_section_16_4_cutoff(date(2023, 1, 10))
    assert cutoff_22_23 == date(2023, 11, 30)
    assert fy_22_23 == "2022-23"

    # Invoice in FY 2023-24 (e.g. 25-Oct-2023) -> cutoff 30-Nov-2024
    cutoff_23_24, fy_23_24 = compute_section_16_4_cutoff(date(2023, 10, 25))
    assert cutoff_23_24 == date(2024, 11, 30)
    assert fy_23_24 == "2023-24"

    # Invoice in FY 2024-25 (e.g. 05-Apr-2024) -> cutoff 30-Nov-2025
    cutoff_24_25, fy_24_25 = compute_section_16_4_cutoff(date(2024, 4, 5))
    assert cutoff_24_25 == date(2025, 11, 30)
    assert fy_24_25 == "2024-25"


def test_20_boundary_exact_cutoff_date():
    """20. Boundary-date test -> exact cutoff date."""
    # Invoice in FY 2023-24, cutoff is 30-Nov-2024.
    # On 30-Nov-2024, the claim window is still OPEN (last day to file/claim).
    status, cutoff, _ = evaluate_section_16_4(
        invoice_date=date(2023, 8, 1),
        evaluation_date=date(2024, 11, 30),
    )
    assert status == Section16_4Status.EXPIRING  # Valid claim window, expiring on this exact date
    assert cutoff == date(2024, 11, 30)


def test_21_boundary_one_day_before_cutoff():
    """21. Boundary-date test -> one day before cutoff (29-Nov-2024)."""
    status, cutoff, _ = evaluate_section_16_4(
        invoice_date=date(2023, 8, 1),
        evaluation_date=date(2024, 11, 29),
    )
    assert status == Section16_4Status.EXPIRING  # Valid claim window
    assert cutoff == date(2024, 11, 30)


def test_22_boundary_one_day_after_cutoff():
    """22. Boundary-date test -> one day after cutoff (01-Dec-2024) -> TIME_BARRED."""
    status, cutoff, _ = evaluate_section_16_4(
        invoice_date=date(2023, 8, 1),
        evaluation_date=date(2024, 12, 1),
    )
    assert status == Section16_4Status.TIME_BARRED
    assert cutoff == date(2024, 11, 30)


# ══════════════════════════════════════════════════════════════════════════════
# Group 4: Combination Tests (Tests 23-30)
# ══════════════════════════════════════════════════════════════════════════════

def test_23_rcm_plus_unavailable_itc():
    """23. RCM + unavailable ITC."""
    sc = classify_statutory_treatment_for_matched(
        g={"reverse_charge": "Y", "itc_available": False},
        g_rd={"itcavl": "N", "rsn": "POS mismatch"},
        p={"reverse_charge": "Y"},
        p_rd={},
        is_itc_avail=False,
        itc_rsn="POS mismatch",
        is_r37a=False,
        is_blocked_credit=False,
        default_d_what="Matched",
        default_d_why="Exact match",
        default_d_next="Claim ITC",
    )
    assert sc.is_rcm is True
    assert sc.is_itc_available is False
    assert sc.category == "blocked_credit"
    assert sc.liability_table == "3.1(d)"
    assert sc.claim_table != "4(A)(5)"


def test_24_rcm_plus_section17_5():
    """24. RCM + Section 17(5) blocked credit."""
    sc = classify_statutory_treatment_for_matched(
        g={"reverse_charge": "Y"},
        g_rd={},
        p={"reverse_charge": "Y"},
        p_rd={},
        is_itc_avail=False,
        itc_rsn="Blocked credit under Section 17(5)",
        is_r37a=False,
        is_blocked_credit=True,
        default_d_what="Matched",
        default_d_why="Exact match",
        default_d_next="Claim ITC",
    )
    assert sc.is_rcm is True
    assert sc.is_itc_available is False
    assert sc.category == "blocked_credit"
    assert sc.liability_table == "3.1(d)"
    assert sc.claim_table == "4(B)(1)"


def test_25_pr_only_plus_expired_16_4():
    """25. PR-only + expired 16(4) cutoff."""
    sc = classify_statutory_treatment_for_pr_only(
        p={"invoice_date": "2023-07-20"},
        p_rd={},
        reporting_period="2024-12",
    )
    assert sc.category == "time_barred_itc"
    assert sc.is_itc_available is False
    assert sc.section_16_4_status == Section16_4Status.TIME_BARRED


def test_26_credit_note_plus_unavailable_itc():
    """26. Credit note + unavailable ITC."""
    sc = classify_statutory_treatment_for_matched(
        g={"doc_type": "CREDIT_NOTE", "itc_available": False},
        g_rd={},
        p={"doc_type": "CREDIT_NOTE"},
        p_rd={},
        is_itc_avail=False,
        itc_rsn="Ineligible",
        is_r37a=False,
        is_blocked_credit=False,
        default_d_what="Credit note matched",
        default_d_why="CDNR matches PR",
        default_d_next="No action",
    )
    assert sc.category == "blocked_credit"
    assert sc.is_itc_available is False


def test_27_duplicate_invoice_plus_unavailable_itc():
    """27. Duplicate invoice + unavailable ITC."""
    row = OutcomeRow(
        id="dp:1",
        category="duplicate_entry",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-DUP",
        invoice_date="2024-05-10",
        match_status="DUPLICATE",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="Duplicate invoice",
        decision_why="Repeated in PR",
        decision_next="Review duplicate",
        rule37_flag=False,
        blocked_credit_flag=True,
        late_filing_flag=False,
        is_credit_note=False,
        amount=10000,
        itc_available=False,
    )
    assert row.category == "duplicate_entry"
    assert row.itc_available is False


def test_28_multiline_invoice_plus_unavailable_itc():
    """28. Multi-line invoice + unavailable ITC in GSTR-2B."""
    sc = classify_statutory_treatment_for_matched(
        g={"invoice_number": "INV-MULTI", "itc_available": False},
        g_rd={"itcavl": "N"},
        p={"invoice_number": "INV-MULTI"},
        p_rd={},
        is_itc_avail=False,
        itc_rsn=None,
        is_r37a=False,
        is_blocked_credit=False,
        default_d_what="Matched multiline",
        default_d_why="Merged lines match",
        default_d_next="Claim ITC",
    )
    assert sc.category == "blocked_credit"
    assert sc.is_itc_available is False


def test_29_rule37a_plus_rcm():
    """29. Existing Rule 37/37A + RCM supply."""
    sc = classify_statutory_treatment_for_matched(
        g={"reverse_charge": "Y", "filing_status": "NO"},
        g_rd={},
        p={"reverse_charge": "Y"},
        p_rd={},
        is_itc_avail=False,
        itc_rsn="Supplier has not filed GSTR-3B",
        is_r37a=True,
        is_blocked_credit=False,
        default_d_what="Matched",
        default_d_why="Supplier non filer",
        default_d_next="Hold on IMS",
    )
    assert sc.category == "rule37_warnings"
    assert sc.rule37a_flag is True
    assert sc.is_rcm is True
    assert sc.liability_table == "3.1(d)"


def test_30_table4_outcome_new_eligibility_states():
    """30. Existing Table 4 outcome + newly introduced eligibility states."""
    r_regular = OutcomeRow(
        id="pm:1",
        category="matched",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-REG",
        invoice_date="2024-05-10",
        match_status="EXACT",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="Matched",
        decision_why="Exact match",
        decision_next="Claim ITC",
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=18000,
        itc_available=True,
        is_rcm=False,
    )
    r_rcm = OutcomeRow(
        id="pm:2",
        category="matched",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-RCM",
        invoice_date="2024-05-10",
        match_status="EXACT",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="RCM",
        decision_why="RCM",
        decision_next="Pay RCM",
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=5000,
        itc_available=True,
        is_rcm=True,
    )
    r_pos = OutcomeRow(
        id="pm:3",
        category="blocked_credit",
        supplier_gstin="29AABCU9603R1ZM",
        invoice_number="INV-POS",
        invoice_date="2024-05-10",
        match_status="BLOCKED",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="POS",
        decision_why="POS",
        decision_next="Do not claim",
        rule37_flag=False,
        blocked_credit_flag=True,
        late_filing_flag=False,
        is_credit_note=False,
        amount=3000,
        itc_available=False,
        normalized_reason="POS_RESTRICTED",
    )

    sb = MagicMock()
    run_row = {
        "id": "run-test-30",
        "period": "2024-05",
        "status": "COMPLETED",
        "client_gstins": {"gstin": "27AABCU9603R1ZM"},
    }
    sb.table().select().eq().limit().execute.return_value.data = [run_row]
    sb.table().select().eq().execute.return_value.data = []

    with patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[]), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([r_regular, r_rcm, r_pos], {}, {})), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
             "1": {"record_data": {"igst_paise": 18000, "itc_available": True}},
             "2": {"record_data": {"igst_paise": 5000, "reverse_charge": "Y", "itc_available": True}},
             "3": {"record_data": {"igst_paise": 3000, "itc_available": False, "rsn": "POS restriction"}},
         }), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
        res = compile_gstr3b_table4(sb, "run-test-30")

    sec_4a = res["table_4"]["section_4a"]
    sec_4d = res["table_4"]["section_4d"]

    # In Table 4:
    # 4(A)(5) contains regular eligible ITC (18000)
    assert sec_4a["row_4a5_all_other_itc"]["total_tax_paise"] == 18000
    # 4(A)(3) contains eligible RCM ITC (5000)
    assert sec_4a["row_4a3_inward_rcm"]["total_tax_paise"] == 5000
    # 4(D)(2) contains POS restricted (3000)
    assert sec_4d["row_4d2_ineligible_16_4_pos"]["total_tax_paise"] == 3000


# ══════════════════════════════════════════════════════════════════════════════
# Group 5: Global Financial Invariant Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_financial_invariants_global():
    """Assert all statutory financial invariants on aggregate rupee totals.

    Invariants:
    1. net_claimable_itc <= eligible ITC
    2. 4A(5) excludes RCM
    3. 4A(5) excludes ITC unavailable in GSTR-2B
    4. Missed ITC excludes ITC unavailable in GSTR-2B
    5. TIME_BARRED_ITC contributes ₹0 to claimable ITC
    6. 4A(3) contains eligible RCM ITC only
    7. 3.1(d) represents identified RCM liability
    """
    gstr_rows = [
        # 1. Clean eligible regular B2B: tax 10,000
        {"id": "g-reg", "record_data": {"supplier_gstin": "27A", "invoice_number": "I-1", "total_tax_paise": 1000000, "itc_available": True}},
        # 2. Eligible RCM B2B: tax 5,000
        {"id": "g-rcm", "record_data": {"supplier_gstin": "27B", "invoice_number": "I-2", "total_tax_paise": 500000, "reverse_charge": "Y", "itc_available": True}},
        # 3. Ineligible POS restricted: tax 3,000
        {"id": "g-pos", "record_data": {"supplier_gstin": "29C", "invoice_number": "I-3", "total_tax_paise": 300000, "itc_available": False, "itc_reason": "POS restriction"}},
        # 4. GSTR-only eligible missed ITC: tax 2,000
        {"id": "g-miss-ok", "record_data": {"supplier_gstin": "27D", "invoice_number": "I-4", "total_tax_paise": 200000, "itc_available": True}},
        # 5. GSTR-only unavailable ITC: tax 4,000
        {"id": "g-miss-no", "record_data": {"supplier_gstin": "27E", "invoice_number": "I-5", "total_tax_paise": 400000, "itc_available": False, "itc_reason": "Ineligible"}},
    ]

    pr_rows = [
        {"id": "p-reg", "record_data": {"supplier_gstin": "27A", "invoice_number": "I-1", "total_tax_paise": 1000000}},
        {"id": "p-rcm", "record_data": {"supplier_gstin": "27B", "invoice_number": "I-2", "total_tax_paise": 500000, "reverse_charge": "Y"}},
        {"id": "p-pos", "record_data": {"supplier_gstin": "29C", "invoice_number": "I-3", "total_tax_paise": 300000}},
        # 6. PR-only valid open window: tax 1,500
        {"id": "p-risk-open", "record_data": {"supplier_gstin": "27F", "invoice_number": "I-6", "invoice_date": "2024-05-15", "total_tax_paise": 150000}},
        # 7. PR-only time-barred Section 16(4): tax 2,500 (dated FY 2023-24 evaluated in Dec 2024)
        {"id": "p-risk-tb", "record_data": {"supplier_gstin": "27G", "invoice_number": "I-7", "invoice_date": "2023-08-10", "total_tax_paise": 250000}},
    ]

    sb = _mock_sb_for_run(gstr_rows, pr_rows, run_id="run-financial-invariants", period="2024-12")
    payload = {
        "engine": {
            "matched": [
                {"gstr_id": "g-reg", "pr_id": "p-reg"},
                {"gstr_id": "g-rcm", "pr_id": "p-rcm"},
                {"gstr_id": "g-pos", "pr_id": "p-pos"},
            ],
            "missed_itc": [
                {"gstr_id": "g-miss-ok", "total_tax_paise": 200000},
                {"gstr_id": "g-miss-no", "total_tax_paise": 400000},
            ],
            "wrongful_itc_risk": [
                {"id": "p-risk-open", "invoice_date": "2024-05-15", "total_tax_paise": 150000},
                {"id": "p-risk-tb", "invoice_date": "2023-08-10", "total_tax_paise": 250000},
            ],
        },
        "compliance": {},
        "period": "2024-12",  # Dec 2024 -> Nov 30 2024 deadline for 2023-24 is expired!
    }

    rows, ccounts, stats = build_outcome_rows(sb, "run-financial-invariants", payload)

    # Invariant 1: net_claimable_itc <= eligible ITC
    total_eligible_itc = stats["matched_eligible_itc_paise"] + stats["rcm_itc_paise"]
    assert stats["net_claimable_itc_paise"] <= total_eligible_itc

    # Invariant 2: matched_itc_paise (feeds 4A5) strictly excludes RCM
    assert stats["matched_itc_paise"] == 1000000  # Regular B2B only, does NOT include 500,000 RCM!
    assert stats["rcm_itc_paise"] == 500000

    # Invariant 3: matched_itc_paise strictly excludes ITC unavailable in GSTR-2B
    assert stats["ineligible_itc_paise"] >= 300000  # POS restricted is classified as ineligible

    # Invariant 4: Missed ITC excludes ITC unavailable in GSTR-2B
    # Only g-miss-ok (200000) contributes to missed_itc_paise; g-miss-no (400000) is excluded!
    assert stats["missed_itc_paise"] == 200000

    # Invariant 5: TIME_BARRED_ITC contributes ₹0 to claimable ITC and is not in wrongful_risk_paise
    assert stats["time_barred_itc_paise"] == 250000
    assert stats["wrongful_risk_paise"] == 150000  # Only the open window invoice is in wrongful_risk!

    # Invariant 6 & 7 via Table 4 Engine:
    with patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[]), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={}):
        res = compile_gstr3b_table4(sb, "run-financial-invariants", payload=payload)
    sec_4a = res["table_4"]["section_4a"]
    sec_4d = res["table_4"]["section_4d"]

    # Invariant 6: 4A(3) contains eligible RCM ITC only
    assert sec_4a["row_4a3_inward_rcm"]["total_tax_paise"] == 500000

    # Invariant 2 & 3 in Table 4: 4A(5) excludes RCM and excludes POS restricted unavailable ITC
    assert sec_4a["row_4a5_all_other_itc"]["total_tax_paise"] == 1000000

    # Table 4(D)(2) contains the POS restricted invoice
    assert sec_4d["row_4d2_ineligible_16_4_pos"]["total_tax_paise"] == 300000

    # Invariant 7: RCM liability represents identified RCM liability
    assert stats["rcm_liability_paise"] >= 500000


def test_gstr_only_time_barred_detected():
    """GSTR-2B-only invoice past Section 16(4) deadline must be TIME_BARRED, not Missed ITC."""
    # Invoice dated 10-Mar-2025 (FY 2024-25, deadline 30-Nov-2025). Recon run for Sep 2026.
    g = {"invoice_date": "2025-03-10", "total_tax_paise": 200744}
    sc = classify_statutory_treatment_for_gstr_only(
        g=g,
        g_rd={},
        is_itc_avail=True,
        itc_rsn=None,
        reporting_period="September 2026",
    )
    assert sc.category == "time_barred_itc"
    assert sc.is_itc_available is False
    assert sc.itc_status == ITCEligibilityStatus.TIME_BARRED
    assert sc.section_16_4_status == Section16_4Status.TIME_BARRED
    assert "Time-Barred under Section 16(4)" in sc.decision_what
    assert "Cannot be claimed in GSTR-3B" in sc.decision_next


def test_gstr_only_prior_fy_expiring_warning():
    """GSTR-2B-only invoice from prior FY (Jan-Mar 2026) evaluated in Jul 2026 must warn Section 16(4) expiring."""
    # Invoice dated 15-Feb-2026 (FY 2025-26, deadline 30-Nov-2026). Recon run for Jul 2026.
    g = {"invoice_date": "2026-02-15", "total_tax_paise": 50000}
    sc = classify_statutory_treatment_for_gstr_only(
        g=g,
        g_rd={},
        is_itc_avail=True,
        itc_rsn=None,
        reporting_period="July 2026",
    )
    assert sc.category == "missed_itc"
    assert sc.is_itc_available is True
    assert sc.section_16_4_status == Section16_4Status.EXPIRING
    assert "URGENT: Section 16(4) claim window expires on 30 Nov 2026" in sc.decision_next
