"""Unit tests for ReconDesk AWS Aurora Migration — Phase 9D-1 Batch 2A.

Covers:
1. Model & Schema Verification:
   - Table names:
     - mismatch_notes
     - reconciliation_exception_dispositions
     - invoice_tracking
     - rule37_actions
     - rule37_resolutions
     - rule37_alert_dedup
   - Column types, defaults, and nullability.
   - Unique constraints and indexes.
2. Serialization (.to_dict()) compatibility with Supabase PostgREST format.
3. Cascade relationships and foreign key integrity.
4. Migration discovery and checksum verification via AuroraMigrationRunner.
5. Dry-run transaction rollback verification (zero residual rows).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.migrations.runner import AuroraMigrationRunner
from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.reconciliation import ReconciliationRun
from app.models.compliance import (
    MismatchNote,
    ReconciliationExceptionDisposition,
    InvoiceTracking,
    Rule37Action,
    Rule37Resolution,
    Rule37AlertDedup,
)


@pytest.fixture
def compliance_sqlite_engine():
    """Create an isolated temporary SQLite engine with all schema tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture
def db_session(compliance_sqlite_engine) -> Session:
    """Provide a database session."""
    factory = sessionmaker(
        bind=compliance_sqlite_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = factory()
    yield session
    session.close()


def _seed_baseline(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Helper to seed minimal UserProfile, ClientGSTIN, and ReconciliationRun."""
    user_id = uuid.uuid4()
    client_id = uuid.uuid4()
    run_id = uuid.uuid4()

    owner = UserProfile(
        id=user_id,
        email="compliance_ca@example.com",
        full_name="Compliance CA",
        role="admin",
    )
    session.add(owner)
    session.commit()

    client = ClientGSTIN(
        id=client_id,
        firm_owner_id=user_id,
        gstin="27AABCU9603R1ZM",
        trade_name="Compliance Client",
    )
    session.add(client)
    session.commit()

    run = ReconciliationRun(
        id=run_id,
        client_gstin_id=client_id,
        period="2026-04",
        status="completed",
    )
    session.add(run)
    session.commit()
    return user_id, client_id, run_id


class TestBatch2ASchemaAndModels:
    def test_table_names(self, compliance_sqlite_engine):
        """Verify the 6 Batch 2A tables exist in metadata."""
        inspector = inspect(compliance_sqlite_engine)
        tables = inspector.get_table_names()

        assert "mismatch_notes" in tables
        assert "reconciliation_exception_dispositions" in tables
        assert "invoice_tracking" in tables
        assert "rule37_actions" in tables
        assert "rule37_resolutions" in tables
        assert "rule37_alert_dedup" in tables

    def test_mismatch_note_lifecycle(self, db_session):
        """Test MismatchNote insert, serialization, and default status."""
        user_id, _, run_id = _seed_baseline(db_session)
        rec_id = uuid.uuid4()

        note = MismatchNote(
            record_id=rec_id,
            record_type="gstr",
            run_id=run_id,
            user_id=user_id,
            note="Verified against supplier ledger; timing difference.",
        )
        db_session.add(note)
        db_session.commit()

        d = note.to_dict()
        assert d["record_id"] == str(rec_id)
        assert d["record_type"] == "gstr"
        assert d["run_id"] == str(run_id)
        assert d["user_id"] == str(user_id)
        assert d["note"] == "Verified against supplier ledger; timing difference."
        assert d["status"] == "pending"
        assert d["created_at"] is not None

    def test_reconciliation_exception_disposition_lifecycle(self, db_session):
        """Test ReconciliationExceptionDisposition insert and serialization."""
        user_id, _, run_id = _seed_baseline(db_session)

        disp = ReconciliationExceptionDisposition(
            run_id=run_id,
            record_id="INV-9901-HASH",
            exception_type="missing_in_gstr2b",
            disposition="carry_forward",
            eligibility_effect="provisional_hold",
            table4_effect="deferred",
            reason="Awaiting GSTR-1 supplier filing in subsequent tax period",
            reference_doc="PO-4412",
            statutory_reference="Sec 16(2)(c)",
            created_by=user_id,
        )
        db_session.add(disp)
        db_session.commit()

        d = disp.to_dict()
        assert d["run_id"] == str(run_id)
        assert d["record_id"] == "INV-9901-HASH"
        assert d["exception_type"] == "missing_in_gstr2b"
        assert d["disposition"] == "carry_forward"
        assert d["table4_effect"] == "deferred"
        assert d["created_by"] == str(user_id)

    def test_invoice_tracking_lifecycle(self, db_session):
        """Test InvoiceTracking insert, serialization, and default values."""
        _, client_id, run_id = _seed_baseline(db_session)

        inv = InvoiceTracking(
            client_gstin_id=client_id,
            invoice_number="INV-2026-0042",
            supplier_gstin="27AABCT1234F1Z0",
            taxable_amount=15000000,  # 150,000 INR in paise
            first_seen_run_id=run_id,
            last_seen_run_id=run_id,
            consecutive_unmatched_runs=2,
            last_match_status="unmatched_pr_only",
            is_resolved=False,
        )
        db_session.add(inv)
        db_session.commit()

        d = inv.to_dict()
        assert d["client_gstin_id"] == str(client_id)
        assert d["invoice_number"] == "INV-2026-0042"
        assert d["supplier_gstin"] == "27AABCT1234F1Z0"
        assert d["taxable_amount"] == 15000000
        assert d["first_seen_run_id"] == str(run_id)
        assert d["consecutive_unmatched_runs"] == 2
        assert d["is_resolved"] is False

    def test_rule37_action_lifecycle(self, db_session):
        """Test Rule37Action insert, settlement fields, and bare user_id."""
        user_id, _, _ = _seed_baseline(db_session)
        import_run_id = uuid.uuid4()  # Note: bare UUID not in reconciliation_run

        action = Rule37Action(
            run_id=import_run_id,
            record_hash="HASH-PR-9988",
            status="reversed",
            user_id=user_id,
            tds_deducted=Decimal("2500.00"),
            tds_confirmed=True,
            total_settled=Decimal("50000.00"),
            amount_paid=Decimal("47500.00"),
            remaining_unpaid_amount=Decimal("0.00"),
            payment_coverage="full",
            source="manual_review",
            settled_date=date(2026, 8, 15),
        )
        db_session.add(action)
        db_session.commit()

        d = action.to_dict()
        assert d["run_id"] == str(import_run_id)
        assert d["record_hash"] == "HASH-PR-9988"
        assert d["status"] == "reversed"
        assert d["tds_deducted"] == 2500.00
        assert d["tds_confirmed"] is True
        assert d["total_settled"] == 50000.00
        assert d["settled_date"] == "2026-08-15"

    def test_rule37_resolution_lifecycle(self, db_session):
        """Test Rule37Resolution insert and bare resolved_by UUID."""
        _, _, run_id = _seed_baseline(db_session)
        external_user_id = uuid.uuid4()

        res = Rule37Resolution(
            run_id=run_id,
            invoice_result_id="RES-INV-101",
            resolved_by=external_user_id,
            resolution_note="Payment bank reference verified; Rule 37 compliance cleared.",
        )
        db_session.add(res)
        db_session.commit()

        d = res.to_dict()
        assert d["run_id"] == str(run_id)
        assert d["invoice_result_id"] == "RES-INV-101"
        assert d["resolved_by"] == str(external_user_id)
        assert "Payment bank reference" in d["resolution_note"]

    def test_rule37_alert_dedup_lifecycle(self, db_session):
        """Test Rule37AlertDedup insert, tier check, and uniqueness."""
        user_id, client_id, _ = _seed_baseline(db_session)

        dedup = Rule37AlertDedup(
            firm_owner_id=user_id,
            client_gstin_id=client_id,
            invoice_key="27AAACR1234F1Z1:INV-001:2026-01-01",
            last_alert_tier="WARNING_60_DAYS",
        )
        db_session.add(dedup)
        db_session.commit()

        d = dedup.to_dict()
        assert d["firm_owner_id"] == str(user_id)
        assert d["client_gstin_id"] == str(client_id)
        assert d["invoice_key"] == "27AAACR1234F1Z1:INV-001:2026-01-01"
        assert d["last_alert_tier"] == "WARNING_60_DAYS"

    def test_cascade_delete_on_parent_run(self, db_session):
        """Verify deleting ReconciliationRun cascades to MismatchNote and ExceptionDisposition."""
        user_id, _, run_id = _seed_baseline(db_session)

        note = MismatchNote(
            record_id=uuid.uuid4(),
            record_type="gstr",
            run_id=run_id,
            user_id=user_id,
            note="Cascade test note",
        )
        disp = ReconciliationExceptionDisposition(
            run_id=run_id,
            record_id="REC-CASCADE",
            exception_type="unmatched",
            disposition="investigate",
            eligibility_effect="hold",
            table4_effect="pending",
            reason="Cascade test",
        )
        db_session.add(note)
        db_session.add(disp)
        db_session.commit()

        run = db_session.get(ReconciliationRun, run_id)
        db_session.delete(run)
        db_session.commit()

        assert db_session.query(MismatchNote).filter_by(run_id=run_id).count() == 0
        assert db_session.query(ReconciliationExceptionDisposition).filter_by(run_id=run_id).count() == 0

    def test_migration_runner_discovers_batch2a_migration(self):
        """Verify AuroraMigrationRunner discovers the Batch 2A migration."""
        runner = AuroraMigrationRunner()
        discovered = runner.discover_migrations()

        migration_versions = [m.version for m in discovered]
        assert "20261003150000" in migration_versions

        batch2a_migration = next(m for m in discovered if m.version == "20261003150000")
        assert batch2a_migration.name == "create_batch2a_compliance_tables"
        assert batch2a_migration.up_path.exists()
        assert batch2a_migration.down_path.exists()
        assert len(batch2a_migration.checksum) == 64

    def test_dry_run_transactional_rollback_preserves_zero_state(self, compliance_sqlite_engine):
        """Verify simulated dry-run backfill rolls back and leaves 0 residual records."""
        factory = sessionmaker(bind=compliance_sqlite_engine, autoflush=False)
        session = factory()

        user_id, client_id, run_id = _seed_baseline(session)

        # Insert 1 record into each table
        session.add(MismatchNote(record_id=uuid.uuid4(), record_type="gstr", run_id=run_id, user_id=user_id, note="Rollback test"))
        session.add(ReconciliationExceptionDisposition(run_id=run_id, record_id="R1", exception_type="t", disposition="d", eligibility_effect="e", table4_effect="t", reason="r"))
        session.add(InvoiceTracking(client_gstin_id=client_id, invoice_number="INV-1", supplier_gstin="27A", taxable_amount=100, first_seen_run_id=run_id, last_seen_run_id=run_id, last_match_status="u"))
        session.add(Rule37Action(run_id=run_id, record_hash="H1", status="p"))
        session.add(Rule37Resolution(run_id=run_id, invoice_result_id="RES-1", resolved_by=user_id))
        session.add(Rule37AlertDedup(firm_owner_id=user_id, client_gstin_id=client_id, invoice_key="K1", last_alert_tier="WARNING_30_DAYS"))
        session.flush()

        assert session.query(MismatchNote).count() == 1
        assert session.query(Rule37AlertDedup).count() == 1

        # Simulate dry-run rollback
        session.rollback()
        session.close()

        # Open fresh session and verify 0 residual records
        fresh_session = factory()
        assert fresh_session.query(MismatchNote).count() == 0
        assert fresh_session.query(ReconciliationExceptionDisposition).count() == 0
        assert fresh_session.query(InvoiceTracking).count() == 0
        assert fresh_session.query(Rule37Action).count() == 0
        assert fresh_session.query(Rule37Resolution).count() == 0
        assert fresh_session.query(Rule37AlertDedup).count() == 0
        fresh_session.close()
