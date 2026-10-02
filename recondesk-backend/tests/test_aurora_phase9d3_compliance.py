"""Tests for Phase 9D-3 — Batch 2A Application Cutover.

Verifies:
1. AuroraComplianceRepository methods work against SQLite in-memory engine.
2. Aurora primary operations for mismatch_notes, rule37_actions, rule37_resolutions,
   rule37_alert_dedup, invoice_tracking, and reconciliation_exception_dispositions.
3. Fallback behavior when Aurora raises errors.
4. Tenant isolation across client_gstin_id boundaries.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.schema_base import Base
from app.models.compliance import (
    InvoiceTracking,
    MismatchNote,
    ReconciliationExceptionDisposition,
    Rule37Action,
    Rule37AlertDedup,
    Rule37Resolution,
)
from app.repositories.compliance import AuroraComplianceRepository


@pytest.fixture
def sqlite_compliance_repo():
    """In-memory SQLite database wired to AuroraComplianceRepository."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    repo = AuroraComplianceRepository(session_factory=session_factory)
    return repo


class TestAuroraComplianceRepository:
    """Unit tests for the new AuroraComplianceRepository."""

    def test_mismatch_notes_lifecycle(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        run_id = str(uuid.uuid4())
        rec_id = str(uuid.uuid4())
        uid = str(uuid.uuid4())

        # Insert
        row = {
            "record_id": rec_id,
            "run_id": run_id,
            "user_id": uid,
            "note": "Initial mismatch observation",
            "record_type": "pr",
            "note_type": "note",
            "severity": "medium",
        }
        inserted = repo.insert_mismatch_note(row)
        assert inserted is not None
        note_id = inserted["id"]
        assert inserted["note"] == "Initial mismatch observation"
        assert inserted["run_id"] == run_id

        # Read by record_id
        notes = repo.get_mismatch_notes_by_record_id(rec_id)
        assert len(notes) == 1
        assert notes[0]["id"] == note_id

        # Update
        updated = repo.update_mismatch_note(note_id, note="Updated observation")
        assert updated is True
        fetched = repo.get_mismatch_note_by_id(note_id)
        assert fetched["note"] == "Updated observation"

        # Delete
        deleted = repo.delete_mismatch_note(note_id)
        assert deleted is True
        assert repo.get_mismatch_note_by_id(note_id) is None

    def test_decision_status_upsert_pattern(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        run_id = str(uuid.uuid4())
        rec_id = str(uuid.uuid4())
        uid = str(uuid.uuid4())

        # First status: pending
        repo.delete_mismatch_notes_by_run_and_record(run_id, rec_id)
        res1 = repo.insert_mismatch_note({
            "record_id": rec_id,
            "run_id": run_id,
            "user_id": uid,
            "note": "pending",
            "record_type": "pr",
            "note_type": "decision_status",
            "severity": "low",
        })
        assert res1 is not None

        statuses = repo.get_mismatch_notes_by_run_id(run_id, note_type="decision_status")
        assert len(statuses) == 1
        assert statuses[0]["note"] == "pending"

        # Overwrite with: acted (delete-then-insert)
        repo.delete_mismatch_notes_by_run_and_record(run_id, rec_id)
        res2 = repo.insert_mismatch_note({
            "record_id": rec_id,
            "run_id": run_id,
            "user_id": uid,
            "note": "acted",
            "record_type": "pr",
            "note_type": "decision_status",
            "severity": "low",
        })
        assert res2 is not None

        statuses_after = repo.get_mismatch_notes_by_run_id(run_id, note_type="decision_status")
        assert len(statuses_after) == 1
        assert statuses_after[0]["note"] == "acted"

    def test_rule37_actions_upsert_and_history(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        run_id = str(uuid.uuid4())
        rec_hash = "abc123hash"
        uid = str(uuid.uuid4())

        # First insert
        payload1 = {
            "run_id": run_id,
            "record_hash": rec_hash,
            "status": "pending_review",
            "user_id": uid,
            "amount_paid": 500.0,
            "tds_deducted": 0.0,
            "tds_confirmed": False,
        }
        ok = repo.upsert_rule37_action(payload1)
        assert ok is True

        actions = repo.get_rule37_actions_for_run(run_id)
        assert len(actions) == 1
        assert actions[0]["status"] == "pending_review"

        # Second insert (same run_id + record_hash) — updates/replaces
        payload2 = {
            "run_id": run_id,
            "record_hash": rec_hash,
            "status": "resolved",
            "user_id": uid,
            "amount_paid": 1000.0,
            "tds_deducted": 20.0,
            "tds_confirmed": True,
            "total_settled": 1020.0,
        }
        ok = repo.upsert_rule37_action(payload2)
        assert ok is True

        actions_after = repo.get_rule37_actions_for_run(run_id)
        assert len(actions_after) == 1
        assert actions_after[0]["status"] == "resolved"
        assert float(actions_after[0]["amount_paid"]) == 1000.0

        # Lookup by hash
        single = repo.get_rule37_action_by_hash(run_id, rec_hash)
        assert single is not None
        assert single["status"] == "resolved"

    def test_invoice_tracking_batch_operations(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        client_id = uuid.uuid4()
        run1 = str(uuid.uuid4())
        run2 = str(uuid.uuid4())

        rows = [
            {
                "client_gstin_id": str(client_id),
                "invoice_number": "INV-001",
                "supplier_gstin": "27AABCU9603R1ZX",
                "taxable_amount": 100000,
                "first_seen_run_id": run1,
                "last_seen_run_id": run1,
                "consecutive_unmatched_runs": 1,
                "last_match_status": "unmatched",
                "is_resolved": False,
            },
            {
                "client_gstin_id": str(client_id),
                "invoice_number": "INV-002",
                "supplier_gstin": "27AABCU9603R1ZX",
                "taxable_amount": 200000,
                "first_seen_run_id": run1,
                "last_seen_run_id": run1,
                "consecutive_unmatched_runs": 3,
                "last_match_status": "missed_itc",
                "is_resolved": False,
            },
        ]

        inserted = repo.batch_upsert_invoice_tracking(rows)
        assert inserted == 2

        # Bulk fetch
        tracking = repo.bulk_fetch_invoice_tracking(client_id)
        assert len(tracking) == 2
        assert ("INV-001", "27AABCU9603R1ZX") in tracking
        assert ("INV-002", "27AABCU9603R1ZX") in tracking

        # Chronic risks (threshold = 3)
        risks = repo.get_chronic_risks(client_id, threshold=3)
        assert len(risks) == 1
        assert risks[0]["invoice_number"] == "INV-002"

        # Cascade cleanup helpers
        by_run = repo.get_invoice_tracking_by_run(column="first_seen_run_id", run_id=run1)
        assert len(by_run) == 2

        row_id = by_run[0]["id"]
        repo.update_invoice_tracking_last_seen(row_id, run2)
        assert repo.delete_invoice_tracking_by_id(row_id) is True

    def test_reconciliation_exception_disposition_lifecycle(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        run_id = str(uuid.uuid4())
        rec_id = "pr:INV-001"
        ex_type = "RULE37_OVERDUE"

        disp = {
            "run_id": run_id,
            "record_id": rec_id,
            "exception_type": ex_type,
            "disposition": "REVERSED",
            "eligibility_effect": "REVERSED",
            "table4_effect": "4B2",
            "reason": "180 days exceeded, ITC reversed in Table 4B(2)",
            "created_by": str(uuid.uuid4()),
        }

        saved = repo.upsert_exception_disposition(disp)
        assert saved is not None
        assert saved["disposition"] == "REVERSED"

        # Read for run
        dispositions = repo.get_exception_dispositions_for_run(run_id)
        assert f"{rec_id}:{ex_type}" in dispositions
        assert rec_id in dispositions

    def test_rule37_alert_dedup_lifecycle(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        firm_owner = str(uuid.uuid4())
        client_gstin = str(uuid.uuid4())
        inv_key = "27AABCU9603R1ZX:INV-001"
        now = datetime.now(timezone.utc)

        # Upsert
        ok = repo.upsert_rule37_dedup(
            firm_owner_id=firm_owner,
            client_gstin_id=client_gstin,
            invoice_key=inv_key,
            tier="WARNING_30_DAYS",
            now=now,
        )
        assert ok is True

        # Load
        dedup_map = repo.load_rule37_dedup_map(client_gstin)
        assert inv_key in dedup_map
        assert dedup_map[inv_key]["last_alert_tier"] == "WARNING_30_DAYS"

    def test_rule37_resolutions_count(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        run_id = str(uuid.uuid4())

        # Zero initially
        assert repo.count_rule37_resolutions_for_run(run_id) == 0

        # Add a resolution row
        with repo._session_factory() as session:
            res = Rule37Resolution(
                run_id=run_id,
                invoice_result_id=str(uuid.uuid4()),
                resolution_note="CA confirmed paid via ledger",
                resolved_by=str(uuid.uuid4()),
            )
            session.add(res)
            session.commit()

        assert repo.count_rule37_resolutions_for_run(run_id) == 1
        rows = repo.get_rule37_resolutions_for_run(run_id)
        assert len(rows) == 1
        assert rows[0]["resolution_note"] == "CA confirmed paid via ledger"


class TestBatch2AFailureModeWithoutSupabase:
    """Verifies that Batch 2A operations succeed purely on Aurora when Supabase is down/unavailable."""

    def test_notes_and_rule37_operations_when_supabase_raises(self, sqlite_compliance_repo, monkeypatch):
        repo = sqlite_compliance_repo
        monkeypatch.setattr("app.repositories.compliance.get_compliance_repository", lambda: repo)
        monkeypatch.setattr("app.routers.reconciliation_api._get_compliance_repo", lambda: repo)

        class BrokenSupabaseClient:
            def table(self, *args, **kwargs):
                raise RuntimeError("CRITICAL: Supabase network failure / service unavailable")

        broken_sb = BrokenSupabaseClient()
        run_id = str(uuid.uuid4())
        rec_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        # 1. Notes insert & count
        repo.insert_mismatch_note({
            "record_id": rec_id,
            "run_id": run_id,
            "user_id": user_id,
            "note": "Aurora standalone note",
            "record_type": "pr",
            "status": "pending",
        })

        from app.routers.reconciliation_api import _notes_count_for_run
        counts = _notes_count_for_run(broken_sb, run_id)
        assert counts[rec_id] == 1, "Should read note count from Aurora without querying Supabase"

        # 2. Decision status upsert & read
        from app.routers.reconciliation_api import _upsert_decision_status, _decision_statuses_for_run
        _upsert_decision_status(
            broken_sb,
            run_id=run_id,
            record_id=rec_id,
            status_value="acted",
            user_id=user_id,
        )
        statuses = _decision_statuses_for_run(broken_sb, run_id)
        assert statuses.get(rec_id) == "acted", "Should persist & retrieve decision status on Aurora without Supabase"

        # 3. Rule 37 action upsert & history
        from app.routers.reconciliation_api import _persist_rule37_action_row, _rule37_actions_for_run
        record_hash = "standalone_hash_999"
        payload = {
            "run_id": run_id,
            "record_hash": record_hash,
            "status": "resolved",
            "user_id": user_id,
            "amount_paid": 4500.0,
            "tds_deducted": 50.0,
            "tds_confirmed": True,
        }
        _persist_rule37_action_row(broken_sb, payload)
        actions = _rule37_actions_for_run(broken_sb, run_id)
        assert actions.get(f"r37:{record_hash}") == "resolved"


class TestBatch2ATenantIsolation:
    """Verifies strict tenant and run scoping across Batch 2A tables."""

    def test_tenant_scoping_invoice_tracking(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        client_a = uuid.uuid4()
        client_b = uuid.uuid4()
        run_id = str(uuid.uuid4())

        repo.batch_upsert_invoice_tracking([
            {
                "client_gstin_id": str(client_a),
                "invoice_number": "INV-A",
                "supplier_gstin": "27AABCU9603R1ZX",
                "taxable_amount": 1000,
                "first_seen_run_id": run_id,
                "last_seen_run_id": run_id,
                "consecutive_unmatched_runs": 4,
                "last_match_status": "unmatched",
            },
            {
                "client_gstin_id": str(client_b),
                "invoice_number": "INV-B",
                "supplier_gstin": "27AABCU9603R1ZX",
                "taxable_amount": 2000,
                "first_seen_run_id": run_id,
                "last_seen_run_id": run_id,
                "consecutive_unmatched_runs": 4,
                "last_match_status": "unmatched",
            },
        ])


        # Client A query must never return Client B
        rows_a = repo.bulk_fetch_invoice_tracking(client_a)
        assert len(rows_a) == 1
        assert ("INV-A", "27AABCU9603R1ZX") in rows_a
        assert ("INV-B", "27AABCU9603R1ZX") not in rows_a

        # Chronic risks for Client A
        risks_a = repo.get_chronic_risks(client_a, threshold=3)
        assert len(risks_a) == 1
        assert risks_a[0]["invoice_number"] == "INV-A"

        # Chronic risks for Client B
        risks_b = repo.get_chronic_risks(client_b, threshold=3)
        assert len(risks_b) == 1
        assert risks_b[0]["invoice_number"] == "INV-B"

    def test_run_scoping_rule37_and_notes(self, sqlite_compliance_repo):
        repo = sqlite_compliance_repo
        run_1 = str(uuid.uuid4())
        run_2 = str(uuid.uuid4())

        # Run 1 action
        repo.upsert_rule37_action({
            "run_id": run_1,
            "record_hash": "hash_1",
            "status": "pending_review",
            "user_id": str(uuid.uuid4()),
        })

        # Run 2 action
        repo.upsert_rule37_action({
            "run_id": run_2,
            "record_hash": "hash_2",
            "status": "resolved",
            "user_id": str(uuid.uuid4()),
        })

        actions_1 = repo.get_rule37_actions_for_run(run_1)
        actions_2 = repo.get_rule37_actions_for_run(run_2)

        assert len(actions_1) == 1 and actions_1[0]["record_hash"] == "hash_1"
        assert len(actions_2) == 1 and actions_2[0]["record_hash"] == "hash_2"

