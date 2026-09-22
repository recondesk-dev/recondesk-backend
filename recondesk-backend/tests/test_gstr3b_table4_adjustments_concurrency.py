"""Phase 5.7 REM-05: Manual Adjustments Optimistic Versioning & Concurrency Lock Tests.

Verifies:
1. Backward compatible adjustment creation (no expected_digest) succeeds.
2. Adjustment creation with matching expected_digest succeeds and advances digest.
3. Adjustment creation with stale expected_digest fails with HTTP 409 Conflict.
4. Concurrency token passed via If-Match HTTP header behaves identically to body field.
5. Concurrent multi-user race condition: exactly one winner at a time, loser receives 409.
6. Deleting non-existent adjustment returns HTTP 404 Not Found.
7. Deleting already soft-deleted adjustment returns HTTP 409 Conflict.
8. Deleting with stale expected_digest returns HTTP 409 Conflict.
9. Finalized / locked runs strictly reject adjustments (create and delete) with HTTP 409.
10. Table 4 workpaper response includes adjustments_digest aligned with active adjustments.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.constants import RunStatus
from app.services.gstr3b_table4_engine import (
    compute_table4_adjustments_digest,
    load_table4_adjustments,
)
from tests.test_gstr3b_finalization_hardening import (
    HardeningInMemorySupabaseClient,
    CLIENT_A_ID,
    USER_ADMIN_ID,
    RUN_COMPLETED_CLEAN,
    RUN_ALREADY_FINAL,
    _mock_reconciliation_payload,
)


@pytest.fixture
def concurrency_db() -> HardeningInMemorySupabaseClient:
    db = HardeningInMemorySupabaseClient()

    # Seed client_gstins
    db.table("client_gstins").insert([
        {
            "id": CLIENT_A_ID,
            "firm_owner_id": USER_ADMIN_ID,
            "gstin": "27AAACB1234A1Z1",
            "legal_name": "Client A Corp",
            "is_active": True,
        }
    ]).execute()

    # Seed reconciliation runs
    db.table("reconciliation_run").insert([
        {
            "id": RUN_COMPLETED_CLEAN,
            "client_gstin_id": CLIENT_A_ID,
            "period": "2026-05",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
            "run_summary": {"clean_matched_count": 10, "matched_itc_paise": 500000},
        },
        {
            "id": RUN_ALREADY_FINAL,
            "client_gstin_id": CLIENT_A_ID,
            "period": "2026-04",
            "status": RunStatus.FINAL,
            "is_locked": True,
            "finalized_at": "2026-05-15T10:00:00Z",
            "finalized_by": USER_ADMIN_ID,
            "run_summary": {"clean_matched_count": 10, "matched_itc_paise": 500000},
        },
    ]).execute()

    # Seed empty adjustments
    db.table("gstr3b_table4_adjustments").rows = []
    db.table("reconciliation_exception_dispositions").rows = []
    db.table("gstr3b_reversal_ledger").rows = []

    return db


@pytest.fixture
def client(concurrency_db: HardeningInMemorySupabaseClient):
    from app.main import app
    from app.auth import get_current_active_user

    async def mock_user():
        return {
            "id": USER_ADMIN_ID,
            "email": "admin@recondesk.in",
            "is_active": True,
            "role": "admin",
        }

    app.dependency_overrides[get_current_active_user] = mock_user

    with patch("app.routers.reconciliation_api.get_supabase", return_value=concurrency_db), \
         patch("app.routers.reconciliation_api.assert_run_accessible", return_value={
             "id": RUN_COMPLETED_CLEAN,
             "client_gstin_id": CLIENT_A_ID,
             "status": RunStatus.COMPLETED,
             "is_locked": False,
         }), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.auth.get_user_role", return_value="admin"), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={}), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
        test_c = TestClient(app)
        yield test_c

    app.dependency_overrides.clear()


# ===========================================================================
# 1. Backward Compatible Creation (No Expected Digest)
# ===========================================================================

def test_1_adjustment_create_without_digest_succeeds_backward_compatible(client, concurrency_db):
    """POST adjustment without expected_digest succeeds and returns new_adjustments_digest."""
    res = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        json={
            "row_id": "4B1",
            "adjustment_type": "ADDITION",
            "statutory_category": "RULE_42_INPUTS",
            "igst": 2500.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "reason": "Rule 42 common credit reversal on exempt supplies",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["row_id"] == "4B1"
    assert data["igst_paise"] == 250000
    assert "new_adjustments_digest" in data
    assert len(data["new_adjustments_digest"]) == 64  # SHA-256


# ===========================================================================
# 2. Matching Digest Creation
# ===========================================================================

def test_2_adjustment_create_with_matching_digest_succeeds(client, concurrency_db):
    """POST adjustment with matching expected_digest succeeds and advances digest."""
    initial_digest = compute_table4_adjustments_digest([], run_id=RUN_COMPLETED_CLEAN)

    res = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        json={
            "row_id": "4A2",
            "adjustment_type": "ADDITION",
            "statutory_category": "IMPORT_SERVICES_RCM",
            "igst": 15000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "reason": "Self-invoiced import of cloud services per Sec 5(3)",
            "expected_digest": initial_digest,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    new_digest = data["new_adjustments_digest"]
    assert new_digest != initial_digest


# ===========================================================================
# 3. Stale Digest Creation Fails with HTTP 409
# ===========================================================================

def test_3_adjustment_create_with_stale_digest_fails_409(client, concurrency_db):
    """POST adjustment with stale/mismatched expected_digest fails closed with HTTP 409."""
    res = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        json={
            "row_id": "4B1",
            "adjustment_type": "ADDITION",
            "statutory_category": "RULE_38_BANKING",
            "igst": 5000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "reason": "Rule 38 50% statutory banking reversal",
            "expected_digest": "deadbeef1234567890abcdefdeadbeef1234567890abcdefdeadbeef12345678",
        },
    )
    assert res.status_code == 409
    assert "changed since last retrieved" in res.json()["detail"].lower()


# ===========================================================================
# 4. If-Match HTTP Header Support
# ===========================================================================

def test_4_adjustment_create_with_if_match_header(client, concurrency_db):
    """If-Match HTTP header is accepted as the concurrency token."""
    initial_digest = compute_table4_adjustments_digest([], run_id=RUN_COMPLETED_CLEAN)

    # 1. Matching header succeeds
    res_ok = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        headers={"If-Match": f'"{initial_digest}"'},
        json={
            "row_id": "4A3",
            "adjustment_type": "ADDITION",
            "statutory_category": "DOMESTIC_RCM",
            "igst": 0.0,
            "cgst": 4500.0,
            "sgst": 4500.0,
            "cess": 0.0,
            "reason": "Domestic RCM supplies under Section 9(3)",
        },
    )
    assert res_ok.status_code == 200, res_ok.text

    # 2. Mismatched header fails with 409
    res_conflict = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        headers={"If-Match": f'"{initial_digest}"'},  # Now stale!
        json={
            "row_id": "4A3",
            "adjustment_type": "ADDITION",
            "statutory_category": "DOMESTIC_RCM",
            "igst": 0.0,
            "cgst": 1000.0,
            "sgst": 1000.0,
            "cess": 0.0,
            "reason": "Second RCM entry on stale state",
        },
    )
    assert res_conflict.status_code == 409


# ===========================================================================
# 5. Multi-User Race Simulation
# ===========================================================================

def test_5_concurrent_multi_user_race_condition(client, concurrency_db):
    """Simulate User A and User B concurrently trying to add adjustments from same baseline."""
    # Both users read the current state
    baseline_digest = compute_table4_adjustments_digest([], run_id=RUN_COMPLETED_CLEAN)

    # User A posts adjustment 1 -> SUCCEEDS
    res_user_a = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        json={
            "row_id": "4B1",
            "adjustment_type": "ADDITION",
            "statutory_category": "RULE_42_INPUTS",
            "igst": 1000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "reason": "User A: Rule 42 exempt turnover reversal",
            "expected_digest": baseline_digest,
        },
    )
    assert res_user_a.status_code == 200
    digest_after_a = res_user_a.json()["new_adjustments_digest"]

    # User B posts adjustment 2 using stale baseline_digest -> FAILS with 409 Conflict
    res_user_b = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        json={
            "row_id": "4B1",
            "adjustment_type": "ADDITION",
            "statutory_category": "RULE_43_CAPITAL_GOODS",
            "igst": 2000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "reason": "User B: Rule 43 capital goods reversal",
            "expected_digest": baseline_digest,
        },
    )
    assert res_user_b.status_code == 409
    assert "changed since last retrieved" in res_user_b.json()["detail"].lower()

    # User B refreshes to digest_after_a and retries -> SUCCEEDS
    res_user_b_retry = client.post(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust",
        json={
            "row_id": "4B1",
            "adjustment_type": "ADDITION",
            "statutory_category": "RULE_43_CAPITAL_GOODS",
            "igst": 2000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "reason": "User B: Rule 43 capital goods reversal",
            "expected_digest": digest_after_a,
        },
    )
    assert res_user_b_retry.status_code == 200
    final_digest = res_user_b_retry.json()["new_adjustments_digest"]
    assert final_digest != digest_after_a


# ===========================================================================
# 6. Delete Non-Existent Adjustment
# ===========================================================================

def test_6_delete_nonexistent_adjustment_returns_404(client, concurrency_db):
    """DELETE non-existent adjustment UUID returns HTTP 404 Not Found."""
    fake_id = str(uuid.uuid4())
    res = client.delete(f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust/{fake_id}")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


# ===========================================================================
# 7. Delete Already Deleted Adjustment Returns 409
# ===========================================================================

def test_7_delete_already_deleted_adjustment_returns_409(client, concurrency_db):
    """DELETE on an already soft-deleted adjustment fails with HTTP 409 Conflict."""
    adj_id = str(uuid.uuid4())
    concurrency_db.table("gstr3b_table4_adjustments").insert({
        "id": adj_id,
        "run_id": RUN_COMPLETED_CLEAN,
        "client_gstin_id": CLIENT_A_ID,
        "tax_period": "2026-05",
        "row_id": "4B1",
        "adjustment_type": "ADDITION",
        "statutory_category": "RULE_42_INPUTS",
        "igst_paise": 100000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "reason": "Initial adjustment to delete",
        "is_deleted": False,
    }).execute()

    # First delete -> 200 OK
    res1 = client.delete(f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust/{adj_id}")
    assert res1.status_code == 200
    assert res1.json()["deleted"] is True

    # Second delete -> 409 Conflict
    res2 = client.delete(f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust/{adj_id}")
    assert res2.status_code == 409
    assert "already been deleted" in res2.json()["detail"].lower()


# ===========================================================================
# 8. Delete With Stale Digest Returns 409
# ===========================================================================

def test_8_delete_with_stale_digest_returns_409(client, concurrency_db):
    """DELETE with a stale expected_digest fails with HTTP 409 Conflict."""
    adj_id = str(uuid.uuid4())
    concurrency_db.table("gstr3b_table4_adjustments").insert({
        "id": adj_id,
        "run_id": RUN_COMPLETED_CLEAN,
        "client_gstin_id": CLIENT_A_ID,
        "tax_period": "2026-05",
        "row_id": "4B1",
        "adjustment_type": "ADDITION",
        "statutory_category": "RULE_42_INPUTS",
        "igst_paise": 100000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "reason": "Adjustment to delete",
        "is_deleted": False,
    }).execute()

    # Pass stale digest
    res = client.delete(
        f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4/adjust/{adj_id}",
        params={"expected_digest": "stale-concurrency-token-999"},
    )
    assert res.status_code == 409
    assert "changed since last retrieved" in res.json()["detail"].lower()

    # Adjustment is still NOT deleted
    remaining = load_table4_adjustments(concurrency_db, RUN_COMPLETED_CLEAN)
    assert len(remaining) == 1


# ===========================================================================
# 9. Finalized Run Rejection
# ===========================================================================

def test_9_locked_finalized_run_rejects_mutations_regardless_of_digest(client, concurrency_db):
    """Locked and finalized runs reject both CREATE and DELETE adjustments with HTTP 409."""
    # 1. CREATE on locked run
    res_create = client.post(
        f"/api/reconcile/runs/{RUN_ALREADY_FINAL}/gstr3b/table4/adjust",
        json={
            "row_id": "4A5",
            "adjustment_type": "ADDITION",
            "statutory_category": "OTHER_MANUAL",
            "igst": 100.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "reason": "Adjustment attempt on finalized run",
        },
    )
    assert res_create.status_code == 409
    assert "finalized reconciliation runs are immutable" in res_create.json()["detail"].lower()

    # 2. DELETE on locked run
    res_delete = client.delete(
        f"/api/reconcile/runs/{RUN_ALREADY_FINAL}/gstr3b/table4/adjust/{uuid.uuid4()}"
    )
    assert res_delete.status_code == 409
    assert "finalized reconciliation runs are immutable" in res_delete.json()["detail"].lower()


# ===========================================================================
# 10. Table 4 Workpaper Response Includes Aligned Adjustments Digest
# ===========================================================================

def test_10_table4_workpaper_response_contains_aligned_adjustments_digest(client, concurrency_db):
    """GET /runs/{run_id}/gstr3b/table4 includes adjustments_digest matching active adjustments."""
    adj_id = str(uuid.uuid4())
    concurrency_db.table("gstr3b_table4_adjustments").insert({
        "id": adj_id,
        "run_id": RUN_COMPLETED_CLEAN,
        "client_gstin_id": CLIENT_A_ID,
        "tax_period": "2026-05",
        "row_id": "4B1",
        "adjustment_type": "ADDITION",
        "statutory_category": "RULE_42_INPUTS",
        "igst_paise": 200000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "reason": "Test active adjustment for digest verification",
        "is_deleted": False,
    }).execute()

    res = client.get(f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/gstr3b/table4")
    assert res.status_code == 200, res.text
    data = res.json()
    assert "adjustments_digest" in data
    assert len(data["adjustments_digest"]) == 64

    # Direct calculation tie-out
    active_adjs = load_table4_adjustments(concurrency_db, RUN_COMPLETED_CLEAN)
    expected_digest = compute_table4_adjustments_digest(active_adjs, run_id=RUN_COMPLETED_CLEAN)
    assert data["adjustments_digest"] == expected_digest
