"""Comprehensive test suite for Phase 3D: GSTR-3B Table 4 Reversal & Reclaim Ledger REST Endpoints.

Contracts and Guardrails Verified:
1. Source-Run Provenance View:
   - GET /api/reconciliation/{run_id}/table4/reversal-ledger
   - Returns reversals whose source provenance is that specific run
   - Calculates exact reversed, reclaimed, and outstanding totals
2. Client Multi-Period Lifecycle View:
   - GET /api/reconciliation/{client_id}/reversal-ledger
   - Supports UUID client identifier or 15-character GSTIN string
   - Cross-period tracking with status, statutory_reason, and reclaimability filters
3. Client Outstanding Reclaimable Balances:
   - GET /api/reconciliation/{client_id}/reclaimable-balances
   - Aggregates authorized vs pending balances across tax heads
4. Multi-Tenant Scoping & Access Control:
   - Rejects unauthorized users outside firm scope with HTTP 403
   - Rejects mismatched run/ledger client pairs with HTTP 403
5. Explicit Lifecycle State Machine Gate:
   - OPEN -> CONDITION_FULFILLED -> RECLAIM_AUTHORIZED -> PARTIALLY/FULLY_RECLAIMED
   - POST .../fulfill requires valid statutory evidence (Rule 37, Rule 37A, Section 16(2)(b))
   - Cannot skip steps: fulfill on fulfilled/authorized returns 409
   - Authorize on unfulfilled returns 409
   - Reclaim on un-authorized returns 409
6. Strict Reclaimability Guardrails:
   - Non-reclaimable (is_reclaimable=False) entries cannot fulfill, authorize, or reclaim (409)
7. Finalized Run Protection & Immutability:
   - Reclaim into finalized/locked target run strictly rejected with HTTP 409
   - Reclaim in target run does not mutate historical source run
8. Tax-Head Isolation & Mathematical Validation:
   - IGST, CGST, SGST, Cess independently bounded
   - Excess amounts, zero amounts, and negative amounts rejected with HTTP 422
9. HTTP-Level Idempotency:
   - Key-based replay returning is_idempotent_replay=True without double deductions
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.constants import RunStatus
from app.services.gstr3b_reversal_ledger import (
    ReversalStatus,
    StatutoryTemporaryReason,
    compute_state_digest,
)
from tests.test_gstr3b_reversal_ledger import InMemorySupabaseClient

CLIENT_ID_1 = "00000000-0000-0000-0000-000000000001"
CLIENT_ID_2 = "00000000-0000-0000-0000-000000000002"
GSTIN_1 = "27AAACB1234A1Z1"
GSTIN_2 = "27AAACB9999Z1Z9"

RUN_ID_1 = "11111111-1111-1111-1111-111111111111"
RUN_ID_2 = "22222222-2222-2222-2222-222222222222"
RUN_ID_FINALIZED = "33333333-3333-3333-3333-333333333333"

USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def mock_db() -> InMemorySupabaseClient:
    """Populate an in-memory DB with clients, runs, and initial reversal records."""
    db = InMemorySupabaseClient()

    # Seed client_gstins
    db.table("client_gstins").insert([
        {
            "id": CLIENT_ID_1,
            "firm_owner_id": USER_ID,
            "gstin": GSTIN_1,
            "legal_name": "Test Client 1 Corp",
            "is_active": True,
        },
        {
            "id": CLIENT_ID_2,
            "firm_owner_id": "other-user-99",
            "gstin": GSTIN_2,
            "legal_name": "Other Client 2 Corp",
            "is_active": True,
        },
    ]).execute()

    # Seed reconciliation_run
    db.table("reconciliation_run").insert([
        {
            "id": RUN_ID_1,
            "client_gstin_id": CLIENT_ID_1,
            "period": "2024-01",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
        },
        {
            "id": RUN_ID_2,
            "client_gstin_id": CLIENT_ID_1,
            "period": "2024-02",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
        },
        {
            "id": RUN_ID_FINALIZED,
            "client_gstin_id": CLIENT_ID_1,
            "period": "2023-12",
            "status": RunStatus.FINAL,
            "is_locked": True,
        },
    ]).execute()

    return db


def _seed_ledger_entry(
    db: InMemorySupabaseClient,
    *,
    entry_id: str | None = None,
    client_gstin_id: str = CLIENT_ID_1,
    source_run_id: str = RUN_ID_1,
    reversal_tax_period: str = "2024-01",
    statutory_reason: str = StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value,
    is_reclaimable: bool = True,
    status: str = ReversalStatus.OPEN.value,
    reversed_igst: int = 10000,
    reversed_cgst: int = 5000,
    reversed_sgst: int = 5000,
    reversed_cess: int = 0,
    reclaimed_igst: int = 0,
    reclaimed_cgst: int = 0,
    reclaimed_sgst: int = 0,
    reclaimed_cess: int = 0,
) -> dict:
    eid = entry_id or str(uuid.uuid4())
    row = {
        "id": eid,
        "client_gstin_id": client_gstin_id,
        "source_type": "RECON_OUTCOME",
        "source_record_id": f"rec-{eid[:8]}",
        "source_run_id": source_run_id,
        "reversal_tax_period": reversal_tax_period,
        "document_type": "INVOICE",
        "document_number": f"INV-{eid[:6]}",
        "document_date": "2024-01-15",
        "supplier_gstin": "27SUPPLIER1234",
        "reversal_table4_cell": "4B2",
        "is_reclaimable": is_reclaimable,
        "statutory_reason": statutory_reason,
        "reversed_igst_paise": reversed_igst,
        "reversed_cgst_paise": reversed_cgst,
        "reversed_sgst_paise": reversed_sgst,
        "reversed_cess_paise": reversed_cess,
        "cached_reclaimed_igst_paise": reclaimed_igst,
        "cached_reclaimed_cgst_paise": reclaimed_cgst,
        "cached_reclaimed_sgst_paise": reclaimed_sgst,
        "cached_reclaimed_cess_paise": reclaimed_cess,
        "status": status,
        "source_state_hash": compute_state_digest({"eid": eid}),
        "source_payload": {"test": True},
        "created_at": "2024-01-20T10:00:00Z",
        "updated_at": "2024-01-20T10:00:00Z",
    }
    db.table("gstr3b_reversal_ledger").insert(row).execute()
    return row


# ───────────────────────────────────────────────────────────────────────────
# 1. Source-Run Provenance View Tests
# ───────────────────────────────────────────────────────────────────────────

def test_endpoint_run_reversal_ledger_source_view(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """GET /api/reconciliation/{run_id}/table4/reversal-ledger returns entries originating from run."""
    _seed_ledger_entry(mock_db, source_run_id=RUN_ID_1, reversed_igst=10000, reversed_cgst=5000, reversed_sgst=5000)
    _seed_ledger_entry(mock_db, source_run_id=RUN_ID_1, reversed_igst=20000, reversed_cgst=0, reversed_sgst=0)
    # Seed entry from different run
    _seed_ledger_entry(mock_db, source_run_id=RUN_ID_2, reversed_igst=99999)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.get(f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["source_run_id"] == RUN_ID_1
    assert data["client_gstin_id"] == CLIENT_ID_1
    assert data["total_count"] == 2
    assert data["summary"]["reversed"]["igst_paise"] == 30000
    assert data["summary"]["reversed"]["cgst_paise"] == 5000
    assert data["summary"]["reversed"]["sgst_paise"] == 5000
    assert data["summary"]["reversed"]["total_paise"] == 40000
    assert data["summary"]["outstanding"]["total_paise"] == 40000


def test_endpoint_run_reversal_ledger_filters(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """GET /api/reconciliation/{run_id}/table4/reversal-ledger supports status and reclaimable filters."""
    _seed_ledger_entry(mock_db, source_run_id=RUN_ID_1, status=ReversalStatus.OPEN.value, is_reclaimable=True)
    _seed_ledger_entry(mock_db, source_run_id=RUN_ID_1, status=ReversalStatus.CONDITION_FULFILLED.value, is_reclaimable=True)
    _seed_ledger_entry(mock_db, source_run_id=RUN_ID_1, status=ReversalStatus.NON_RECLAIMABLE.value, is_reclaimable=False)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        # Filter by status=OPEN
        res_open = client.get(f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger?status=OPEN", headers=auth_headers)
        assert res_open.status_code == 200
        assert res_open.json()["total_count"] == 1

        # Filter by is_reclaimable=false
        res_nonrec = client.get(f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger?is_reclaimable=false", headers=auth_headers)
        assert res_nonrec.status_code == 200
        assert res_nonrec.json()["total_count"] == 1
        assert res_nonrec.json()["items"][0]["status"] == ReversalStatus.NON_RECLAIMABLE.value


# ───────────────────────────────────────────────────────────────────────────
# 2. Client Lifecycle View Tests
# ───────────────────────────────────────────────────────────────────────────

def test_endpoint_client_reversal_ledger_by_uuid(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """GET /api/reconciliation/{client_id}/reversal-ledger returns multi-period records by client UUID."""
    _seed_ledger_entry(mock_db, reversal_tax_period="2024-01", reversed_igst=10000)
    _seed_ledger_entry(mock_db, reversal_tax_period="2024-02", reversed_igst=15000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.get(f"/api/reconciliation/{CLIENT_ID_1}/reversal-ledger", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["client_gstin_id"] == CLIENT_ID_1
    assert data["total_count"] == 2
    assert data["summary"]["reversed"]["igst_paise"] == 25000


def test_endpoint_client_reversal_ledger_by_gstin(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """GET /api/reconciliation/{client_id}/reversal-ledger resolves 15-char GSTIN to client_gstins.id."""
    _seed_ledger_entry(mock_db, reversal_tax_period="2024-01", reversed_igst=12345)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.get(f"/api/reconciliation/{GSTIN_1}/reversal-ledger", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["client_gstin_id"] == CLIENT_ID_1
    assert data["total_count"] == 1


def test_endpoint_client_reversal_ledger_filters(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """GET /api/reconciliation/{client_id}/reversal-ledger filters by statutory reason and period."""
    _seed_ledger_entry(mock_db, statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value, reversal_tax_period="2024-01")
    _seed_ledger_entry(mock_db, statutory_reason=StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING.value, reversal_tax_period="2024-02")

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.get(
            f"/api/reconciliation/{CLIENT_ID_1}/reversal-ledger?statutory_reason=RULE_37_NON_PAYMENT",
            headers=auth_headers,
        )
        assert res.status_code == 200
        assert res.json()["total_count"] == 1
        assert res.json()["items"][0]["statutory_reason"] == StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value

        res_period = client.get(
            f"/api/reconciliation/{CLIENT_ID_1}/reversal-ledger?reversal_tax_period=2024-02",
            headers=auth_headers,
        )
        assert res_period.status_code == 200
        assert res_period.json()["total_count"] == 1


# ───────────────────────────────────────────────────────────────────────────
# 3. Client Outstanding Reclaimable Balances Tests
# ───────────────────────────────────────────────────────────────────────────

def test_endpoint_client_reclaimable_balances(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """GET /api/reconciliation/{client_id}/reclaimable-balances groups authorized vs pending balances."""
    # Seed one authorized entry
    _seed_ledger_entry(
        mock_db,
        status=ReversalStatus.RECLAIM_AUTHORIZED.value,
        reversed_igst=10000,
        reversed_cgst=2000,
        reversed_sgst=2000,
    )
    # Seed one open (pending auth) entry
    _seed_ledger_entry(
        mock_db,
        status=ReversalStatus.OPEN.value,
        reversed_igst=5000,
        reversed_cgst=1000,
        reversed_sgst=1000,
    )

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.get(f"/api/reconciliation/{CLIENT_ID_1}/reclaimable-balances", headers=auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["total_reclaimable_authorized"]["igst_paise"] == 10000
    assert data["total_reclaimable_authorized"]["total_paise"] == 14000
    assert data["total_pending_authorization"]["igst_paise"] == 5000
    assert data["total_pending_authorization"]["total_paise"] == 7000


# ───────────────────────────────────────────────────────────────────────────
# 4. Multi-Tenant Scoping & Access Control Tests
# ───────────────────────────────────────────────────────────────────────────

def test_multi_tenant_isolation_unauthorized_client_rejected(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Unauthorized user attempting to read client reversal ledger is rejected with HTTP 403."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        # CLIENT_ID_2 belongs to another firm
        res = client.get(f"/api/reconciliation/{CLIENT_ID_2}/reversal-ledger", headers=auth_headers)

    assert res.status_code == 403


def test_multi_tenant_isolation_unauthorized_run_rejected(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Unauthorized user attempting to access a run outside firm scope receives HTTP 403."""
    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.services.firm_access.list_accessible_client_gstin_ids", return_value=set()):
        res = client.get(f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger", headers=auth_headers)

    assert res.status_code == 403


def test_mismatched_client_on_fulfill_returns_403(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Fulfill request where ledger entry client differs from run client raises HTTP 403."""
    # Create ledger entry belonging to client 2
    entry = _seed_ledger_entry(mock_db, client_gstin_id=CLIENT_ID_2, source_run_id="run-client-2")

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1, CLIENT_ID_2}):
        # RUN_ID_1 belongs to CLIENT_ID_1, but entry belongs to CLIENT_ID_2
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "UTR-TEST-123", "payment_date": "2024-03-01"},
        )

    assert res.status_code == 403
    assert "different client" in res.json()["detail"].lower()


# ───────────────────────────────────────────────────────────────────────────
# 5. Lifecycle Transition: Fulfill Condition Tests
# ───────────────────────────────────────────────────────────────────────────

def test_fulfill_reversal_condition_success(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Transition OPEN -> CONDITION_FULFILLED with payment evidence."""
    entry = _seed_ledger_entry(mock_db, statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={
                "payment_reference": "UTR-998877",
                "payment_date": "2024-03-10",
                "notes": "Payment made in full to supplier via NEFT",
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] == ReversalStatus.CONDITION_FULFILLED.value
    assert data["entry"]["status"] == ReversalStatus.CONDITION_FULFILLED.value


def test_fulfill_nonexistent_entry_returns_404(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Fulfill on unknown ledger UUID returns HTTP 404."""
    unknown_id = str(uuid.uuid4())
    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{unknown_id}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "UTR-123"},
        )
    assert res.status_code == 404


def test_fulfill_invalid_state_transition_returns_409(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Fulfill on an entry that is already CONDITION_FULFILLED returns HTTP 409."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.CONDITION_FULFILLED.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "UTR-123"},
        )
    assert res.status_code == 409
    assert "must be 'OPEN'" in res.json()["detail"]


def test_fulfill_non_reclaimable_entry_returns_409(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Fulfill on non-reclaimable entry (is_reclaimable=False) returns HTTP 409."""
    entry = _seed_ledger_entry(mock_db, is_reclaimable=False, status=ReversalStatus.NON_RECLAIMABLE.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "UTR-123"},
        )
    assert res.status_code == 409
    assert "non-reclaimable" in res.json()["detail"].lower()


def test_fulfill_rule37_missing_evidence_returns_422(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Fulfill Rule 37 without payment details returns HTTP 422."""
    entry = _seed_ledger_entry(mock_db, statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"notes": "No payment details provided"},
        )
    assert res.status_code == 422
    assert "payment reference" in res.json()["detail"].lower()


def test_fulfill_rule37a_missing_evidence_returns_422(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Fulfill Rule 37A without supplier filing date/ARN returns HTTP 422."""
    entry = _seed_ledger_entry(mock_db, statutory_reason=StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"notes": "Supplier told us they filed"},
        )
    assert res.status_code == 422
    assert "supplier filing date and arn" in res.json()["detail"].lower()


# ───────────────────────────────────────────────────────────────────────────
# 6. Lifecycle Transition: Authorize Reclaim Tests
# ───────────────────────────────────────────────────────────────────────────

def test_authorize_reclaim_success(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Transition CONDITION_FULFILLED -> RECLAIM_AUTHORIZED."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.CONDITION_FULFILLED.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/authorize",
            headers=auth_headers,
            json={
                "reclaim_target_period": "2024-03",
                "authorization_notes": "CA verified invoice and payment, authorized for reclaim in March 2024",
                "authorization_reference": "AUTH-2024-001",
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] == ReversalStatus.RECLAIM_AUTHORIZED.value
    assert data["entry"]["status"] == ReversalStatus.RECLAIM_AUTHORIZED.value


def test_authorize_reclaim_on_open_entry_returns_409(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Attempting to authorize an OPEN entry before condition is fulfilled returns HTTP 409."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.OPEN.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/authorize",
            headers=auth_headers,
            json={"reclaim_target_period": "2024-03"},
        )
    assert res.status_code == 409
    assert "condition has not been fulfilled" in res.json()["detail"].lower()


def test_authorize_reclaim_on_non_reclaimable_returns_409(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Authorize on non-reclaimable entry returns HTTP 409."""
    entry = _seed_ledger_entry(mock_db, is_reclaimable=False, status=ReversalStatus.NON_RECLAIMABLE.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/authorize",
            headers=auth_headers,
            json={"reclaim_target_period": "2024-03"},
        )
    assert res.status_code == 409


def test_authorize_reclaim_already_authorized_is_idempotent(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Authorize on already RECLAIM_AUTHORIZED entry returns HTTP 200 idempotently."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/authorize",
            headers=auth_headers,
            json={"reclaim_target_period": "2024-03"},
        )
    assert res.status_code == 200
    assert res.json()["status"] == ReversalStatus.RECLAIM_AUTHORIZED.value


# ───────────────────────────────────────────────────────────────────────────
# 7. Execute Reclaim Tests
# ───────────────────────────────────────────────────────────────────────────

def test_execute_reclaim_success(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Execute reclaim against active target run succeeds and updates balances."""
    entry = _seed_ledger_entry(
        mock_db,
        source_run_id=RUN_ID_1,
        status=ReversalStatus.RECLAIM_AUTHORIZED.value,
        reversed_igst=10000,
        reversed_cgst=5000,
        reversed_sgst=5000,
    )

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 6000,
                "reclaim_cgst_paise": 5000,
                "reclaim_sgst_paise": 5000,
                "reclaim_notes": "Executing partial reclaim into Feb 2024 run",
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["is_idempotent_replay"] is False
    assert data["status"] == ReversalStatus.PARTIALLY_RECLAIMED.value
    assert data["reclaimed_paise"]["igst"] == 6000
    assert data["remaining_paise"]["igst"] == 4000
    assert data["remaining_paise"]["cgst"] == 0
    assert data["remaining_paise"]["sgst"] == 0


def test_execute_reclaim_into_finalized_locked_run_returns_409(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim targeting a locked/finalized run is strictly rejected with HTTP 409."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, reversed_igst=10000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_FINALIZED}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 5000,
            },
        )

    assert res.status_code == 409
    assert "finalized" in res.json()["detail"].lower()


def test_execute_reclaim_on_unauthorized_state_returns_409(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim on OPEN or CONDITION_FULFILLED entry returns HTTP 409."""
    entry_open = _seed_ledger_entry(mock_db, status=ReversalStatus.OPEN.value, reversed_igst=10000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry_open["id"],
                "reclaim_igst_paise": 5000,
            },
        )
    assert res.status_code == 409
    assert "expected 'RECLAIM_AUTHORIZED'" in res.json()["detail"]


def test_execute_reclaim_on_non_reclaimable_returns_409(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim on non-reclaimable entry returns HTTP 409."""
    entry = _seed_ledger_entry(mock_db, is_reclaimable=False, status=ReversalStatus.NON_RECLAIMABLE.value, reversed_igst=10000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": 1000},
        )
    assert res.status_code == 409


def test_execute_reclaim_mismatched_client_returns_403(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim where ledger entry client differs from target run client returns HTTP 403."""
    entry = _seed_ledger_entry(mock_db, client_gstin_id=CLIENT_ID_2, status=ReversalStatus.RECLAIM_AUTHORIZED.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1, CLIENT_ID_2}):
        # RUN_ID_2 is for CLIENT_ID_1
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": 1000},
        )
    assert res.status_code == 403
    assert "different client" in res.json()["detail"].lower()


def test_execute_reclaim_excess_tax_head_returns_422(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim amount exceeding available balance for a tax head returns HTTP 422."""
    entry = _seed_ledger_entry(
        mock_db,
        status=ReversalStatus.RECLAIM_AUTHORIZED.value,
        reversed_igst=5000,
        reversed_cgst=2000,
        reversed_sgst=2000,
    )

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        # Attempt to claim 6000 IGST when only 5000 is available
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": 6000},
        )
    assert res.status_code == 422
    assert "EXCESS_RECLAIM_IGST" in res.json()["detail"]


def test_execute_reclaim_zero_or_negative_returns_422(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim with total zero paise or negative amounts returns HTTP 422."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, reversed_igst=5000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        # Zero amount
        res_zero = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": 0},
        )
        assert res_zero.status_code == 422

        # Negative amount
        res_neg = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": -100},
        )
        assert res_neg.status_code == 422


def test_execute_reclaim_idempotency_key_replay(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim with same idempotency_key returns cached event without double deduction."""
    entry = _seed_ledger_entry(
        mock_db,
        status=ReversalStatus.RECLAIM_AUTHORIZED.value,
        reversed_igst=10000,
    )
    idemp_key = "test-idemp-uuid-12345"

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        # First execution
        res1 = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 4000,
                "idempotency_key": idemp_key,
            },
        )
        assert res1.status_code == 200
        d1 = res1.json()
        assert d1["is_idempotent_replay"] is False
        event_id_1 = d1["event_id"]

        # Duplicate retry with same idempotency key
        res2 = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 4000,
                "idempotency_key": idemp_key,
            },
        )
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["is_idempotent_replay"] is True
        assert d2["event_id"] == event_id_1
        # Remaining paise is still 6000 (not 2000 from double-reclaim!)
        assert d2["remaining_paise"]["igst"] == 6000


def test_reclaim_target_run_immutability_of_source_run(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Executing reclaim in target run does not mutate or modify source run."""
    entry = _seed_ledger_entry(
        mock_db,
        source_run_id=RUN_ID_1,
        status=ReversalStatus.RECLAIM_AUTHORIZED.value,
        reversed_igst=10000,
    )

    # Record source run state before reclaim
    source_run_before = [r for r in mock_db.table("reconciliation_run").rows if r["id"] == RUN_ID_1][0].copy()

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 5000,
            },
        )

    assert res.status_code == 200
    source_run_after = [r for r in mock_db.table("reconciliation_run").rows if r["id"] == RUN_ID_1][0]
    # Source run attributes remain completely identical
    assert source_run_before == source_run_after


# ───────────────────────────────────────────────────────────────────────────
# 8. Phase 3E: Production Hardening, Dedicated Idempotency & Audit Tests
# ───────────────────────────────────────────────────────────────────────────

def test_phase3e_dedicated_idempotency_key_column_persisted(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """idempotency_key is persisted in dedicated DB column, not encoded into notes."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, reversed_igst=10000)
    idemp_key = "prod-idem-key-8888"

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 3000,
                "reclaim_notes": "Clean CA human note",
                "idempotency_key": idemp_key,
            },
        )

    assert res.status_code == 200
    events = mock_db.table("gstr3b_reclaim_events").rows
    matching_ev = [e for e in events if e.get("idempotency_key") == idemp_key]
    assert len(matching_ev) == 1
    ev = matching_ev[0]
    assert ev["client_gstin_id"] == CLIENT_ID_1
    assert ev["idempotency_key"] == idemp_key
    assert ev["reclaim_notes"] == "Clean CA human note"
    assert "[IDEMP:" not in ev["reclaim_notes"]


def test_phase3e_idempotency_decoupled_from_notes_string(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """String '[IDEMP:xyz]' inside notes does not trigger fake idempotency."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, reversed_igst=10000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        # First execution with fake string in note, but no idempotency_key
        res1 = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 2000,
                "reclaim_notes": "Mentioning [IDEMP:fake-tag] as text",
            },
        )
        assert res1.status_code == 200
        assert res1.json()["is_idempotent_replay"] is False

        # Second execution with same note text but no idempotency_key is a distinct second execution
        res2 = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={
                "ledger_id": entry["id"],
                "reclaim_igst_paise": 2000,
                "reclaim_notes": "Mentioning [IDEMP:fake-tag] as text",
            },
        )
        assert res2.status_code == 200
        assert res2.json()["is_idempotent_replay"] is False
        assert res2.json()["event_id"] != res1.json()["event_id"]


def test_phase3e_database_unique_constraint_enforcement(
    mock_db: InMemorySupabaseClient
):
    """Database unique index uq_reclaim_events_client_idempotency prevents duplicate insert."""
    mock_db.table("gstr3b_reclaim_events").insert({
        "client_gstin_id": CLIENT_ID_1,
        "ledger_id": str(uuid.uuid4()),
        "reclaim_run_id": RUN_ID_2,
        "reclaim_tax_period": "2024-02",
        "reclaimed_igst_paise": 1000,
        "idempotency_key": "conflict-key-1",
    }).execute()

    # Second insert with same client and key raises unique constraint violation
    with pytest.raises(RuntimeError) as exc_info:
        mock_db.table("gstr3b_reclaim_events").insert({
            "client_gstin_id": CLIENT_ID_1,
            "ledger_id": str(uuid.uuid4()),
            "reclaim_run_id": RUN_ID_2,
            "reclaim_tax_period": "2024-02",
            "reclaimed_igst_paise": 1000,
            "idempotency_key": "conflict-key-1",
        }).execute()

    assert "UNIQUE CONSTRAINT VIOLATION" in str(exc_info.value)
    assert "uq_reclaim_events_client_idempotency" in str(exc_info.value)


def test_phase3e_cross_client_idempotency_key_isolation(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Same idempotency_key used by different clients does NOT conflict (scoped to client)."""
    run_client_2_source = "55555555-5555-5555-5555-555555555555"
    run_client_2_active = "44444444-4444-4444-4444-444444444444"

    # Make client 2 accessible to user's firm for multi-client testing
    mock_db.table("client_gstins").update({"firm_owner_id": USER_ID}).eq("id", CLIENT_ID_2).execute()

    entry1 = _seed_ledger_entry(mock_db, client_gstin_id=CLIENT_ID_1, source_run_id=RUN_ID_1, status=ReversalStatus.RECLAIM_AUTHORIZED.value, reversed_igst=5000)
    entry2 = _seed_ledger_entry(mock_db, client_gstin_id=CLIENT_ID_2, source_run_id=run_client_2_source, status=ReversalStatus.RECLAIM_AUTHORIZED.value, reversed_igst=5000)

    # Seed run for client 2
    mock_db.table("reconciliation_run").insert({
        "id": run_client_2_active,
        "client_gstin_id": CLIENT_ID_2,
        "period": "2024-02",
        "status": RunStatus.COMPLETED,
        "is_locked": False,
    }).execute()

    shared_key = "tx-shared-idem-key"

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.services.firm_access.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1, CLIENT_ID_2}), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1, CLIENT_ID_2}):
        res1 = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry1["id"], "reclaim_igst_paise": 2000, "idempotency_key": shared_key},
        )
        assert res1.status_code == 200
        assert res1.json()["is_idempotent_replay"] is False

        # Client 2 using identical idempotency_key succeeds independently
        res2 = client.post(
            f"/api/reconciliation/{run_client_2_active}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry2["id"], "reclaim_igst_paise": 2000, "idempotency_key": shared_key},
        )
        assert res2.status_code == 200
        assert res2.json()["is_idempotent_replay"] is False


def test_phase3e_audit_logging_across_all_lifecycle_transitions(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Audit action is logged on fulfill, authorize, and reclaim."""
    entry = _seed_ledger_entry(mock_db, status=ReversalStatus.OPEN.value, statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value, reversed_igst=10000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}), \
         patch("app.routers.reconciliation_api.log_action") as mock_log:

        # 1. Fulfill
        res_f = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "UTR-AUDIT-1", "payment_date": "2024-03-01"},
        )
        assert res_f.status_code == 200
        assert any(c[0][1] == "TABLE4_REVERSAL_CONDITION_FULFILLED" for c in mock_log.call_args_list)

        # 2. Authorize
        res_a = client.post(
            f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/{entry['id']}/authorize",
            headers=auth_headers,
            json={"reclaim_target_period": "2024-03", "authorization_reference": "AUTH-AUDIT-1"},
        )
        assert res_a.status_code == 200
        assert any(c[0][1] == "TABLE4_REVERSAL_RECLAIM_AUTHORIZED" for c in mock_log.call_args_list)

        # 3. Reclaim
        mock_log.reset_mock()
        res_r = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": 4000, "idempotency_key": "audit-key-1"},
        )
        assert res_r.status_code == 200
        assert any(c[0][1] == "TABLE4_RECLAIM_EXECUTED" for c in mock_log.call_args_list)

        # 4. Idempotent replay does NOT re-log TABLE4_RECLAIM_EXECUTED
        mock_log.reset_mock()
        res_replay = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": 4000, "idempotency_key": "audit-key-1"},
        )
        assert res_replay.status_code == 200
        assert not any(c[0][1] == "TABLE4_RECLAIM_EXECUTED" for c in mock_log.call_args_list)


def test_phase3e_reclaim_response_source_run_provenance(
    client: TestClient, auth_headers: dict, mock_db: InMemorySupabaseClient
):
    """Reclaim response explicitly exposes source_run_id and target_run_id."""
    entry = _seed_ledger_entry(mock_db, source_run_id=RUN_ID_1, status=ReversalStatus.RECLAIM_AUTHORIZED.value, reversed_igst=10000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        res = client.post(
            f"/api/reconciliation/{RUN_ID_2}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_igst_paise": 5000},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["source_run_id"] == RUN_ID_1
    assert data["target_run_id"] == RUN_ID_2


def test_phase3e_malformed_uuid_returns_400(
    client: TestClient, auth_headers: dict
):
    """Passing a malformed UUID returns HTTP 400 with descriptive message."""
    res = client.get("/api/reconciliation/not-a-valid-uuid/table4/reversal-ledger", headers=auth_headers)
    assert res.status_code == 400
    assert "invalid run_id" in res.json()["detail"].lower()


def test_phase3e_unauthenticated_requests_return_401(
    client: TestClient
):
    """Requests lacking authentication header receive HTTP 401."""
    res1 = client.get(f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger")
    assert res1.status_code == 401

    res2 = client.get(f"/api/reconciliation/{CLIENT_ID_1}/reversal-ledger")
    assert res2.status_code == 401

    res3 = client.post(f"/api/reconciliation/{RUN_ID_1}/table4/reversal-ledger/some-id/fulfill", json={})
    assert res3.status_code == 401

