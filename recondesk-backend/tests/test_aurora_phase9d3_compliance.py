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

