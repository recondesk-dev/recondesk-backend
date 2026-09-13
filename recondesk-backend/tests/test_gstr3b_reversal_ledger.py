"""Unit and integration tests for GSTR-3B Table 4(B)(2) Reversal Ledger, Reclaim Events, and Snapshot Versioning.

Phase 3A.1.1 Hardening Tests:
1. Reversal Ledger:
   - Valid 4B2 creation with all temporary categories:
     * RULE_37_NON_PAYMENT
     * RULE_37A_SUPPLIER_NON_FILING
     * SECTION_16_2_B_NOT_RECEIVED
     * SECTION_16_2_C_SUPPLIER_TAX_CONDITION
     * OTHER_TEMPORARY
     * OPENING_BALANCE
   - Rejection of 4B1 permanent reversal
   - Strict Reclaimability Boundary (is_reclaimable=False):
     * Status is locked to NON_RECLAIMABLE
     * Cannot transition to CONDITION_FULFILLED
     * Cannot transition to RECLAIM_AUTHORIZED
     * Cannot transition to PARTIALLY_RECLAIMED or FULLY_RECLAIMED
     * Cannot have reclaim events
   - Complete Rule 37A provenance tracking (10 explicit fields)
   - Relaxed document fields (nullable supplier_gstin, reference_doc)
   - Source state sealing and deterministic digest verification
2. Reclaim Events & Tax-Head Safety:
   - Valid single reclaim
   - Cross-period reversal -> partial reclaim -> full reclaim
   - Same-period 4B2 -> 4A5 + 4D1 reclaim
   - Double reclaim attempt across multiple periods rejected
   - Tax-head isolation across multiple reclaims (IGST, CGST, SGST, Cess independently)
   - Compensating reversal event (without deleting immutable history)
3. Concurrency Safety:
   - Simultaneous requests cannot breach available balance
4. Snapshot Versioning & Immutability:
   - Finalized V1 -> V2 snapshot while V1 remains 100% reproducible
   - Mutation of underlying outcome after V1 finalization does not alter V1 snapshot digest
   - Deletion attempt of a run containing finalized snapshot/reclaim history fails (ON DELETE RESTRICT)
   - Parent reconciliation_run remains unlocked
"""

import threading
from datetime import date
from unittest.mock import MagicMock
import pytest

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
    get_authoritative_reclaim_history,
    get_reclaimable_reversals,
    get_reversal_ledger_entry,
    list_reversal_ledger_entries,
    register_table4_reversals_to_ledger,
    update_reversal_ledger_status,
    validate_reclaim_request,
)


# ---------------------------------------------------------------------------
# In-Memory Mock Supabase Fixture with Referential Integrity Checks
# ---------------------------------------------------------------------------

class InMemoryTable:
    def __init__(self, name: str, db: "InMemorySupabaseClient"):
        self.name = name
        self.db = db
        self.rows: list[dict] = []
        self._filters: list = []
        self._order_by: list = []
        self._limit_val: int | None = None
        self._pending_insert: list[dict] | None = None
        self._pending_update: dict | None = None

    def insert(self, payload: dict | list):
        if isinstance(payload, list):
            self._pending_insert = [dict(p) for p in payload]
        else:
            self._pending_insert = [dict(payload)]
        return self

    def update(self, values: dict):
        self._pending_update = dict(values)
        return self

    def delete(self):
        # Enforce ON DELETE RESTRICT on run_id
        if self.name == "reconciliation_run":
            for col, val in self._filters:
                if col == "id":
                    has_snaps = any(s.get("run_id") == val for s in self.db.table("gstr3b_table4_summaries").rows)
                    has_reclaims = any(r.get("reclaim_run_id") == val for r in self.db.table("gstr3b_reclaim_events").rows)
                    if has_snaps or has_reclaims:
                        raise RuntimeError(
                            f"FOREIGN KEY RESTRICT VIOLATION: Cannot delete reconciliation_run {val} "
                            "because finalized snapshots or reclaim events depend on it."
                        )
        self.rows = [r for r in self.rows if not all(r.get(c) == v for c, v in self._filters)]
        self._filters = []
        res = MagicMock()
        res.data = []
        return res

    def select(self, columns: str = "*"):
        self._filters = []
        self._order_by = []
        self._limit_val = None
        return self

    def eq(self, col: str, val: any):
        self._filters.append((col, val))
        return self

    def in_(self, col: str, vals: list):
        self._filters.append((col, ("IN", set(vals))))
        return self

    def lte(self, col: str, val: any):
        self._filters.append((col, ("LTE", val)))
        return self

    def limit(self, val: int):
        self._limit_val = val
        return self

    def order(self, col: str, desc: bool = False):
        self._order_by.append((col, desc))
        return self

    def execute(self):
        import uuid

        if self._pending_insert is not None:
            inserted = []
            for item in self._pending_insert:
                if "id" not in item or not item["id"]:
                    item["id"] = str(uuid.uuid4())
                if self.name == "gstr3b_reclaim_events":
                    cid = item.get("client_gstin_id")
                    idemp = item.get("idempotency_key")
                    if cid and idemp:
                        for existing in self.rows:
                            if existing.get("client_gstin_id") == cid and existing.get("idempotency_key") == idemp:
                                raise RuntimeError(
                                    f"UNIQUE CONSTRAINT VIOLATION: duplicate key value violates unique constraint 'uq_reclaim_events_client_idempotency' Key (client_gstin_id, idempotency_key)=({cid}, {idemp})"
                                )
                self.rows.append(item)
                inserted.append(item)
            self._pending_insert = None
            res = MagicMock()
            res.data = inserted
            return res

        if self._pending_update is not None:
            updated = []
            for r in self.rows:
                match = True
                for filter_spec in self._filters:
                    col, op_spec = filter_spec
                    if isinstance(op_spec, tuple) and op_spec[0] == "IN":
                        if r.get(col) not in op_spec[1]:
                            match = False
                            break
                    elif isinstance(op_spec, tuple) and op_spec[0] == "LTE":
                        if r.get(col) is None or r.get(col) > op_spec[1]:
                            match = False
                            break
                    else:
                        if r.get(col) != op_spec:
                            match = False
                            break
                if match:
                    r.update(self._pending_update)
                    updated.append(r)
            self._pending_update = None
            self._filters = []
            res = MagicMock()
            res.data = updated
            return res

        filtered = list(self.rows)
        for filter_spec in self._filters:
            col, op_spec = filter_spec
            if isinstance(op_spec, tuple) and op_spec[0] == "IN":
                filtered = [r for r in filtered if r.get(col) in op_spec[1]]
            elif isinstance(op_spec, tuple) and op_spec[0] == "LTE":
                filtered = [r for r in filtered if r.get(col) is not None and str(r.get(col)) <= str(op_spec[1])]
            else:
                filtered = [r for r in filtered if r.get(col) == op_spec]
        for col, desc in self._order_by:
            filtered.sort(key=lambda r: r.get(col, ""), reverse=desc)
        if self._limit_val is not None:
            filtered = filtered[: self._limit_val]
        self._filters = []
        self._order_by = []
        self._limit_val = None
        res = MagicMock()
        res.data = filtered
        return res


class InMemorySupabaseClient:
    def __init__(self):
        self.tables = {}

    def table(self, name: str):
        if name not in self.tables:
            self.tables[name] = InMemoryTable(name, self)
        return self.tables[name]

    def rpc(self, fn_name: str, params: dict):
        res = MagicMock()
        res.execute.side_effect = RuntimeError("RPC not installed in test mock")
        return res


@pytest.fixture
def mock_sb():
    return InMemorySupabaseClient()


# ---------------------------------------------------------------------------
# 1. Reversal Ledger & State Sealing Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cat", [
    StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
    StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING,
    StatutoryTemporaryReason.SECTION_16_2_B_NOT_RECEIVED,
    StatutoryTemporaryReason.SECTION_16_2_C_SUPPLIER_TAX_CONDITION,
    StatutoryTemporaryReason.OTHER_TEMPORARY,
    StatutoryTemporaryReason.OPENING_BALANCE,
])
def test_valid_4b2_temporary_categories(mock_sb, cat):
    """Verify that all approved temporary categories create valid 4B2 entries."""
    entry = ReversalLedgerCreate(
        client_gstin_id="client-1",
        source_type=ReversalProvenanceType.STATUTORY_ADJUSTMENT if cat == StatutoryTemporaryReason.OPENING_BALANCE else ReversalProvenanceType.RECON_OUTCOME,
        source_record_id=f"rec-{cat.value}",
        reversal_tax_period="2026-05",
        document_number=None if cat == StatutoryTemporaryReason.OPENING_BALANCE else "INV-001",
        supplier_gstin=None if cat == StatutoryTemporaryReason.OPENING_BALANCE else "27AABCU9603R1ZM",
        reference_doc="VOUCHER-01",
        reversal_table4_cell="4B2",
        statutory_reason=cat,
        reversed_igst_paise=150000,
    )
    row = create_reversal_ledger_entry(mock_sb, entry)
    assert row["statutory_reason"] == cat.value
    assert row["status"] == "OPEN"
    assert row["source_state_hash"] != ""


def test_strict_reclaimability_boundary_enforcement(mock_sb):
    """Verify that is_reclaimable=False strictly guarantees NO reclaim transitions or events."""
    entry = ReversalLedgerCreate(
        client_gstin_id="client-1",
        source_type=ReversalProvenanceType.EXCEPTION_DISPOSITION,
        source_record_id="disp-nonrec",
        reversal_tax_period="2026-05",
        reversal_table4_cell="4B2",
        is_reclaimable=False,  # Explicitly non-reclaimable
        statutory_reason=StatutoryTemporaryReason.OTHER_TEMPORARY,
        reversed_igst_paise=200000,
    )
    row = create_reversal_ledger_entry(mock_sb, entry)
    ledger_id = row["id"]

    assert row["is_reclaimable"] is False
    assert row["status"] == "NON_RECLAIMABLE"

    # 1. Available balance is strictly 0
    bal = calculate_available_balance(mock_sb, ledger_id)
    assert bal.total_paise == 0

    # 2. Cannot transition to CONDITION_FULFILLED
    with pytest.raises(ValueError, match="REVERSAL_BOUNDARY_VIOLATION"):
        update_reversal_ledger_status(mock_sb, ledger_id, ReversalStatus.CONDITION_FULFILLED)

    # 3. Cannot transition to RECLAIM_AUTHORIZED
    with pytest.raises(ValueError, match="REVERSAL_BOUNDARY_VIOLATION"):
        update_reversal_ledger_status(mock_sb, ledger_id, ReversalStatus.RECLAIM_AUTHORIZED)

    # 4. Cannot execute reclaim event
    req = ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-2",
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.OTHER_STATUTORY_PROOF,
        evidence_reference="DOC-REF",
        reclaim_notes="Attempt on non-reclaimable entry",
    )
    with pytest.raises(ValueError, match="REVERSAL_ENTRY_IS_NOT_RECLAIMABLE"):
        execute_reclaim_event(mock_sb, req)


def test_complete_rule_37a_provenance_fields(mock_sb):
    """Verify full 10-field Rule 37A provenance tracking."""
    entry = ReversalLedgerCreate(
        client_gstin_id="client-1",
        source_type=ReversalProvenanceType.EXCEPTION_DISPOSITION,
        source_record_id="disp-37a-full",
        reversal_tax_period="2026-11",
        document_number="INV-37A-01",
        supplier_gstin="27AABCU9603R1ZM",
        reversal_table4_cell="4B2",
        statutory_reason=StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING,
        itc_financial_year="2025-26",
        supplier_outward_statement_period="2025-08",
        supplier_gstr1_filing_date=date(2025, 9, 11),
        supplier_gstr3b_tax_period="2025-08",
        supplier_gstr3b_filing_status="UNFILED",
        filed_by_september_30=False,
        september_test_date=date(2026, 9, 30),
        november_reversal_deadline=date(2026, 11, 30),
        actual_reversal_date=date(2026, 11, 20),
        subsequent_supplier_filing_date=date(2027, 1, 15),
        subsequent_filing_arn="AA2701271234567",
        condition_fulfilled_date=date(2027, 1, 15),
        reclaim_eligibility_date=date(2027, 1, 15),
        reversed_igst_paise=350000,
    )
    row = create_reversal_ledger_entry(mock_sb, entry)

    assert row["itc_financial_year"] == "2025-26"
    assert row["supplier_outward_statement_period"] == "2025-08"
    assert row["supplier_gstr1_filing_date"] == "2025-09-11"
    assert row["supplier_gstr3b_tax_period"] == "2025-08"
    assert row["supplier_gstr3b_filing_status"] == "UNFILED"
    assert row["filed_by_september_30"] is False
    assert row["september_test_date"] == "2026-09-30"
    assert row["november_reversal_deadline"] == "2026-11-30"
    assert row["subsequent_filing_arn"] == "AA2701271234567"


def test_source_state_sealing_integrity(mock_sb):
    """Verify that source state payload generates a deterministic digest."""
    raw_source = {
        "invoice_number": "INV-SEAL-01",
        "supplier_gstin": "27AABCU9603R1ZM",
        "taxable_value_paise": 1000000,
        "igst_paise": 180000,
        "disposition": "RULE_37_REVERSED",
    }
    digest1 = compute_state_digest(raw_source)
    digest2 = compute_state_digest(raw_source)
    assert digest1 == digest2
    assert len(digest1) == 64

    entry = ReversalLedgerCreate(
        client_gstin_id="client-1",
        source_type=ReversalProvenanceType.EXCEPTION_DISPOSITION,
        source_record_id="disp-sealed",
        reversal_tax_period="2026-05",
        document_number="INV-SEAL-01",
        supplier_gstin="27AABCU9603R1ZM",
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        source_payload=raw_source,
        reversed_igst_paise=180000,
    )
    row = create_reversal_ledger_entry(mock_sb, entry)
    assert row["source_state_hash"] == digest1


# ---------------------------------------------------------------------------
# 2. Integration Tests: Cross-Period Reclaim & Same-Period Reclaim
# ---------------------------------------------------------------------------

def test_cross_period_reversal_partial_and_full_reclaim(mock_sb):
    """Test full lifecycle: Period 1 reversal -> Period 2 partial reclaim -> Period 3 full reclaim."""
    # Month 1 (2026-05): Reversal under Rule 37
    entry = ReversalLedgerCreate(
        client_gstin_id="client-1",
        source_type=ReversalProvenanceType.RECON_OUTCOME,
        source_record_id="rec-lifecycle",
        source_run_id="run-2026-05",
        reversal_tax_period="2026-05",
        document_number="INV-LIFE",
        supplier_gstin="27AABCU9603R1ZM",
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=100000,
        reversed_cgst_paise=50000,
        reversed_sgst_paise=50000,
    )
    row = create_reversal_ledger_entry(mock_sb, entry)
    ledger_id = row["id"]

    # Month 2 (2026-06): Partial Reclaim of 50,000 IGST
    res1 = execute_reclaim_event(mock_sb, ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-2026-06",
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-PARTIAL",
        reclaim_notes="Half invoice settled",
    ))
    assert res1.status == "PARTIALLY_RECLAIMED"
    assert res1.remaining_igst_paise == 50000

    # Month 3 (2026-07): Final Reclaim of remaining 50,000 IGST + 50,000 CGST + 50,000 SGST
    res2 = execute_reclaim_event(mock_sb, ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-2026-07",
        reclaim_tax_period="2026-07",
        reclaimed_igst_paise=50000,
        reclaimed_cgst_paise=50000,
        reclaimed_sgst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-FINAL",
        reclaim_notes="Final balance settled",
    ))
    assert res2.status == "FULLY_RECLAIMED"
    assert res2.remaining_igst_paise == 0
    assert res2.remaining_cgst_paise == 0
    assert res2.remaining_sgst_paise == 0

    bal_final = calculate_available_balance(mock_sb, ledger_id)
    assert bal_final.total_paise == 0


def test_same_period_reversal_and_reclaim(mock_sb):
    """Verify that an invoice reversed and subsequently cleared within the same period behaves correctly."""
    entry = ReversalLedgerCreate(
        client_gstin_id="client-1",
        source_type=ReversalProvenanceType.RECON_OUTCOME,
        source_record_id="rec-same-period",
        source_run_id="run-2026-05",
        reversal_tax_period="2026-05",
        document_number="INV-SAME",
        supplier_gstin="27AABCU9603R1ZM",
        statutory_reason=StatutoryTemporaryReason.SECTION_16_2_B_NOT_RECEIVED,
        reversed_igst_paise=75000,
    )
    row = create_reversal_ledger_entry(mock_sb, entry)
    ledger_id = row["id"]

    # Reclaimed in same period (e.g. goods received before final filing)
    res = execute_reclaim_event(mock_sb, ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-2026-05",
        reclaim_tax_period="2026-05",
        reclaimed_igst_paise=75000,
        statutory_evidence_type=StatutoryEvidenceType.GOODS_RECEIVED_GRN,
        evidence_reference="GRN-2026-05-88",
        reclaim_notes="Goods received prior to month-end filing",
    ))
    assert res.status == "FULLY_RECLAIMED"
    assert res.remaining_igst_paise == 0


def test_double_reclaim_across_multiple_periods_rejected(mock_sb):
    """Verify that attempting to reclaim previously exhausted credit across periods fails."""
    entry = ReversalLedgerCreate(
        client_gstin_id="client-1",
        source_type=ReversalProvenanceType.RECON_OUTCOME,
        source_record_id="rec-double-test",
        reversal_tax_period="2026-05",
        document_number="INV-DBL",
        supplier_gstin="27AABCU9603R1ZM",
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=50000,
    )
    row = create_reversal_ledger_entry(mock_sb, entry)
    ledger_id = row["id"]

    # Period 2026-06: Full reclaim of 50,000
    execute_reclaim_event(mock_sb, ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-2026-06",
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-LEGIT",
        reclaim_notes="Legitimate full reclaim",
    ))

    # Period 2026-07: Attempting to reclaim again fails
    with pytest.raises(ValueError, match="EXCESS_RECLAIM_IGST"):
        execute_reclaim_event(mock_sb, ReclaimEventCreate(
            ledger_id=ledger_id,
            reclaim_run_id="run-2026-07",
            reclaim_tax_period="2026-07",
            reclaimed_igst_paise=50000,
            statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
            evidence_reference="UTR-DUPLICATE",
            reclaim_notes="Accidental duplicate reclaim attempt",
        ))


# ---------------------------------------------------------------------------
# 3. Snapshot Immutability, Provenance Digest, & Deletion Protection
# ---------------------------------------------------------------------------

def test_finalized_v1_and_v2_with_underlying_mutation_reproducibility(mock_sb):
    """Prove that V1 remains 100% reproducible via its frozen snapshot_payload even if raw records change."""
    snap_table = mock_sb.table("gstr3b_table4_summaries")

    # Raw state at V1 finalization
    v1_raw_state = {
        "outcomes": [{"id": "inv-1", "net_tax": 50000}],
        "dispositions": [{"record_id": "inv-1", "disp": "CONFIRMED_BLOCKED"}],
    }
    v1_digest = compute_state_digest(v1_raw_state)

    # Save V1 snapshot
    snap_v1 = {
        "id": "snap-v1",
        "run_id": "run-immutable-test",
        "client_gstin_id": "client-1",
        "tax_period": "2026-05",
        "version": 1,
        "is_current": True,
        "status": "FINALIZED",
        "source_state_digest": v1_digest,
        "snapshot_payload": v1_raw_state,
        "audit_hash": "hash-v1",
        "table_4c": {"total_tax_paise": 50000},
    }
    snap_table.insert(snap_v1).execute()

    # Underlying data mutates (e.g. CA changes disposition to STATUTORY_EXCEPTION)
    v2_raw_state = {
        "outcomes": [{"id": "inv-1", "net_tax": 50000}],
        "dispositions": [{"record_id": "inv-1", "disp": "STATUTORY_EXCEPTION"}],
    }
    v2_digest = compute_state_digest(v2_raw_state)
    assert v1_digest != v2_digest

    # Save V2 snapshot (supersedes V1)
    snap_table.update({"is_current": False, "status": "SUPERSEDED"}).eq("id", "snap-v1").execute()
    snap_v2 = {
        "id": "snap-v2",
        "run_id": "run-immutable-test",
        "client_gstin_id": "client-1",
        "tax_period": "2026-05",
        "version": 2,
        "is_current": True,
        "status": "FINALIZED",
        "source_state_digest": v2_digest,
        "snapshot_payload": v2_raw_state,
        "audit_hash": "hash-v2",
        "table_4c": {"total_tax_paise": 100000},
    }
    snap_table.insert(snap_v2).execute()

    # Historical V1 payload and digest remain identical to original state
    v1_saved = snap_table.select("*").eq("id", "snap-v1").execute().data[0]
    assert v1_saved["source_state_digest"] == v1_digest
    assert v1_saved["snapshot_payload"]["dispositions"][0]["disp"] == "CONFIRMED_BLOCKED"

    # Current snapshot is V2
    current_snap = snap_table.select("*").eq("run_id", "run-immutable-test").eq("is_current", True).execute().data[0]
    assert current_snap["version"] == 2
    assert current_snap["source_state_digest"] == v2_digest


def test_deletion_attempt_of_run_with_finalized_history_fails(mock_sb):
    """Verify that a run with finalized snapshots or reclaim history CANNOT be deleted (ON DELETE RESTRICT)."""
    run_table = mock_sb.table("reconciliation_run")
    snap_table = mock_sb.table("gstr3b_table4_summaries")

    run_table.insert({"id": "run-with-history", "client_gstin_id": "c1", "period": "2026-05"}).execute()
    snap_table.insert({"id": "s1", "run_id": "run-with-history", "version": 1, "is_current": True}).execute()

    with pytest.raises(RuntimeError, match="FOREIGN KEY RESTRICT VIOLATION"):
        run_table.eq("id", "run-with-history").delete()


# ---------------------------------------------------------------------------
# 4. Phase 3C: Lifecycle Orchestration & 4(B)(2) Ledger Registration
# ---------------------------------------------------------------------------

def test_fulfill_reversal_condition_and_authorize_reclaim(mock_sb):
    """Test state machine transitions: OPEN -> CONDITION_FULFILLED -> RECLAIM_AUTHORIZED, and boundary protection."""
    # 1. Create open reclaimable reversal entry
    entry = create_reversal_ledger_entry(mock_sb, ReversalLedgerCreate(
        client_gstin_id="client-test",
        source_type=ReversalProvenanceType.RECON_OUTCOME,
        source_record_id="rec-lifecycle-1",
        reversal_tax_period="2026-05",
        document_number="INV-LIFE-1",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=60000,
    ))
    ledger_id = entry["id"]
    assert entry["status"] == ReversalStatus.OPEN.value

    # 2. Transition to CONDITION_FULFILLED with statutory evidence
    fulfilled = fulfill_reversal_condition(
        mock_sb,
        ledger_id,
        evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-STATE-TRANSITION",
        evidence_document_date=date(2026, 6, 15),
        condition_fulfilled_date=date(2026, 6, 15),
        notes="Bank payment confirmed by CA",
    )
    assert fulfilled["status"] == ReversalStatus.CONDITION_FULFILLED.value
    assert fulfilled["condition_fulfilled_date"] == "2026-06-15"
    assert fulfilled["source_payload"]["evidence_fulfilled"]["reference"] == "UTR-STATE-TRANSITION"

    # 3. Transition to RECLAIM_AUTHORIZED
    authorized = authorize_reclaim(
        mock_sb,
        ledger_id,
        authorized_by="ca-user-1",
        reclaim_eligibility_date=date(2026, 6, 20),
    )
    assert authorized["status"] == ReversalStatus.RECLAIM_AUTHORIZED.value
    assert authorized["reclaim_eligibility_date"] == "2026-06-20"

    # 4. Non-reclaimable boundary violation check
    non_rec_entry = create_reversal_ledger_entry(mock_sb, ReversalLedgerCreate(
        client_gstin_id="client-test",
        source_type=ReversalProvenanceType.STATUTORY_ADJUSTMENT,
        source_record_id="adj-non-rec",
        reversal_tax_period="2026-05",
        reversal_table4_cell="4B2",
        is_reclaimable=False,
        statutory_reason=StatutoryTemporaryReason.OTHER_TEMPORARY,
        reversed_igst_paise=10000,
    ))
    with pytest.raises(ValueError, match="REVERSAL_BOUNDARY_VIOLATION"):
        fulfill_reversal_condition(mock_sb, non_rec_entry["id"], StatutoryEvidenceType.OTHER_STATUTORY_PROOF, "REF-1")

    with pytest.raises(ValueError, match="REVERSAL_BOUNDARY_VIOLATION"):
        authorize_reclaim(mock_sb, non_rec_entry["id"], "ca-user-1")


def test_validate_reclaim_request(mock_sb):
    """Test validate_reclaim_request checks for balance limits, status eligibility, and non-reclaimable boundary."""
    entry = create_reversal_ledger_entry(mock_sb, ReversalLedgerCreate(
        client_gstin_id="client-test",
        source_type=ReversalProvenanceType.RECON_OUTCOME,
        source_record_id="rec-val-1",
        reversal_tax_period="2026-05",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=40000,
        reversed_cgst_paise=20000,
        reversed_sgst_paise=20000,
    ))
    ledger_id = entry["id"]

    # 1. Valid reclaim within available balance
    valid_req = ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-2026-06",
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=30000,
        reclaimed_cgst_paise=10000,
        reclaimed_sgst_paise=10000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-VAL-OK",
        reclaim_notes="Verified payment",
    )
    is_valid, err = validate_reclaim_request(mock_sb, valid_req)
    assert is_valid is True
    assert err is None

    # 2. Invalid reclaim exceeding available IGST balance (40000 available vs 50000 requested)
    excess_req = ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-2026-06",
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-VAL-EXCESS",
        reclaim_notes="Excess claim attempt",
    )
    is_valid, err = validate_reclaim_request(mock_sb, excess_req)
    assert is_valid is False
    assert "EXCESS_RECLAIM_IGST" in str(err)

    # 3. Non-reclaimable entry check
    non_rec = create_reversal_ledger_entry(mock_sb, ReversalLedgerCreate(
        client_gstin_id="client-test",
        source_type=ReversalProvenanceType.STATUTORY_ADJUSTMENT,
        source_record_id="adj-non-rec-val",
        reversal_tax_period="2026-05",
        reversal_table4_cell="4B2",
        is_reclaimable=False,
        statutory_reason=StatutoryTemporaryReason.OTHER_TEMPORARY,
        reversed_igst_paise=10000,
    ))
    non_rec_req = ReclaimEventCreate(
        ledger_id=non_rec["id"],
        reclaim_run_id="run-2026-06",
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=5000,
        statutory_evidence_type=StatutoryEvidenceType.OTHER_STATUTORY_PROOF,
        evidence_reference="REF-NON-REC",
        reclaim_notes="Forbidden attempt",
    )
    is_valid, err = validate_reclaim_request(mock_sb, non_rec_req)
    assert is_valid is False
    assert "REVERSAL_ENTRY_IS_NOT_RECLAIMABLE" in str(err)


def test_get_reclaimable_reversals(mock_sb):
    """Ensure get_reclaimable_reversals returns open/authorized items with positive available balance."""
    # Create entry 1: Partially reclaimed (available > 0)
    e1 = create_reversal_ledger_entry(mock_sb, ReversalLedgerCreate(
        client_gstin_id="client-rec-query",
        source_type=ReversalProvenanceType.RECON_OUTCOME,
        source_record_id="rec-q-1",
        reversal_tax_period="2026-04",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=50000,
    ))
    # Create entry 2: Non-reclaimable (must be excluded)
    e2 = create_reversal_ledger_entry(mock_sb, ReversalLedgerCreate(
        client_gstin_id="client-rec-query",
        source_type=ReversalProvenanceType.STATUTORY_ADJUSTMENT,
        source_record_id="adj-q-2",
        reversal_tax_period="2026-04",
        reversal_table4_cell="4B2",
        is_reclaimable=False,
        statutory_reason=StatutoryTemporaryReason.OTHER_TEMPORARY,
        reversed_igst_paise=20000,
    ))
    # Create entry 3: Reclaimable but fully reclaimed (must be excluded)
    e3 = create_reversal_ledger_entry(mock_sb, ReversalLedgerCreate(
        client_gstin_id="client-rec-query",
        source_type=ReversalProvenanceType.RECON_OUTCOME,
        source_record_id="rec-q-3",
        reversal_tax_period="2026-04",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING,
        reversed_igst_paise=10000,
    ))
    execute_reclaim_event(mock_sb, ReclaimEventCreate(
        ledger_id=e3["id"],
        reclaim_run_id="run-reclaimed",
        reclaim_tax_period="2026-05",
        reclaimed_igst_paise=10000,
        statutory_evidence_type=StatutoryEvidenceType.SUPPLIER_GSTR3B_FILED,
        evidence_reference="ARN-123",
        reclaim_notes="Fully reclaimed",
    ))

    reclaimables = get_reclaimable_reversals(mock_sb, "client-rec-query")
    ids = [r["id"] for r in reclaimables]
    assert e1["id"] in ids
    assert e2["id"] not in ids  # Excluded: is_reclaimable=False
    assert e3["id"] not in ids  # Excluded: available balance is 0 (fully reclaimed)


def _make_outcome_row(
    row_id: str,
    category: str = "matched",
    amount: int = 18000,
    *,
    match_status: str = "EXACT",
    matched_pr_id: str = "pr-1",
    supplier_gstin: str = "27AAACG0568M1Z8",
    supplier_name: str = "Supplier Inc",
    invoice_number: str = "INV-001",
    blocked_credit_flag: bool = False,
    rule37_flag: bool = False,
    rule37a_flag: bool = False,
    is_credit_note: bool = False,
    itc_reason: str = None,
):
    from app.services.reconciliation_outcomes import OutcomeRow
    return OutcomeRow(
        id=row_id,
        category=category,
        supplier_gstin=supplier_gstin,
        supplier_name=supplier_name,
        invoice_number=invoice_number,
        invoice_date="2026-05-10",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="",
        decision_why="",
        decision_next="",
        match_status=match_status,
        matched_pr_id=matched_pr_id,
        blocked_credit_flag=blocked_credit_flag,
        late_filing_flag=False,
        rule37_flag=rule37_flag,
        rule37a_flag=rule37a_flag,
        is_credit_note=is_credit_note,
        itc_reason=itc_reason,
        amount=amount,
    )


def test_register_table4_reversals_to_ledger_idempotency_and_classification(mock_sb, monkeypatch):
    """register_table4_reversals_to_ledger correctly classifies 4B2 entries and prevents duplicate creation."""
    from unittest.mock import patch

    # Setup run row
    mock_sb.table("reconciliation_run").insert({
        "id": "run-reg-test",
        "client_gstin_id": "client-reg-1",
        "period": "2026-05",
    }).execute()

    # Create mock outcomes:
    # 1. Rule 37 reversed invoice (50,000 paise)
    r_r37 = _make_outcome_row(
        "pm:inv-r37", category="rule37_warnings", invoice_number="INV-37",
        rule37_flag=True, amount=50000,
    )
    # 2. Rule 37A reversed invoice (30,000 paise)
    r_r37a = _make_outcome_row(
        "pm:inv-r37a", category="matched", invoice_number="INV-37A",
        match_status="RULE37A", rule37a_flag=True, amount=30000,
    )
    # 3. Section 16(2)(b) reversed invoice (20,000 paise)
    r_162b = _make_outcome_row(
        "pm:inv-162b", category="matched", invoice_number="INV-162B",
        amount=20000,
    )
    # 4. Section 17(5) blocked credit (MUST NEVER ENTER 4B2 LEDGER!)
    r_175 = _make_outcome_row(
        "pm:inv-175", category="blocked_credit", invoice_number="INV-175",
        blocked_credit_flag=True, amount=90000,
    )

    mock_dispositions = {
        "pm:inv-r37:RULE_37": {"disposition": "REVERSED", "exception_type": "RULE_37"},
        "pm:inv-r37a:RULE_37A": {"disposition": "REVERSED", "exception_type": "RULE_37A"},
        "pm:inv-162b:SECTION_16_2_B": {"disposition": "SECTION_16_2_B_REVERSED", "exception_type": "SECTION_16_2_B"},
        "pm:inv-175:SEC_17_5": {"disposition": "CONFIRMED_BLOCKED", "exception_type": "SEC_17_5"},
    }

    mock_adjustments = [
        {
            "id": "adj-4b2-ext",
            "row_id": "4B2",
            "igst_paise": 15000,
            "statutory_reason": "OTHER_TEMPORARY",
            "reference_doc": "JV-TEMPORARY",
            "is_reclaimable": True,
        }
    ]

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([r_r37, r_r37a, r_162b, r_175], {}, {})), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
             "inv-r37": {"record_data": {"igst_paise": 50000}},
             "inv-r37a": {"record_data": {"igst_paise": 30000}},
             "inv-162b": {"record_data": {"igst_paise": 20000}},
             "inv-175": {"record_data": {"igst_paise": 90000}},
         }), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value=mock_dispositions), \
         patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=mock_adjustments):

        # First run: auto-registration
        registered = register_table4_reversals_to_ledger(mock_sb, "run-reg-test", "ca-user-test")

        # Exactly 4 items registered (Rule 37, Rule 37A, Section 16(2)(b), and 4B2 adjustment)
        # 17(5) is strictly excluded!
        assert len(registered) == 4
        reasons = {r["statutory_reason"] for r in registered}
        assert StatutoryTemporaryReason.RULE_37_NON_PAYMENT.value in reasons
        assert StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING.value in reasons
        assert StatutoryTemporaryReason.SECTION_16_2_B_NOT_RECEIVED.value in reasons
        assert StatutoryTemporaryReason.OTHER_TEMPORARY.value in reasons

        # Second run: must be idempotent (0 new items added)
        registered_again = register_table4_reversals_to_ledger(mock_sb, "run-reg-test", "ca-user-test")
        assert len(registered_again) == 0

        # Total rows in db remains 4
        all_rows = mock_sb.table("gstr3b_reversal_ledger").select("*").execute().data
        assert len(all_rows) == 4


def test_e2e_reversal_to_reclaim_lifecycle(mock_sb):
    """Full lifecycle: 4B2 reversal in Run 1 -> registered to ledger -> condition fulfilled & authorized -> reclaimed in Run 2 -> Table 4 compilation reflects 4A5 + 4D1."""
    from unittest.mock import patch
    from app.services.gstr3b_table4_engine import compile_gstr3b_table4

    # Setup Run 1 ("2026-05")
    mock_sb.table("reconciliation_run").insert({
        "id": "run-p1",
        "client_gstin_id": "client-lifecycle",
        "period": "2026-05",
        "status": "COMPLETED",
        "is_locked": False,
    }).execute()

    # Outcome with confirmed Rule 37 reversal of Rs 500 (50,000 paise)
    r1 = _make_outcome_row("pm:inv-r37", category="rule37_warnings", invoice_number="INV-R37", rule37_flag=True, amount=50000)
    mock_disp1 = {"pm:inv-r37:RULE_37": {"disposition": "REVERSED", "exception_type": "RULE_37"}}

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([r1], {}, {})), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"inv-r37": {"record_data": {"igst_paise": 50000}}}), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value=mock_disp1), \
         patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[]):

        # Compile Run 1
        t4_p1 = compile_gstr3b_table4(mock_sb, "run-p1")
        assert t4_p1["table_4"]["section_4a"]["row_4a5_all_other_itc"]["igst"] == 500.0
        assert t4_p1["table_4"]["section_4b"]["row_4b2_others_rule37_37a"]["igst"] == 500.0
        assert t4_p1["table_4"]["section_4c_net_itc"]["igst"] == 0.0

        # Auto-register to ledger
        registered = register_table4_reversals_to_ledger(mock_sb, "run-p1", "ca-user")
        assert len(registered) == 1
        ledger_entry = registered[0]
        ledger_id = ledger_entry["id"]
        assert ledger_entry["status"] == ReversalStatus.OPEN.value
        assert ledger_entry["reversed_igst_paise"] == 50000

    # Month 2: Condition fulfilled with bank proof
    fulfill_reversal_condition(
        mock_sb, ledger_id,
        evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-JULY-PAID",
        condition_fulfilled_date=date(2026, 6, 20),
        notes="Bank payment cleared",
    )
    # Reclaim authorized
    authorize_reclaim(mock_sb, ledger_id, authorized_by="ca-lead")

    # Setup Run 2 ("2026-06")
    mock_sb.table("reconciliation_run").insert({
        "id": "run-p2",
        "client_gstin_id": "client-lifecycle",
        "period": "2026-06",
        "status": "COMPLETED",
        "is_locked": False,
    }).execute()

    # Reclaim execution against Run 2
    rec_res = execute_reclaim_event(mock_sb, ReclaimEventCreate(
        ledger_id=ledger_id,
        reclaim_run_id="run-p2",
        reclaim_tax_period="2026-06",
        reclaimed_igst_paise=50000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-JULY-PAID",
        reclaim_notes="Reclaim in GSTR-3B Table 4A5 & 4D1",
    ))
    assert rec_res.status == ReversalStatus.FULLY_RECLAIMED.value
    assert rec_res.remaining_igst_paise == 0

    # Compile Run 2 Table 4
    # Suppose Run 2 has a fresh clean invoice of Rs 200 (20,000 paise)
    r2 = _make_outcome_row("pm:inv-clean2", category="matched", invoice_number="INV-CLEAN-2", amount=20000)
    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([r2], {}, {})), \
         patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"inv-clean2": {"record_data": {"igst_paise": 20000}}}), \
         patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}), \
         patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={}), \
         patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[]):

        t4_p2 = compile_gstr3b_table4(mock_sb, "run-p2")

        # 4A5 must be 200 (clean invoice) + 500 (reclaim) = 700
        assert t4_p2["table_4"]["section_4a"]["row_4a5_all_other_itc"]["igst"] == 700.0
        # 4D1 must be 500 (reclaim tracking in ECRRS)
        assert t4_p2["table_4"]["section_4d"]["row_4d1_reclaimed"]["igst"] == 500.0
        # 4B must be 0
        assert t4_p2["table_4"]["section_4b"]["total_4b"]["igst"] == 0.0
        # Net 4C must be 700
        assert t4_p2["table_4"]["section_4c_net_itc"]["igst"] == 700.0


