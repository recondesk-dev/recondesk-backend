"""Tests for Phase 5.5A: Revalidation Core Orchestration Engine.

Verifies:
1. cross-tenant authorization
2. PENDING idempotency
3. concurrent duplicate request behavior
4. business identity matching
5. ephemeral record_id is NOT used
6. duplicate candidate identity is handled safely
7. invoice-date disambiguation
8. ambiguous invoice identity
9. MISSING_2B -> CLEARED
10. MISSING_2B -> PERSISTS
11. MISSING_2B -> CHANGED
12. VALUE_MISMATCH -> CLEARED
13. VALUE_MISMATCH -> CHANGED
14. GSTIN_MISMATCH
15. RULE_37 authoritative result
16. RULE_37A authoritative result
17. SEC_17_5 -> NOT_REVALIDATED
18. TIME_BARRED_16_4 -> NOT_REVALIDATED
19. technical failure -> ERROR (never PERSISTS)
20. finalized source run remains immutable
21. stale target run cannot overwrite newer state
22. source_version protection
23. maker-checker preservation
24. audit event sequence
25. zero Table 4 mutation
26. zero reconciliation outcome mutation
27. no second matcher/reconciliation engine
28. retry after ERROR
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.itc_revalidation_engine import (
    RESULT_CLEARED,
    RESULT_PERSISTS,
    RESULT_CHANGED,
    RESULT_ERROR,
    RESULT_NOT_REVALIDATED,
    STATUS_PENDING,
    STATUS_REVALIDATED,
    STATUS_ERROR,
    find_candidate_outcomes,
    compare_work_item_with_outcome,
    get_latest_eligible_completed_run,
    request_revalidation,
    execute_revalidation,
)
from app.services.reconciliation_outcomes import OutcomeRow
from tests.test_itc_work_items import (
    _build_mock_db,
    CLIENT_ID_1,
    CLIENT_ID_2,
    GSTIN_1,
    GSTIN_2,
    ADMIN_USER_ID,
    STAFF_USER_ID,
    OTHER_FIRM_USER_ID,
    RUN_ID,
)

TARGET_RUN_ID = "run-target-456"

ADMIN_USER = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}
STAFF_USER = {"id": STAFF_USER_ID, "role": "staff", "full_name": "Staff Member"}
OTHER_USER = {"id": OTHER_FIRM_USER_ID, "role": "admin", "full_name": "Other CA"}


def _setup_test_db_and_item(
    exception_type: str = "MISSING_2B",
    is_blocking: bool = False,
    status: str = "OPEN",
    reval_status: str = "NONE",
    itc_amount_paise: int = 500000,
    invoice_number: str = "INV-999",
    invoice_date: str = "2026-08-15",
    vendor_gstin: str = "27AABCT1234A1Z1",
):
    sb = _build_mock_db()

    # Add Target Run to DB
    sb.table("reconciliation_run").rows.append({
        "id": TARGET_RUN_ID,
        "client_gstin_id": CLIENT_ID_1,
        "period": "2026-08",
        "status": "COMPLETED",
        "is_locked": False,
        "created_at": "2026-09-12T10:00:00Z",
        "completed_at": "2026-09-12T10:05:00Z",
    })

    wi_id = str(uuid.uuid4())
    work_item = {
        "id": wi_id,
        "client_gstin_id": CLIENT_ID_1,
        "firm_owner_id": ADMIN_USER_ID,
        "run_id": RUN_ID,
        "record_id": f"pr:{uuid.uuid4()}",
        "exception_type": exception_type,
        "status": status,
        "priority": "HIGH",
        "system_priority": "HIGH",
        "is_blocking": is_blocking,
        "vendor_gstin": vendor_gstin,
        "vendor_name": "Test Vendor",
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "itc_amount_at_stake_paise": itc_amount_paise,
        "revalidation_status": reval_status,
        "revalidation_requested_at": None,
        "revalidation_completed_at": None,
        "revalidation_result": None,
        "source_version": 1,
        "carried_forward_from_id": None,
        "created_at": "2026-09-10T11:00:00Z",
        "updated_at": "2026-09-10T11:00:00Z",
    }
    sb.table("itc_work_items").rows.append(work_item)
    return sb, wi_id


# ---------------------------------------------------------------------------
# Test 1: Cross-Tenant Authorization
# ---------------------------------------------------------------------------
def test_cross_tenant_authorization():
    sb, wi_id = _setup_test_db_and_item()
    with pytest.raises(HTTPException) as exc_info:
        request_revalidation(sb, wi_id, OTHER_USER)
    assert exc_info.value.status_code in (403, 404)



# ---------------------------------------------------------------------------
# Test 2: PENDING Idempotency
# ---------------------------------------------------------------------------
def test_pending_idempotency():
    sb, wi_id = _setup_test_db_and_item()
    res1 = request_revalidation(sb, wi_id, STAFF_USER)
    assert res1["revalidation_status"] == STATUS_PENDING
    assert res1["revalidation_requested_at"] is not None

    events1 = [e for e in sb.table("itc_work_item_events").rows if e["event_type"] == "REVALIDATION_REQUESTED"]
    assert len(events1) == 1

    # Second request on already PENDING item must be idempotent
    res2 = request_revalidation(sb, wi_id, STAFF_USER)
    assert res2["revalidation_status"] == STATUS_PENDING
    events2 = [e for e in sb.table("itc_work_item_events").rows if e["event_type"] == "REVALIDATION_REQUESTED"]
    assert len(events2) == 1  # No duplicate event


# ---------------------------------------------------------------------------
# Test 3: Concurrent Duplicate Request Behavior
# ---------------------------------------------------------------------------
def test_concurrent_duplicate_request_behavior():
    sb, wi_id = _setup_test_db_and_item(reval_status=STATUS_PENDING)
    # When already PENDING, atomic update neq('revalidation_status', 'PENDING') won't update
    item = request_revalidation(sb, wi_id, ADMIN_USER)
    assert item["revalidation_status"] == STATUS_PENDING


# ---------------------------------------------------------------------------
# Test 4: Business Identity Matching
# ---------------------------------------------------------------------------
def test_business_identity_matching():
    outcomes = [
        OutcomeRow(
            id="gstr:111",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV/00999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    candidate, reason = find_candidate_outcomes(outcomes, "27aabct1234a1z1", "INV-00999", "2026-08-15")
    assert candidate is not None
    assert reason is None
    assert candidate.id == "gstr:111"


# ---------------------------------------------------------------------------
# Test 5: Ephemeral record_id is NOT used across runs
# ---------------------------------------------------------------------------
def test_ephemeral_record_id_not_used():
    sb, wi_id = _setup_test_db_and_item()
    # Work item has record_id = "pr:old-uuid-xyz"
    fresh_outcomes = [
        OutcomeRow(
            id="pr:fresh-uuid-999",  # Completely new ephemeral ID in fresh run!
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        request_revalidation(sb, wi_id, STAFF_USER)
        res = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
        assert res["revalidation_result"] == RESULT_CLEARED


# ---------------------------------------------------------------------------
# Test 6: Duplicate Candidate Identity Handled Safely
# ---------------------------------------------------------------------------
def test_duplicate_candidate_identity_safety():
    outcomes = [
        OutcomeRow(
            id="pr:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-10",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        ),
        OutcomeRow(
            id="pr:2",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-20",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        ),
    ]
    # No date supplied -> ambiguous
    cand, reason = find_candidate_outcomes(outcomes, "27AABCT1234A1Z1", "INV-999", None)
    assert cand is None
    assert "AMBIGUOUS" in reason


# ---------------------------------------------------------------------------
# Test 7: Invoice-Date Disambiguation
# ---------------------------------------------------------------------------
def test_invoice_date_disambiguation():
    outcomes = [
        OutcomeRow(
            id="pr:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-10",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        ),
        OutcomeRow(
            id="pr:2",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-20",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        ),
    ]
    cand, reason = find_candidate_outcomes(outcomes, "27AABCT1234A1Z1", "INV-999", "2026-08-20")
    assert cand is not None
    assert reason is None
    assert cand.id == "pr:2"


# ---------------------------------------------------------------------------
# Test 8: Ambiguous Invoice Identity
# ---------------------------------------------------------------------------
def test_ambiguous_invoice_identity():
    outcomes = [
        OutcomeRow(
            id="pr:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-20",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        ),
        OutcomeRow(
            id="pr:2",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-20",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        ),
    ]
    cand, reason = find_candidate_outcomes(outcomes, "27AABCT1234A1Z1", "INV-999", "2026-08-20")
    assert cand is None
    assert "AMBIGUOUS_MULTIPLE_INVOICES_SAME_DATE" in reason
    comparison = compare_work_item_with_outcome({"exception_type": "MISSING_2B"}, cand, reason)
    assert comparison["revalidation_result"] == RESULT_NOT_REVALIDATED


# ---------------------------------------------------------------------------
# Test 9: MISSING_2B -> CLEARED
# ---------------------------------------------------------------------------
def test_missing_2b_cleared():
    item = {"exception_type": "MISSING_2B", "itc_amount_at_stake_paise": 50000}
    outcome = OutcomeRow(
        id="m:1",
        category="matched",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="EXACT",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    res = compare_work_item_with_outcome(item, outcome)
    assert res["revalidation_result"] == RESULT_CLEARED
    assert res["tax_diff_after_paise"] == 0


# ---------------------------------------------------------------------------
# Test 10: MISSING_2B -> PERSISTS
# ---------------------------------------------------------------------------
def test_missing_2b_persists():
    item = {"exception_type": "MISSING_2B", "itc_amount_at_stake_paise": 50000}
    # Outcome is still missed_itc / in PR only
    outcome = OutcomeRow(
        id="pr:101",
        category="missed_itc",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="MISMATCH",
        taxable_value_diff=50000,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=50000,
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    res = compare_work_item_with_outcome(item, outcome)
    assert res["revalidation_result"] == RESULT_PERSISTS


# ---------------------------------------------------------------------------
# Test 11: MISSING_2B -> CHANGED
# ---------------------------------------------------------------------------
def test_missing_2b_changed():
    item = {"exception_type": "MISSING_2B", "itc_amount_at_stake_paise": 50000}
    outcome = OutcomeRow(
        id="m:101",
        category="matched",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="DIFF_AMOUNT",
        taxable_value_diff=20000,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=20000,  # Value mismatch now
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    res = compare_work_item_with_outcome(item, outcome)
    assert res["revalidation_result"] == RESULT_CHANGED
    assert res["new_exception_type"] == "VALUE_MISMATCH"


# ---------------------------------------------------------------------------
# Test 12: VALUE_MISMATCH -> CLEARED
# ---------------------------------------------------------------------------
def test_value_mismatch_cleared():
    item = {"exception_type": "VALUE_MISMATCH", "itc_amount_at_stake_paise": 50000}
    outcome = OutcomeRow(
        id="m:101",
        category="matched",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="EXACT",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=50,  # <= 100 paise tolerance
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    res = compare_work_item_with_outcome(item, outcome)
    assert res["revalidation_result"] == RESULT_CLEARED


# ---------------------------------------------------------------------------
# Test 13: VALUE_MISMATCH -> CHANGED
# ---------------------------------------------------------------------------
def test_value_mismatch_changed():
    item = {"exception_type": "VALUE_MISMATCH", "itc_amount_at_stake_paise": 50000}
    outcome = OutcomeRow(
        id="m:101",
        category="matched",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="DIFF_AMOUNT",
        taxable_value_diff=15000,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=15000,  # Changed from 50000 to 15000
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    res = compare_work_item_with_outcome(item, outcome)
    assert res["revalidation_result"] == RESULT_CHANGED
    assert res["tax_diff_after_paise"] == 15000


# ---------------------------------------------------------------------------
# Test 14: GSTIN_MISMATCH
# ---------------------------------------------------------------------------
def test_gstin_mismatch():
    item = {"exception_type": "GSTIN_MISMATCH", "itc_amount_at_stake_paise": 0}
    clean_outcome = OutcomeRow(
        id="m:1",
        category="matched",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="EXACT",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    assert compare_work_item_with_outcome(item, clean_outcome)["revalidation_result"] == RESULT_CLEARED

    mismatch_outcome = OutcomeRow(
        id="m:2",
        category="gstin_mismatch",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="MISMATCH",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    assert compare_work_item_with_outcome(item, mismatch_outcome)["revalidation_result"] == RESULT_PERSISTS


# ---------------------------------------------------------------------------
# Test 15: RULE_37 Authoritative Result
# ---------------------------------------------------------------------------
def test_rule37_authoritative_result():
    item = {"exception_type": "RULE_37", "itc_amount_at_stake_paise": 10000}
    r37_cleared = OutcomeRow(
        id="m:1",
        category="matched",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="EXACT",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        rule37_flag=False,  # Flag is cleared!
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    assert compare_work_item_with_outcome(item, r37_cleared)["revalidation_result"] == RESULT_CLEARED

    r37_persists = copy.copy(r37_cleared)
    r37_persists.rule37_flag = True
    assert compare_work_item_with_outcome(item, r37_persists)["revalidation_result"] == RESULT_PERSISTS


# ---------------------------------------------------------------------------
# Test 16: RULE_37A Authoritative Result
# ---------------------------------------------------------------------------
def test_rule37a_authoritative_result():
    item = {"exception_type": "RULE_37A", "itc_amount_at_stake_paise": 10000}
    r37a_cleared = OutcomeRow(
        id="m:1",
        category="matched",
        supplier_gstin="27AABCT1234A1Z1",
        invoice_number="INV-999",
        invoice_date="2026-08-15",
        match_status="EXACT",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        rule37_flag=False,
        rule37a_flag=False,  # Cleared!
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=500,
        decision_what="",
        decision_why="",
        decision_next="",
    )
    assert compare_work_item_with_outcome(item, r37a_cleared)["revalidation_result"] == RESULT_CLEARED

    r37a_persists = copy.copy(r37a_cleared)
    r37a_persists.rule37a_flag = True
    assert compare_work_item_with_outcome(item, r37a_persists)["revalidation_result"] == RESULT_PERSISTS


# ---------------------------------------------------------------------------
# Test 17: SEC_17_5 -> NOT_REVALIDATED
# ---------------------------------------------------------------------------
def test_sec_17_5_not_revalidated():
    sb, wi_id = _setup_test_db_and_item(exception_type="SEC_17_5")
    # Requesting revalidation on SEC_17_5 must be rejected with 422
    with pytest.raises(HTTPException) as exc:
        request_revalidation(sb, wi_id, STAFF_USER)
    assert exc.value.status_code == 422
    assert "statutory condition" in exc.value.detail

    # Direct comparison returns NOT_REVALIDATED
    res = compare_work_item_with_outcome({"exception_type": "SEC_17_5"}, None)
    assert res["revalidation_result"] == RESULT_NOT_REVALIDATED


# ---------------------------------------------------------------------------
# Test 18: TIME_BARRED_16_4 -> NOT_REVALIDATED
# ---------------------------------------------------------------------------
def test_time_barred_16_4_not_revalidated():
    sb, wi_id = _setup_test_db_and_item(exception_type="TIME_BARRED_16_4")
    with pytest.raises(HTTPException) as exc:
        request_revalidation(sb, wi_id, STAFF_USER)
    assert exc.value.status_code == 422

    res = compare_work_item_with_outcome({"exception_type": "TIME_BARRED_16_4"}, None)
    assert res["revalidation_result"] == RESULT_NOT_REVALIDATED


# ---------------------------------------------------------------------------
# Test 19: Technical Failure -> ERROR (Never PERSISTS)
# ---------------------------------------------------------------------------
def test_technical_failure_error():
    sb, wi_id = _setup_test_db_and_item()
    request_revalidation(sb, wi_id, STAFF_USER)

    # Force outcome loader to raise technical exception
    with patch("app.services.reconciliation_outcomes.load_payload", side_effect=RuntimeError("Database connection dropped")):
        res = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
        assert res["revalidation_status"] == STATUS_ERROR
        assert res["revalidation_result"] == RESULT_ERROR
        # Strict rule: technical error must NEVER produce PERSISTS
        assert res["revalidation_result"] != RESULT_PERSISTS


# ---------------------------------------------------------------------------
# Test 20: Finalized Source Run Remains Immutable
# ---------------------------------------------------------------------------
def test_finalized_source_run_immutable():
    sb, wi_id = _setup_test_db_and_item()
    # Source RUN_ID is finalized and locked
    src_run = next(r for r in sb.table("reconciliation_run").rows if r["id"] == RUN_ID)
    assert src_run["is_locked"] is True

    initial_t4 = copy.deepcopy(sb.table("gstr3b_table4_summaries").rows)

    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        request_revalidation(sb, wi_id, STAFF_USER)
        execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)

    # Verify source run is 100% untouched
    after_src_run = next(r for r in sb.table("reconciliation_run").rows if r["id"] == RUN_ID)
    assert after_src_run["is_locked"] is True
    # Verify Table 4 is 100% untouched
    assert sb.table("gstr3b_table4_summaries").rows == initial_t4


# ---------------------------------------------------------------------------
# Test 21: Stale Target Run Cannot Overwrite Newer State
# ---------------------------------------------------------------------------
def test_stale_target_run_rejection():
    sb, wi_id = _setup_test_db_and_item()
    # Add a stale target run whose created_at is older than source run
    stale_run_id = "run-stale-000"
    sb.table("reconciliation_run").rows.append({
        "id": stale_run_id,
        "client_gstin_id": CLIENT_ID_1,
        "period": "2026-08",
        "status": "COMPLETED",
        "is_locked": False,
        "created_at": "2026-09-01T10:00:00Z",  # Older than source run 2026-09-10!
        "completed_at": "2026-09-01T10:05:00Z",
    })
    # get_latest_eligible_completed_run must NOT pick stale run
    eligible = get_latest_eligible_completed_run(sb, CLIENT_ID_1, RUN_ID, period="2026-08")
    assert eligible is not None
    assert eligible["id"] != stale_run_id
    assert eligible["id"] == TARGET_RUN_ID


# ---------------------------------------------------------------------------
# Test 22: Source Version Protection
# ---------------------------------------------------------------------------
def test_source_version_protection():
    sb, wi_id = _setup_test_db_and_item()
    item_before = next(r for r in sb.table("itc_work_items").rows if r["id"] == wi_id)
    assert item_before["source_version"] == 1

    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        request_revalidation(sb, wi_id, STAFF_USER)
        res = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
        assert res["source_version"] == 1  # Version lineage preserved


# ---------------------------------------------------------------------------
# Test 23: Maker-Checker Preservation
# ---------------------------------------------------------------------------
def test_maker_checker_preservation():
    # Blocking item: CLEARED moves to READY_FOR_REVIEW for CA approval
    sb, wi_id_blocking = _setup_test_db_and_item(is_blocking=True)
    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        request_revalidation(sb, wi_id_blocking, STAFF_USER)
        res_blocking = execute_revalidation(sb, wi_id_blocking, STAFF_USER, target_run_id=TARGET_RUN_ID)
        # Maker-checker enforced: status is READY_FOR_REVIEW, NOT RESOLVED directly
        assert res_blocking["revalidation_result"] == RESULT_CLEARED
        assert res_blocking["status"] == "READY_FOR_REVIEW"

    # Non-blocking item: CLEARED moves to RESOLVED
    sb2, wi_id_non_blocking = _setup_test_db_and_item(is_blocking=False)
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        request_revalidation(sb2, wi_id_non_blocking, STAFF_USER)
        res_non_blocking = execute_revalidation(sb2, wi_id_non_blocking, STAFF_USER, target_run_id=TARGET_RUN_ID)
        assert res_non_blocking["revalidation_result"] == RESULT_CLEARED
        assert res_non_blocking["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Test 24: Audit Event Sequence
# ---------------------------------------------------------------------------
def test_audit_event_sequence():
    sb, wi_id = _setup_test_db_and_item()
    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        request_revalidation(sb, wi_id, STAFF_USER)
        execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)

    events = [e["event_type"] for e in sb.table("itc_work_item_events").rows if str(e["work_item_id"]) == wi_id]
    assert "REVALIDATION_REQUESTED" in events
    assert "REVALIDATION_STARTED" in events
    assert "REVALIDATION_COMPLETED" in events
    # Check sequence
    req_idx = events.index("REVALIDATION_REQUESTED")
    start_idx = events.index("REVALIDATION_STARTED")
    comp_idx = events.index("REVALIDATION_COMPLETED")
    assert req_idx < start_idx < comp_idx


# ---------------------------------------------------------------------------
# Test 25: Zero Table 4 Mutation
# ---------------------------------------------------------------------------
def test_zero_table4_mutation():
    sb, wi_id = _setup_test_db_and_item()
    t4_before = copy.deepcopy(sb.table("gstr3b_table4_summaries").rows)
    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        request_revalidation(sb, wi_id, STAFF_USER)
        execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)

    assert sb.table("gstr3b_table4_summaries").rows == t4_before


# ---------------------------------------------------------------------------
# Test 26: Zero Reconciliation Outcome Mutation
# ---------------------------------------------------------------------------
def test_zero_reconciliation_outcome_mutation():
    sb, wi_id = _setup_test_db_and_item()
    with patch("app.services.reconciliation_payload_store.save_reconciliation_results") as mock_save:
        request_revalidation(sb, wi_id, STAFF_USER)
        with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
             patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([], {}, {})):
            execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Test 27: No Second Matcher or Reconciliation Engine
# ---------------------------------------------------------------------------
def test_no_second_matcher():
    import app.services.itc_revalidation_engine as eng
    # Ensure it doesn't import matcher matching functions like match_gstr_to_pr
    assert not hasattr(eng, "match_gstr_to_pr")
    assert not hasattr(eng, "execute_reconciliation")


# ---------------------------------------------------------------------------
# Test 28: Retry After ERROR
# ---------------------------------------------------------------------------
def test_retry_after_error():
    sb, wi_id = _setup_test_db_and_item(reval_status=STATUS_ERROR)
    # Work item in ERROR status can be requested for revalidation again
    res = request_revalidation(sb, wi_id, STAFF_USER)
    assert res["revalidation_status"] == STATUS_PENDING


# ---------------------------------------------------------------------------
# Test 29: Newer Authoritative Run Appears Before Result Persistence
# ---------------------------------------------------------------------------
def test_newer_authoritative_run_appears_before_persistence():
    sb, wi_id = _setup_test_db_and_item()
    request_revalidation(sb, wi_id, STAFF_USER)

    # In target run outcomes, it appears CLEARED
    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]

    # Add a newer completed run that finishes while evaluation was in progress
    newer_run_id = "run-newer-789"
    sb.table("reconciliation_run").rows.append({
        "id": newer_run_id,
        "client_gstin_id": CLIENT_ID_1,
        "period": "2026-08",
        "status": "COMPLETED",
        "is_locked": False,
        "created_at": "2026-09-15T12:00:00Z",  # Brand new run!
        "completed_at": "2026-09-15T12:05:00Z",
    })

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        # Execute revalidation specifically targeting older TARGET_RUN_ID (created 2026-09-12)
        res = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)

        # Stale target protection: MUST NOT persist CLEARED!
        assert res["revalidation_result"] is None
        assert res["revalidation_status"] == STATUS_PENDING

        # Verify audit event emitted
        events = [e for e in sb.table("itc_work_item_events").rows if e["event_type"] == "REVALIDATION_STALE_TARGET_SKIPPED"]
        assert len(events) == 1
        assert events[0]["metadata"]["superseding_run_id"] == newer_run_id
        assert events[0]["metadata"]["stale_result"] is True


# ---------------------------------------------------------------------------
# Test 30: Stale Target Cannot Overwrite Newer Run
# ---------------------------------------------------------------------------
def test_stale_target_cannot_overwrite_newer_run():
    sb, wi_id = _setup_test_db_and_item()
    request_revalidation(sb, wi_id, STAFF_USER)

    stale_run_id = "run-old-001"
    sb.table("reconciliation_run").rows.append({
        "id": stale_run_id,
        "client_gstin_id": CLIENT_ID_1,
        "period": "2026-08",
        "status": "COMPLETED",
        "is_locked": False,
        "created_at": "2026-09-01T10:00:00Z",  # Outdated run
        "completed_at": "2026-09-01T10:05:00Z",
    })

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([], {}, {})):
        res = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=stale_run_id)
        # Stale run must be rejected and remain PENDING
        assert res["revalidation_status"] == STATUS_PENDING


# ---------------------------------------------------------------------------
# Test 31: Simultaneous Execute Requests are Idempotent
# ---------------------------------------------------------------------------
def test_simultaneous_execute_requests_idempotent():
    sb, wi_id = _setup_test_db_and_item()
    request_revalidation(sb, wi_id, STAFF_USER)

    # Manually simulate another worker currently holding REVALIDATING claim
    sb.table("itc_work_items").update({"revalidation_status": "REVALIDATING"}).eq("id", wi_id).execute()

    # Second execution request arrives
    res = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
    # Must safely return without executing or crashing
    assert res["revalidation_status"] == "REVALIDATING"


# ---------------------------------------------------------------------------
# Test 32: Execution Retry After Failure
# ---------------------------------------------------------------------------
def test_execution_retry_after_failure():
    sb, wi_id = _setup_test_db_and_item()
    request_revalidation(sb, wi_id, STAFF_USER)

    # First attempt fails with technical error
    with patch("app.services.reconciliation_outcomes.load_payload", side_effect=RuntimeError("Transient network failure")):
        res_fail = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
        assert res_fail["revalidation_status"] == STATUS_ERROR
        assert res_fail["revalidation_result"] == RESULT_ERROR

    # Retry revalidation request
    res_req = request_revalidation(sb, wi_id, STAFF_USER)
    assert res_req["revalidation_status"] == STATUS_PENDING

    # Re-execute successfully
    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        res_success = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
        assert res_success["revalidation_status"] == STATUS_REVALIDATED
        assert res_success["revalidation_result"] == RESULT_CLEARED


# ---------------------------------------------------------------------------
# Test 33: Existing Maker-Checker Transition Enforcement Intact
# ---------------------------------------------------------------------------
def test_existing_maker_checker_transition_enforcement():
    # Blocking item: staff CANNOT mark RESOLVED
    sb, wi_id = _setup_test_db_and_item(is_blocking=True, status="IN_PROGRESS")
    request_revalidation(sb, wi_id, STAFF_USER)

    fresh_outcomes = [
        OutcomeRow(
            id="m:1",
            category="matched",
            supplier_gstin="27AABCT1234A1Z1",
            invoice_number="INV-999",
            invoice_date="2026-08-15",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=5000,
            decision_what="",
            decision_why="",
            decision_next="",
        )
    ]
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(fresh_outcomes, {}, {})):
        res = execute_revalidation(sb, wi_id, STAFF_USER, target_run_id=TARGET_RUN_ID)
        # Enforces Phase 5.2 maker-checker: strictly READY_FOR_REVIEW
        assert res["status"] == "READY_FOR_REVIEW"
        assert res["revalidation_result"] == RESULT_CLEARED

