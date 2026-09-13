"""Phase 4C.1: Backend Finalization Hardening Regression Tests.

Verifies:
1. COMPLETED run successfully finalizes through POST /api/reconcile/runs/{id}/finalize
   (specifically proving the previous UnboundLocalError is fixed).
2. Blocked run returns HTTP 422.
3. Successful finalization creates the authoritative Table 4 snapshot in gstr3b_table4_summaries.
4. Successful finalization locks the run (status=FINAL, is_locked=True).
5. 4B2 entries are registered exactly once in gstr3b_reversal_ledger.
6. 17(5)/4B1 and 16(4)/4D2 do NOT create reversal ledger entries.
7. Repeated finalization is idempotent and does not create duplicate snapshots/ledger rows.
8. Concurrent finalization handles optimistic concurrency with exactly one winner (HTTP 409).
9. Unauthorized cross-client finalization is rejected with HTTP 403/404.
10. Existing finalized run remains immutable.
11. Snapshot failure preserves COMPLETED/unlocked run state (no partial locked state).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.constants import RunStatus
from app.services.gstr3b_reversal_ledger import ReversalProvenanceType, ReversalStatus
from tests.test_gstr3b_reversal_ledger import InMemorySupabaseClient, InMemoryTable

CLIENT_A_ID = "00000000-0000-0000-0000-000000000001"
CLIENT_B_ID = "00000000-0000-0000-0000-000000000002"
USER_ADMIN_ID = "00000000-0000-0000-0000-000000000001"
USER_STAFF_ID = "00000000-0000-0000-0000-000000000002"

RUN_COMPLETED_CLEAN = "11111111-1111-1111-1111-111111111111"
RUN_BLOCKED = "22222222-2222-2222-2222-222222222222"
RUN_ALREADY_FINAL = "33333333-3333-3333-3333-333333333333"
RUN_CLIENT_B = "44444444-4444-4444-4444-444444444444"


class HardeningInMemoryTable(InMemoryTable):
    """InMemoryTable supporting PostgREST count parameter."""

    def select(self, columns: str = "*", count: str | None = None, **kwargs):
        self._filters = []
        self._order_by = []
        self._limit_val = None
        self._count = count
        return self

    def execute(self):
        res = super().execute()
        if hasattr(self, "_count") and self._count == "exact":
            res.count = len(res.data or [])
        return res


class HardeningInMemorySupabaseClient(InMemorySupabaseClient):
    """InMemorySupabaseClient that provisions HardeningInMemoryTable."""

    def table(self, name: str):
        if name not in self.tables:
            self.tables[name] = HardeningInMemoryTable(name, self)
        return self.tables[name]


@pytest.fixture
def hardening_db() -> HardeningInMemorySupabaseClient:
    db = HardeningInMemorySupabaseClient()

    # Seed client_gstins
    db.table("client_gstins").insert([
        {
            "id": CLIENT_A_ID,
            "firm_owner_id": USER_ADMIN_ID,
            "gstin": "27AAACB1234A1Z1",
            "legal_name": "Client A Corp",
            "is_active": True,
        },
        {
            "id": CLIENT_B_ID,
            "firm_owner_id": "other-firm-owner",
            "gstin": "27AAACB9999Z1Z9",
            "legal_name": "Client B Corp",
            "is_active": True,
        },
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
            "id": RUN_BLOCKED,
            "client_gstin_id": CLIENT_A_ID,
            "period": "2026-05",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
            "run_summary": {"clean_matched_count": 5},
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
        {
            "id": RUN_CLIENT_B,
            "client_gstin_id": CLIENT_B_ID,
            "period": "2026-05",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
            "run_summary": {"clean_matched_count": 2},
        },
    ]).execute()

    return db


def _mock_reconciliation_payload():
    return {
        "engine": {
            "matched": [{"gstr_id": "g-1", "pr_id": "p-1"}],
            "gstr_only": [],
            "pr_only": [],
            "probable": [],
        }
    }


# ---------------------------------------------------------------------------
# TEST 1: P0 Defect Fix Verification (POST /api/reconcile/runs/{id}/finalize)
# ---------------------------------------------------------------------------

def test_1_completed_run_finalizes_via_runs_endpoint_no_unbound_local_error(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 1: Proves a COMPLETED run successfully finalizes via POST /api/reconcile/runs/{id}/finalize.

    Specifically verifies that the previous UnboundLocalError ('p' referenced before assignment)
    is completely fixed and returns a valid RunSummary JSON payload.
    """
    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.auth.get_user_role", return_value="admin"):

        res = client.post(
            f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/finalize",
            headers=auth_headers,
            json={"checklist_snapshot": {"verified_reversals": True}},
        )

        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["run_id"] == RUN_COMPLETED_CLEAN
        assert data["status"].lower() == "final"


# ---------------------------------------------------------------------------
# TEST 2: Blocked Run Rejection (HTTP 422)
# ---------------------------------------------------------------------------

def test_2_blocked_run_returns_http_422(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 2: Proves that unresolved blocking exceptions prevent finalization on both endpoints."""
    blocked_gate = {
        "can_finalize": False,
        "unresolved_blocking_exceptions": 2,
        "blocking_summary": ["Missing Rule 37 payment date for INV-101", "Missing Rule 37A supplier filing status for INV-202"],
    }

    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value=blocked_gate), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value=blocked_gate), \
         patch("app.auth.get_user_role", return_value="admin"):

        # Endpoint A
        res_a = client.post(f"/api/reconciliation/finalize/{RUN_BLOCKED}", headers=auth_headers)
        assert res_a.status_code == 422
        assert "2 itc-affecting exception(s) require disposition before finalizing" in res_a.json()["detail"].lower()

        # Endpoint B
        res_b = client.post(f"/api/reconcile/runs/{RUN_BLOCKED}/finalize", headers=auth_headers, json={})
        assert res_b.status_code == 422
        assert "2 itc-affecting exception(s) require disposition before finalizing" in res_b.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TEST 3: Authoritative Table 4 Snapshot Creation
# ---------------------------------------------------------------------------

def test_3_successful_finalization_creates_authoritative_table4_snapshot(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 3: Proves successful finalization creates an authoritative, immutable Table 4 snapshot."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.auth.get_user_role", return_value="admin"):

        res = client.post(f"/api/reconciliation/finalize/{RUN_COMPLETED_CLEAN}", headers=auth_headers)
        assert res.status_code == 200

        # Verify gstr3b_table4_summaries row created
        summaries = hardening_db.table("gstr3b_table4_summaries").rows
        run_summaries = [s for s in summaries if s.get("run_id") == RUN_COMPLETED_CLEAN]
        assert len(run_summaries) == 1
        snap = run_summaries[0]
        assert snap["is_current"] is True
        assert snap["status"] == "FINALIZED"
        assert snap["version"] == 1

        # Verify reconciliation_run links to snapshot
        run_row = next(r for r in hardening_db.table("reconciliation_run").rows if r["id"] == RUN_COMPLETED_CLEAN)
        assert run_row.get("table4_summary_id") == snap["id"]


# ---------------------------------------------------------------------------
# TEST 4: Run Locking (status=FINAL, is_locked=True)
# ---------------------------------------------------------------------------

def test_4_successful_finalization_locks_the_run(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 4: Proves successful finalization transitions status to FINAL and sets is_locked=True."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.auth.get_user_role", return_value="admin"):

        res = client.post(f"/api/reconciliation/finalize/{RUN_COMPLETED_CLEAN}", headers=auth_headers)
        assert res.status_code == 200

        run_row = next(r for r in hardening_db.table("reconciliation_run").rows if r["id"] == RUN_COMPLETED_CLEAN)
        assert run_row["status"] == RunStatus.FINAL
        assert run_row["is_locked"] is True
        assert run_row["finalized_at"] is not None
        assert run_row["finalized_by"] == USER_ADMIN_ID


# ---------------------------------------------------------------------------
# TEST 5: 4B2 Entries Registered Exactly Once
# ---------------------------------------------------------------------------

def test_5_4b2_entries_registered_exactly_once(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 5: Proves that 4(B)(2) temporary reversals are auto-registered into the reversal ledger."""
    from tests.test_gstr3b_reversal_ledger import _make_outcome_row

    mock_outcome = _make_outcome_row(
        "pm:inv-rule37",
        category="rule37_warnings",
        matched_pr_id="pr-rule37",
        invoice_number="INV-37-01",
        rule37_flag=True,
        rule37a_flag=False,
        amount=100000,
    )

    mock_pr = {
        "pr-rule37": {
            "record_data": {
                "igst_paise": 100000,
                "cgst_paise": 0,
                "sgst_paise": 0,
                "cess_paise": 0,
                "invoice_number": "INV-37-01",
                "invoice_date": "2025-10-01",
                "supplier_gstin": "27SUPPLIER1Z1",
            }
        }
    }
    mock_disp = {
        "pm:inv-rule37:RULE_37": {"exception_type": "RULE_37", "disposition": "REVERSED", "reason": "Rule 37 180 days passed"}
    }

    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([mock_outcome], {}, {})), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={}), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value=mock_pr), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value=mock_disp), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.auth.get_user_role", return_value="admin"):

        res = client.post(f"/api/reconciliation/finalize/{RUN_COMPLETED_CLEAN}", headers=auth_headers)
        assert res.status_code == 200

        ledger_rows = hardening_db.table("gstr3b_reversal_ledger").rows
        assert len(ledger_rows) == 1
        entry = ledger_rows[0]
        assert entry["source_record_id"] == "pm:inv-rule37"
        assert entry["reversal_table4_cell"] == "4B2"
        assert entry["is_reclaimable"] is True
        assert entry["reversed_igst_paise"] == 100000
        assert entry["status"] == ReversalStatus.OPEN.value


# ---------------------------------------------------------------------------
# TEST 6: 17(5) / 4B1 Does NOT Create Reversal Ledger Entries
# ---------------------------------------------------------------------------

def test_6_17_5_permanent_reversals_do_not_enter_reversal_ledger(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 6: Proves that permanent reversals (Section 17(5) / 4B1) NEVER enter gstr3b_reversal_ledger."""
    mock_outcome = MagicMock()
    mock_outcome.id = "pm:inv-175"
    mock_outcome.category = "matched"
    mock_outcome.matched_pr_id = "pr-175"

    mock_pr = {
        "pr-175": {
            "record_data": {
                "igst_paise": 250000,
                "cgst_paise": 0,
                "sgst_paise": 0,
                "cess_paise": 0,
                "invoice_number": "INV-175-01",
                "invoice_date": "2026-05-01",
                "supplier_gstin": "27SUPPLIER1Z1",
                "itc_ineligible": "Y",
                "ineligible_reason": "17(5)",
            }
        }
    }
    mock_disp = {
        "pm:inv-175:INELIGIBLE_17_5": {"exception_type": "INELIGIBLE_17_5", "disposition": "REVERSED", "reason": "Motor vehicle per 17(5)"}
    }

    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([mock_outcome], {}, {})), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={}), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value=mock_pr), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value=mock_disp), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.auth.get_user_role", return_value="admin"):

        res = client.post(f"/api/reconciliation/finalize/{RUN_COMPLETED_CLEAN}", headers=auth_headers)
        assert res.status_code == 200

        # Section 17(5) is permanent (4B1); ledger MUST be empty
        ledger_rows = hardening_db.table("gstr3b_reversal_ledger").rows
        assert len(ledger_rows) == 0


# ---------------------------------------------------------------------------
# TEST 7: Idempotency (Repeated Finalization Creates No Duplicates)
# ---------------------------------------------------------------------------

def test_7_repeated_finalization_is_idempotent_and_creates_no_duplicates(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 7: Proves that repeating finalization on an already final run produces no duplicate state."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.auth.get_user_role", return_value="admin"):

        # First finalization
        res1 = client.post(f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/finalize", headers=auth_headers, json={})
        assert res1.status_code == 200

        snapshots_count_1 = len(hardening_db.table("gstr3b_table4_summaries").rows)
        ledger_count_1 = len(hardening_db.table("gstr3b_reversal_ledger").rows)

        # Second finalization (idempotent call from UI)
        res2 = client.post(f"/api/reconcile/runs/{RUN_COMPLETED_CLEAN}/finalize", headers=auth_headers, json={})
        assert res2.status_code == 200

        snapshots_count_2 = len(hardening_db.table("gstr3b_table4_summaries").rows)
        ledger_count_2 = len(hardening_db.table("gstr3b_reversal_ledger").rows)

        assert snapshots_count_2 == snapshots_count_1
        assert ledger_count_2 == ledger_count_1

        # Endpoint A on already finalized run returns 422
        res_a = client.post(f"/api/reconciliation/finalize/{RUN_COMPLETED_CLEAN}", headers=auth_headers)
        assert res_a.status_code == 422
        assert "run is already final" in res_a.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TEST 8: Concurrent Finalization (Optimistic Concurrency Control)
# ---------------------------------------------------------------------------

def test_8_concurrent_finalization_optimistic_lock_one_winner(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 8: Proves that if another process finalizes the run concurrently, HTTP 409 Conflict is returned."""
    original_table = hardening_db.table

    def table_mock(name: str):
        tbl = original_table(name)
        if name == "reconciliation_run":
            orig_update = tbl.update
            def fake_update(values):
                if values.get("status") == RunStatus.FINAL:
                    chain = orig_update(values)
                    def fake_exec():
                        mock_res = MagicMock()
                        mock_res.data = []  # 0 rows updated
                        return mock_res
                    chain.execute = fake_exec
                    return chain
                return orig_update(values)
            tbl.update = fake_update
        return tbl

    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch.object(hardening_db, "table", side_effect=table_mock), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.auth.get_user_role", return_value="admin"):

        res = client.post(f"/api/reconciliation/finalize/{RUN_COMPLETED_CLEAN}", headers=auth_headers)
        assert res.status_code == 409
        assert "could not finalize run; refresh and retry" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TEST 9: Unauthorized Cross-Client Finalization Rejected
# ---------------------------------------------------------------------------

def test_9_unauthorized_cross_client_finalization_rejected(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 9: Proves cross-client finalization attempts are rejected with HTTP 403 or 404."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.auth.get_user_role", return_value="admin"):

        res_a = client.post(f"/api/reconciliation/finalize/{RUN_CLIENT_B}", headers=auth_headers)
        assert res_a.status_code in (403, 404)

        res_b = client.post(f"/api/reconcile/runs/{RUN_CLIENT_B}/finalize", headers=auth_headers, json={})
        assert res_b.status_code in (403, 404)


# ---------------------------------------------------------------------------
# TEST 10: Existing Finalized Run Remains Immutable
# ---------------------------------------------------------------------------

def test_10_existing_finalized_run_remains_immutable(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 10: Proves that mutations (dispositions, adjustments, reclaims) are strictly rejected on finalized runs."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.auth.get_user_role", return_value="admin"):

        # 1. Finalize endpoint rejects
        res_fin = client.post(f"/api/reconciliation/finalize/{RUN_ALREADY_FINAL}", headers=auth_headers)
        assert res_fin.status_code == 422
        assert "run is already final" in res_fin.json()["detail"].lower()

        # 2. Adjustments endpoint rejects with 409
        res_adj = client.post(
            f"/api/reconcile/runs/{RUN_ALREADY_FINAL}/gstr3b/table4/adjust",
            headers=auth_headers,
            json={
                "row_id": "4A5",
                "igst": 100.0,
                "cgst": 0.0,
                "sgst": 0.0,
                "cess": 0.0,
                "adjustment_type": "ADDITION",
                "statutory_category": "OTHER",
                "reason": "Test adjustment on locked run",
            },
        )
        assert res_adj.status_code == 409
        assert "finalized reconciliation runs are immutable" in res_adj.json()["detail"].lower()

        # 3. Dispositions endpoint rejects with 409
        res_disp = client.post(
            f"/api/reconcile/runs/{RUN_ALREADY_FINAL}/dispositions",
            headers=auth_headers,
            json={
                "record_id": "pm:rec-1",
                "exception_type": "RULE_37",
                "disposition": "REVERSED",
                "reason": "Test disposition on locked run",
            },
        )
        assert res_disp.status_code == 409
        assert "finalized reconciliation runs are immutable" in res_disp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TEST 11: Snapshot Failure Preserves COMPLETED / Unlocked Run State
# ---------------------------------------------------------------------------

def test_11_snapshot_compilation_failure_preserves_unlocked_state(
    client: TestClient, auth_headers: dict, hardening_db: HardeningInMemorySupabaseClient
):
    """Test 11: Proves that if Table 4 snapshot compilation fails, run remains COMPLETED and is_locked=False."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=hardening_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}), \
         patch("app.services.reconciliation_outcomes.load_payload", return_value=_mock_reconciliation_payload()), \
         patch("app.routers.reconciliation_api.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"can_finalize": True, "unresolved_blocking_exceptions": 0, "blocking_summary": []}), \
         patch("app.routers.reconciliation_api.compile_and_save_final_table4_snapshot", side_effect=RuntimeError("DB Connection dropped during snapshot")), \
         patch("app.auth.get_user_role", return_value="admin"):

        res = client.post(f"/api/reconciliation/finalize/{RUN_COMPLETED_CLEAN}", headers=auth_headers)
        assert res.status_code == 500
        assert "snapshot compilation failed" in res.json()["detail"].lower()

        # Run MUST STILL BE COMPLETED and NOT locked
        run_row = next(r for r in hardening_db.table("reconciliation_run").rows if r["id"] == RUN_COMPLETED_CLEAN)
        assert run_row["status"] == RunStatus.COMPLETED
        assert run_row["is_locked"] is False
