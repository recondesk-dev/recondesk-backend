"""Phase 3G: GSTR-3B Table 4 Reversal & Reclaim Production Readiness Audit Test Suite.

Exhaustive verification of statutory, concurrency, immutability, boundary, and authorization controls:
- 3G-A: Authentication & Multi-Tenant Authorization
- 3G-B: Finalized Run Immutability
- 3G-C: Reversal Ledger Immutability
- 3G-D: Reclaim Event Append-Only Behavior
- 3G-E: Concurrency Safety (Test 1, Test 2, Test 3)
- 3G-F: Tax-Head Isolation & Mathematical Bounds
- 3G-G: Lifecycle State Machine Transitions
- 3G-H: Statutory Evidence Requirements
- 3G-I: Section 17(5), 16(4), and Place of Supply Boundaries
- 3G-J: Idempotency Scoping & Deduplication
- 3G-K: Audit Trail Integrity
- 3G-L: API Error Contracts
- 3G-M: Target Run Safety & Isolation
- 3G-N: Snapshot Versioning & Deterministic SHA-256 Hashing
"""

from __future__ import annotations

import concurrent.futures
import threading
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.constants import RunStatus
from app.services.gstr3b_reversal_ledger import (
    AvailableBalancePaise,
    ReclaimEventCreate,
    ReclaimEventType,
    ReversalLedgerCreate,
    ReversalProvenanceType,
    ReversalStatus,
    StatutoryEvidenceType,
    StatutoryTemporaryReason,
    authorize_reclaim,
    calculate_available_balance,
    compute_state_digest,
    create_reversal_ledger_entry,
    execute_reclaim_event,
    fulfill_reversal_condition,
    get_reversal_ledger_entry,
    register_table4_reversals_to_ledger,
)
from app.services.gstr3b_table4_engine import (
    compile_and_save_final_table4_snapshot,
    compile_gstr3b_table4,
)
from tests.test_gstr3b_reversal_ledger import InMemorySupabaseClient

CLIENT_A_ID = "00000000-0000-0000-0000-000000000001"
CLIENT_B_ID = "00000000-0000-0000-0000-000000000002"
GSTIN_A = "27AAACB1234A1ZA"
GSTIN_B = "27AAACB9999Z1ZB"

RUN_A1_SRC = "11111111-1111-1111-1111-11111111111a"
RUN_A2_TGT = "22222222-2222-2222-2222-22222222222a"
RUN_A_FINAL = "33333333-3333-3333-3333-33333333333a"
RUN_B_TGT = "44444444-4444-4444-4444-44444444444b"

USER_A = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def audit_db() -> InMemorySupabaseClient:
    db = InMemorySupabaseClient()

    # Seed client_gstins
    db.table("client_gstins").insert([
        {
            "id": CLIENT_A_ID,
            "firm_owner_id": USER_A,
            "gstin": GSTIN_A,
            "legal_name": "Client A Corp",
            "is_active": True,
        },
        {
            "id": CLIENT_B_ID,
            "firm_owner_id": "other-firm-owner",
            "gstin": GSTIN_B,
            "legal_name": "Client B Corp",
            "is_active": True,
        },
    ]).execute()

    # Seed reconciliation runs
    db.table("reconciliation_run").insert([
        {
            "id": RUN_A1_SRC,
            "client_gstin_id": CLIENT_A_ID,
            "period": "2026-05",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
        },
        {
            "id": RUN_A2_TGT,
            "client_gstin_id": CLIENT_A_ID,
            "period": "2026-06",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
        },
        {
            "id": RUN_A_FINAL,
            "client_gstin_id": CLIENT_A_ID,
            "period": "2026-05",
            "status": RunStatus.FINAL,
            "is_locked": True,
            "finalized_at": "2026-06-15T10:00:00Z",
        },
        {
            "id": RUN_B_TGT,
            "client_gstin_id": CLIENT_B_ID,
            "period": "2026-06",
            "status": RunStatus.COMPLETED,
            "is_locked": False,
        },
    ]).execute()

    return db


def _seed_audit_ledger_entry(
    db: InMemorySupabaseClient,
    *,
    status: str = ReversalStatus.OPEN.value,
    is_reclaimable: bool = True,
    statutory_reason: str = StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value,
    cgst: int = 1017275,
    sgst: int = 1017275,
    igst: int = 0,
    cess: int = 0,
    client_id: str = CLIENT_A_ID,
    source_run_id: str = RUN_A1_SRC,
) -> dict:
    entry = {
        "id": str(uuid.uuid4()),
        "client_gstin_id": client_id,
        "source_type": ReversalProvenanceType.RECON_OUTCOME.value,
        "source_record_id": f"pm:{uuid.uuid4()}",
        "source_run_id": source_run_id,
        "reversal_tax_period": "2026-05",
        "source_state_hash": "audit-mock-hash-1234",
        "source_payload": {"test": "payload"},
        "document_type": "INVOICE",
        "document_number": "INV-AUDIT-101",
        "document_date": "2026-04-01",
        "supplier_gstin": "27TESTV1234A1Z1",
        "reversal_table4_cell": "4B2",
        "is_reclaimable": is_reclaimable,
        "statutory_reason": statutory_reason,
        "reversed_igst_paise": igst,
        "reversed_cgst_paise": cgst,
        "reversed_sgst_paise": sgst,
        "reversed_cess_paise": cess,
        "cached_reclaimed_igst_paise": 0,
        "cached_reclaimed_cgst_paise": 0,
        "cached_reclaimed_sgst_paise": 0,
        "cached_reclaimed_cess_paise": 0,
        "status": status,
        "created_at": "2026-05-31T12:00:00Z",
    }
    db.table("gstr3b_reversal_ledger").insert(entry).execute()
    return entry


# ---------------------------------------------------------------------------
# 3G-E: CONCURRENCY / RACE CONDITION AUDIT (HIGH PRIORITY)
# ---------------------------------------------------------------------------

def test_3g_e_concurrency_test1_same_idempotency_key(audit_db: InMemorySupabaseClient):
    """Test 1: Two simultaneous requests with the SAME idempotency key produce exactly 1 event and 1 deduction."""
    entry = _seed_audit_ledger_entry(audit_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, cgst=100000, sgst=100000)
    shared_key = "audit-concurrent-same-key-1"

    req1 = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=100000,
        reclaimed_sgst_paise=100000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-CONCUR-1",
        reclaim_notes="Test notes 1",
        idempotency_key=shared_key,
    )
    req2 = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=100000,
        reclaimed_sgst_paise=100000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-CONCUR-1",
        reclaim_notes="Test notes 2",
        idempotency_key=shared_key,
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(execute_reclaim_event, audit_db, req1)
        f2 = executor.submit(execute_reclaim_event, audit_db, req2)
        results = [f1.result(), f2.result()]

    # Exactly one original, one replay
    replays = [r for r in results if r.is_idempotent_replay]
    originals = [r for r in results if not r.is_idempotent_replay]
    assert len(replays) == 1, "Expected exactly 1 replay"
    assert len(originals) == 1, "Expected exactly 1 original execution"
    assert replays[0].event_id == originals[0].event_id, "Replay must return original event_id"

    # Exactly 1 event row in database
    evs = audit_db.table("gstr3b_reclaim_events").select("*").eq("ledger_id", entry["id"]).execute().data
    assert len(evs) == 1

    # Balances exact, zero remaining
    updated = get_reversal_ledger_entry(audit_db, entry["id"])
    assert updated["status"] == ReversalStatus.FULLY_RECLAIMED.value
    assert updated["cached_reclaimed_cgst_paise"] == 100000
    assert updated["cached_reclaimed_sgst_paise"] == 100000


def test_3g_e_concurrency_test2_different_keys_competing_for_full_balance(audit_db: InMemorySupabaseClient):
    """Test 2: Two simultaneous requests with DIFFERENT keys competing for full balance -> 1 succeeds, 1 rejected."""
    entry = _seed_audit_ledger_entry(audit_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, cgst=100000, sgst=100000)

    req_a = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=100000,
        reclaimed_sgst_paise=100000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-A",
        reclaim_notes="Concurrent full attempt A",
        idempotency_key="key-compete-A",
    )
    req_b = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=100000,
        reclaimed_sgst_paise=100000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-B",
        reclaim_notes="Concurrent full attempt B",
        idempotency_key="key-compete-B",
    )

    successes = []
    failures = []

    def _worker(req):
        try:
            res = execute_reclaim_event(audit_db, req)
            successes.append(res)
        except Exception as e:
            failures.append(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_worker, req_a)
        f2 = executor.submit(_worker, req_b)
        f1.result()
        f2.result()

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
    assert "EXCESS_RECLAIM" in str(failures[0])

    # No negative balance or over-reclaim
    updated = get_reversal_ledger_entry(audit_db, entry["id"])
    assert updated["status"] == ReversalStatus.FULLY_RECLAIMED.value
    assert updated["cached_reclaimed_cgst_paise"] == 100000
    assert updated["cached_reclaimed_sgst_paise"] == 100000


def test_3g_e_concurrency_test3_concurrent_partial_reclaims(audit_db: InMemorySupabaseClient):
    """Test 3: Concurrent partial reclaims summing to exact balance: Request A: 50,000, Request B: 51,727 paise -> both succeed, final balance exactly 0."""
    total_reversed = 101727  # ₹1,017.27
    entry = _seed_audit_ledger_entry(audit_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, cgst=total_reversed, sgst=0)

    req_a = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-PARTIAL-A",
        reclaim_notes="Partial A",
        idempotency_key="key-part-A",
    )
    req_b = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=51727,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-PARTIAL-B",
        reclaim_notes="Partial B",
        idempotency_key="key-part-B",
    )

    successes = []
    failures = []

    def _worker(req):
        try:
            res = execute_reclaim_event(audit_db, req)
            successes.append(res)
        except Exception as e:
            failures.append(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_worker, req_a)
        f2 = executor.submit(_worker, req_b)
        f1.result()
        f2.result()

    assert len(successes) == 2, f"Both partial reclaims must succeed, failures: {failures}"
    assert len(failures) == 0

    # Total events in db is 2
    evs = audit_db.table("gstr3b_reclaim_events").select("*").eq("ledger_id", entry["id"]).execute().data
    assert len(evs) == 2
    total_reclaimed = sum(int(e["reclaimed_cgst_paise"]) for e in evs)
    assert total_reclaimed == total_reversed

    # Final balance exactly zero
    bal = calculate_available_balance(audit_db, entry["id"])
    assert bal.cgst_paise == 0
    assert bal.total_paise == 0

    updated = get_reversal_ledger_entry(audit_db, entry["id"])
    assert updated["status"] == ReversalStatus.FULLY_RECLAIMED.value
    assert updated["cached_reclaimed_cgst_paise"] == total_reversed


# ---------------------------------------------------------------------------
# 3G-F: TAX-HEAD ISOLATION & BOUNDARY AUDIT
# ---------------------------------------------------------------------------

def test_3g_f_tax_head_cross_borrowing_rejected(audit_db: InMemorySupabaseClient):
    """Cannot reclaim SGST or IGST using available CGST balance."""
    # Entry has only CGST balance (100,000 paise)
    entry = _seed_audit_ledger_entry(audit_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, cgst=100000, sgst=0, igst=0)

    # Attempt to reclaim IGST
    req_igst = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-CROSS-1",
        reclaim_notes="Attempt cross-head IGST",
    )
    with pytest.raises(ValueError) as exc:
        execute_reclaim_event(audit_db, req_igst)
    assert "EXCESS_RECLAIM_IGST" in str(exc.value)

    # Attempt to reclaim SGST
    req_sgst = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_sgst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-CROSS-2",
        reclaim_notes="Attempt cross-head SGST",
    )
    with pytest.raises(ValueError) as exc:
        execute_reclaim_event(audit_db, req_sgst)
    assert "EXCESS_RECLAIM_SGST" in str(exc.value)


def test_3g_f_negative_and_zero_reclaim_amounts_rejected():
    """Negative and zero reclaim amounts are rejected by Pydantic / DB validation."""
    with pytest.raises(ValueError):
        ReclaimEventCreate(
            ledger_id=str(uuid.uuid4()),
            reclaim_run_id=RUN_A2_TGT,
            reclaim_tax_period="2026-06",
            reclaimed_cgst_paise=-500,
            statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
            evidence_reference="UTR-NEG",
            reclaim_notes="Negative amount",
        )

    with pytest.raises(ValueError):
        ReclaimEventCreate(
            ledger_id=str(uuid.uuid4()),
            reclaim_run_id=RUN_A2_TGT,
            reclaim_tax_period="2026-06",
            reclaimed_cgst_paise=0,
            reclaimed_sgst_paise=0,
            statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
            evidence_reference="UTR-ZERO",
            reclaim_notes="Zero amount",
        )


# ---------------------------------------------------------------------------
# 3G-G: LIFECYCLE STATE MACHINE INVALID TRANSITIONS
# ---------------------------------------------------------------------------

def test_3g_g_invalid_lifecycle_transitions_rejected(audit_db: InMemorySupabaseClient):
    """Verify all invalid lifecycle state transitions are rejected."""
    # 1. Non-reclaimable cannot fulfill
    non_rec = _seed_audit_ledger_entry(audit_db, status=ReversalStatus.NON_RECLAIMABLE.value, is_reclaimable=False)
    with pytest.raises(ValueError) as exc:
        fulfill_reversal_condition(audit_db, non_rec["id"], StatutoryEvidenceType.PAYMENT_TO_SUPPLIER, "REF-1")
    assert "REVERSAL_BOUNDARY_VIOLATION" in str(exc.value)

    # 2. Non-reclaimable cannot authorize
    with pytest.raises(ValueError) as exc:
        authorize_reclaim(audit_db, non_rec["id"], authorized_by="user-1")
    assert "REVERSAL_BOUNDARY_VIOLATION" in str(exc.value)

    # 3. Non-reclaimable cannot reclaim
    req_non_rec = ReclaimEventCreate(
        ledger_id=non_rec["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=100,
        statutory_evidence_type=StatutoryEvidenceType.OTHER_STATUTORY_PROOF,
        evidence_reference="REF-NON-REC",
        reclaim_notes="Non-rec reclaim",
    )
    with pytest.raises(ValueError) as exc:
        execute_reclaim_event(audit_db, req_non_rec)
    assert "REVERSAL_ENTRY_IS_NOT_RECLAIMABLE" in str(exc.value)


# ---------------------------------------------------------------------------
# 3G-I: STATUTORY BOUNDARIES (Section 17(5), 16(4), PoS)
# ---------------------------------------------------------------------------

def test_3g_i_statutory_boundaries_strict_isolation(audit_db: InMemorySupabaseClient):
    """Section 17(5) is strictly 4B1 and excluded from 4B2 ledger. Section 16(4) and PoS are strictly 4D2."""
    from unittest.mock import patch
    from tests.test_gstr3b_reversal_ledger import _make_outcome_row

    # Run with 17(5), 16(4), and Rule 37
    r_175 = _make_outcome_row("pm:inv-175", category="blocked_credit", amount=50000, blocked_credit_flag=True)
    r_164 = _make_outcome_row("pm:inv-164", category="ineligible_itc", amount=30000, itc_reason="TIME_BARRED_16_4")
    r_r37 = _make_outcome_row("pm:inv-r37", category="rule37_warnings", amount=20000, rule37_flag=True)

    disps = {
        "pm:inv-175:SEC_17_5": {"disposition": "CONFIRMED_BLOCKED", "exception_type": "SEC_17_5"},
        "pm:inv-r37:RULE_37": {"disposition": "REVERSED", "exception_type": "RULE_37"},
    }

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([r_175, r_164, r_r37], {}, {})), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
             "inv-175": {"record_data": {"igst_paise": 50000}},
             "inv-164": {"record_data": {"igst_paise": 30000, "itcavl": "N", "rsn": "16(4) time barred"}},
             "inv-r37": {"record_data": {"igst_paise": 20000}},
         }), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value=disps), \
         patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[]):

        compiled = compile_gstr3b_table4(audit_db, RUN_A1_SRC)
        sec = compiled["table_4"]

        # 4B1: only 17(5)
        assert sec["section_4b"]["row_4b1_rule38_42_43_sec175"]["igst_paise"] == 50000
        # 4B2: only Rule 37
        assert sec["section_4b"]["row_4b2_others_rule37_37a"]["igst_paise"] == 20000
        # 4D2: only 16(4)
        assert sec["section_4d"]["row_4d2_ineligible_16_4_pos"]["igst_paise"] == 30000
        # 4D1: 0 (no reclaim)
        assert sec["section_4d"]["row_4d1_reclaimed"]["igst_paise"] == 0

        # Register to ledger
        registered = register_table4_reversals_to_ledger(audit_db, RUN_A1_SRC, "user-ca")
        # Exactly 1 row registered (Rule 37)
        assert len(registered) == 1
        assert registered[0]["source_record_id"] == "pm:inv-r37"
        assert registered[0]["statutory_reason"] == StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value


# ---------------------------------------------------------------------------
# 3G-N: SNAPSHOT VERSIONING & DETERMINISTIC SHA-256 HASHING
# ---------------------------------------------------------------------------

def test_3g_n_deterministic_sha256_audit_hashing():
    """Identical canonical payloads produce identical hashes; altering amounts alters hash."""
    p1 = {"run_id": "run-1", "tax_period": "2026-05", "cgst": 10000, "sgst": 10000}
    p2 = {"run_id": "run-1", "tax_period": "2026-05", "cgst": 10000, "sgst": 10000}
    p3 = {"run_id": "run-1", "tax_period": "2026-05", "cgst": 10001, "sgst": 10000}

    hash1 = compute_state_digest(p1)
    hash2 = compute_state_digest(p2)
    hash3 = compute_state_digest(p3)

    assert hash1 == hash2, "Identical payloads must produce identical SHA-256 hash"
    assert hash1 != hash3, "Altered payload must produce different SHA-256 hash"
    assert len(hash1) == 64, "SHA-256 hash must be 64 hex characters"


# ---------------------------------------------------------------------------
# 3G-B & 3G-M: FINALIZED RUN & TARGET SAFETY (REST ENDPOINTS)
# ---------------------------------------------------------------------------

def test_3g_b_and_m_endpoint_guards(
    client: TestClient, auth_headers: dict, audit_db: InMemorySupabaseClient
):
    """Test endpoint-level guardrails: cannot finalize finalized run, cannot reclaim into finalized run, cross-client rejected."""
    entry = _seed_audit_ledger_entry(audit_db, status=ReversalStatus.RECLAIM_AUTHORIZED.value, cgst=50000, sgst=50000)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=audit_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}):

        # 1. Finalize on already finalized run returns 422 (run is already final)
        res_fin = client.post(f"/api/reconciliation/finalize/{RUN_A_FINAL}", headers=auth_headers)
        assert res_fin.status_code == 422
        assert "run is already final" in res_fin.json()["detail"].lower()

        # 2. Reclaim into finalized/locked target run returns 409
        res_rec_final = client.post(
            f"/api/reconciliation/{RUN_A_FINAL}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_cgst_paise": 50000},
        )
        assert res_rec_final.status_code == 409
        assert "finalized reconciliation run" in res_rec_final.json()["detail"].lower()

        # 3. Add adjustment to finalized run returns 409
        res_adj = client.post(
            f"/api/reconcile/runs/{RUN_A_FINAL}/gstr3b/table4/adjust",
            headers=auth_headers,
            json={
                "row_id": "4A5",
                "igst": 100.0,
                "cgst": 0.0,
                "sgst": 0.0,
                "cess": 0.0,
                "adjustment_type": "ADDITION",
                "statutory_category": "OTHER",
                "reason": "Statutory basis explanation for adjustment test",
            },
        )
        assert res_adj.status_code == 409
        assert "finalized reconciliation runs are immutable" in res_adj.json()["detail"].lower()

        # 4. Record disposition on finalized run returns 409
        res_disp = client.post(
            f"/api/reconcile/runs/{RUN_A_FINAL}/dispositions",
            headers=auth_headers,
            json={
                "record_id": "pm:rec-1",
                "exception_type": "RULE_37",
                "disposition": "REVERSED",
                "reason": "Test disposition",
            },
        )
        assert res_disp.status_code == 409
        assert "finalized reconciliation runs are immutable" in res_disp.json()["detail"].lower()

        # 5. Cross-client reclaim attempt returns 403
        res_cross = client.post(
            f"/api/reconciliation/{RUN_B_TGT}/table4/reclaim",
            headers=auth_headers,
            json={"ledger_id": entry["id"], "reclaim_cgst_paise": 50000},
        )
        assert res_cross.status_code == 403


# ---------------------------------------------------------------------------
# 3G-A & 3G-L: AUTHENTICATION & MULTI-TENANT AUTHORIZATION
# ---------------------------------------------------------------------------

def test_3g_a_unauthenticated_requests_return_401(client: TestClient):
    """Unauthenticated requests without Bearer token receive HTTP 401."""
    res1 = client.get(f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger")
    assert res1.status_code == 401

    res2 = client.get(f"/api/reconciliation/{CLIENT_A_ID}/reversal-ledger")
    assert res2.status_code == 401

    res3 = client.get(f"/api/reconciliation/{CLIENT_A_ID}/reclaimable-balances")
    assert res3.status_code == 401

    res4 = client.post(f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/dummy-id/fulfill", json={})
    assert res4.status_code == 401

    res5 = client.post(f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/dummy-id/authorize", json={})
    assert res5.status_code == 401

    res6 = client.post(f"/api/reconciliation/{RUN_A2_TGT}/table4/reclaim", json={})
    assert res6.status_code == 401


def test_3g_a_cross_client_fulfill_and_authorize_rejected(
    client: TestClient, auth_headers: dict, audit_db: InMemorySupabaseClient
):
    """Fulfill and Authorize reject mismatched client run/ledger with HTTP 403."""
    # Entry belongs to Client B, but run belongs to Client A
    entry_b = _seed_audit_ledger_entry(audit_db, client_id=CLIENT_B_ID, source_run_id=RUN_B_TGT)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=audit_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}):

        # 1. Fulfill attempt across clients
        res_f = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{entry_b['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "UTR-CROSS", "payment_date": "2026-06-01"},
        )
        assert res_f.status_code == 403
        assert "different client" in res_f.json()["detail"].lower()

        # 2. Authorize attempt across clients
        res_a = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{entry_b['id']}/authorize",
            headers=auth_headers,
            json={"reclaim_target_period": "2026-06"},
        )
        assert res_a.status_code == 403
        assert "different client" in res_a.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3G-H: STATUTORY EVIDENCE VALIDATION REQUIREMENTS
# ---------------------------------------------------------------------------

def test_3g_h_statutory_evidence_rules(
    client: TestClient, auth_headers: dict, audit_db: InMemorySupabaseClient
):
    """Verify statutory reason specific evidence validation."""
    # Seed Rule 37 entry (requires payment reference/date)
    r37_entry = _seed_audit_ledger_entry(
        audit_db,
        status=ReversalStatus.OPEN.value,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value,
    )
    # Seed Rule 37A entry (requires supplier filing date/ARN)
    r37a_entry = _seed_audit_ledger_entry(
        audit_db,
        status=ReversalStatus.OPEN.value,
        statutory_reason=StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING.value,
    )

    with patch("app.routers.reconciliation_api.get_supabase", return_value=audit_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}):

        # Rule 37 missing evidence -> 422
        res_r37_bad = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{r37_entry['id']}/fulfill",
            headers=auth_headers,
            json={"notes": "No payment reference provided"},
        )
        assert res_r37_bad.status_code == 422
        assert "payment reference" in res_r37_bad.json()["detail"].lower()

        # Rule 37 with payment ref -> 200
        res_r37_good = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{r37_entry['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "NEFT-123456", "payment_date": "2026-06-01"},
        )
        assert res_r37_good.status_code == 200
        assert res_r37_good.json()["status"] == ReversalStatus.CONDITION_FULFILLED.value

        # Rule 37A missing evidence -> 422
        res_r37a_bad = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{r37a_entry['id']}/fulfill",
            headers=auth_headers,
            json={"notes": "No ARN provided"},
        )
        assert res_r37a_bad.status_code == 422
        assert "supplier filing date and arn" in res_r37a_bad.json()["detail"].lower()

        # Rule 37A with filing ARN -> 200
        res_r37a_good = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{r37a_entry['id']}/fulfill",
            headers=auth_headers,
            json={"supplier_filing_arn": "AA2706260000001", "supplier_filing_date": "2026-06-10"},
        )
        assert res_r37a_good.status_code == 200
        assert res_r37a_good.json()["status"] == ReversalStatus.CONDITION_FULFILLED.value


# ---------------------------------------------------------------------------
# 3G-J: IDEMPOTENCY & REPLAY CONTROLS
# ---------------------------------------------------------------------------

def test_3g_j_lifecycle_idempotency_behavior(
    client: TestClient, auth_headers: dict, audit_db: InMemorySupabaseClient
):
    """Repeated fulfill returns 409 Conflict; repeated authorize is idempotent 200."""
    entry = _seed_audit_ledger_entry(audit_db, status=ReversalStatus.OPEN.value)

    with patch("app.routers.reconciliation_api.get_supabase", return_value=audit_db), \
         patch("app.routers.reconciliation_api.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}):

        # 1. First fulfill -> 200
        res_f1 = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "NEFT-IDEMP-1"},
        )
        assert res_f1.status_code == 200

        # 2. Second fulfill on already fulfilled -> 409
        res_f2 = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{entry['id']}/fulfill",
            headers=auth_headers,
            json={"payment_reference": "NEFT-IDEMP-1"},
        )
        assert res_f2.status_code == 409
        assert "cannot fulfill condition" in res_f2.json()["detail"].lower()

        # 3. First authorize -> 200
        res_a1 = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{entry['id']}/authorize",
            headers=auth_headers,
            json={"authorization_reference": "AUTH-IDEMP-1"},
        )
        assert res_a1.status_code == 200

        # 4. Repeated authorize -> idempotent 200
        res_a2 = client.post(
            f"/api/reconciliation/{RUN_A1_SRC}/table4/reversal-ledger/{entry['id']}/authorize",
            headers=auth_headers,
            json={"authorization_reference": "AUTH-IDEMP-1"},
        )
        assert res_a2.status_code == 200
        assert res_a2.json()["status"] == ReversalStatus.RECLAIM_AUTHORIZED.value


# ---------------------------------------------------------------------------
# 3G-P: DATA INTEGRITY / ZERO-LOSS ROLLBACK AUDIT
# ---------------------------------------------------------------------------

def test_3g_p_zero_loss_on_failed_mutation(audit_db: InMemorySupabaseClient):
    """Failed reclaim attempt leaves reversal ledger balances, status, and reclaim events untouched."""
    entry = _seed_audit_ledger_entry(
        audit_db,
        status=ReversalStatus.RECLAIM_AUTHORIZED.value,
        cgst=50000,
        sgst=50000,
    )

    # Attempt to reclaim 60,000 paise (exceeds 50,000 paise available)
    excess_req = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=60000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-EXCESS",
        reclaim_notes="Will fail",
        idempotency_key="key-zero-loss-test",
    )

    with pytest.raises(ValueError) as exc:
        execute_reclaim_event(audit_db, excess_req)
    assert "EXCESS_RECLAIM_CGST" in str(exc.value)

    # Invariants strictly preserved
    post_check = get_reversal_ledger_entry(audit_db, entry["id"])
    assert post_check["status"] == ReversalStatus.RECLAIM_AUTHORIZED.value
    assert post_check["cached_reclaimed_cgst_paise"] == 0
    assert post_check["cached_reclaimed_sgst_paise"] == 0

    events = audit_db.table("gstr3b_reclaim_events").select("*").eq("ledger_id", entry["id"]).execute().data
    assert len(events) == 0, "No orphaned reclaim event must exist after failed validation"

    # Subsequent valid reclaim with identical idempotency key succeeds cleanly
    valid_req = ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=CLIENT_A_ID,
        reclaim_run_id=RUN_A2_TGT,
        reclaim_tax_period="2026-06",
        reclaimed_cgst_paise=50000,
        reclaimed_sgst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-VALID",
        reclaim_notes="Valid execution",
        idempotency_key="key-zero-loss-test",
    )
    res = execute_reclaim_event(audit_db, valid_req)
    assert res.status == ReversalStatus.FULLY_RECLAIMED.value
    assert not res.is_idempotent_replay
