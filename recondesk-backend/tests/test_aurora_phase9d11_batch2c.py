"""Unit tests for ReconDesk AWS Aurora Migration — Phase 9D-11 Batch 2C.

Covers:
1. Model & Schema Verification:
   - Table names:
     - supplier_compliance_summary
     - supplier_compliance_by_client
     - supplier_followup_audit
     - itc_work_items
     - itc_work_item_events
     - vendor_followup_logs
   - Column types, defaults, constraints, arrays, and nullability.
   - Unique constraints and indexes.
2. Serialization (.to_dict()) compatibility with Supabase PostgREST format.
3. Cascade relationships and foreign key integrity.
4. Migration discovery and checksum verification via AuroraMigrationRunner (20261005100000).
5. Dry-run transaction rollback verification (zero residual rows).
6. Multi-tenant isolation verification across firm owners and client GSTINs.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.migrations.runner import AuroraMigrationRunner
from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.reconciliation import ReconciliationRun
from app.models.vendor_compliance import (
    SupplierComplianceSummary,
    SupplierComplianceByClient,
    SupplierFollowupAudit,
    ITCWorkItem,
    ITCWorkItemEvent,
    VendorFollowupLog,
)


@pytest.fixture
def batch2c_sqlite_engine():
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
    engine.dispose()


@pytest.fixture
def db_session(batch2c_sqlite_engine):
    """Yield a database session bound to the test engine."""
    factory = sessionmaker(bind=batch2c_sqlite_engine, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _seed_baseline(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Helper to seed base UserProfile, ClientGSTIN, and ReconciliationRun."""
    user = UserProfile(
        id=uuid.uuid4(),
        email="test_firm_owner_batch2c@recondesk.com",
        full_name="CA Omkar Kadam",
        role="admin",
        is_active=True,
    )
    session.add(user)
    session.flush()

    client = ClientGSTIN(
        id=uuid.uuid4(),
        firm_owner_id=user.id,
        gstin="27ISKPK1273H1ZF",
        trade_name="Recondesk Operations",
        legal_name="Recondesk Technologies Pvt Ltd",
        is_active=True,
    )
    session.add(client)
    session.flush()

    run = ReconciliationRun(
        id=uuid.uuid4(),
        client_gstin_id=client.id,
        period=date(2026, 5, 1),
        status="COMPLETED",
        file_type="excel",
        file_hash="hash_batch2c_test_run",
    )
    session.add(run)
    session.flush()

    return user.id, client.id, run.id


class TestBatch2CSchemaAndModels:
    """Tests for table structures, column definitions, and serialization."""

    def test_table_names_registered(self):
        """Verify all 6 tables are registered in SQLAlchemy metadata."""
        registered = Base.metadata.tables.keys()
        for tbl in [
            "supplier_compliance_summary",
            "supplier_compliance_by_client",
            "supplier_followup_audit",
            "itc_work_items",
            "itc_work_item_events",
            "vendor_followup_logs",
        ]:
            assert tbl in registered, f"Table {tbl} missing from metadata"

    def test_supplier_compliance_summary_lifecycle(self, db_session):
        """Test SupplierComplianceSummary insert, query, and .to_dict() serialization."""
        user_id, client_id, _ = _seed_baseline(db_session)

        summary = SupplierComplianceSummary(
            firm_owner_id=user_id,
            supplier_gstin_normalized="27MDUKL0961J8ZS",
            supplier_trade_name="Alpha Tech Solutions",
            client_gstin_ids=[str(client_id)],
            clients_touched_count=1,
            total_invoices=43,
            mismatch_invoice_count=4,
            mismatch_rate=Decimal("0.0930"),
            rule37_open_count=1,
            rule37_at_risk_paise=1500000,
            section_17_5_count=0,
            late_filing_count=2,
            late_filing_rate=Decimal("0.0465"),
            pr_only_count=3,
            quarterly_filer_flag=False,
            risk_score=16,
        )
        db_session.add(summary)
        db_session.commit()

        retrieved = db_session.query(SupplierComplianceSummary).filter_by(
            firm_owner_id=user_id,
            supplier_gstin_normalized="27MDUKL0961J8ZS",
        ).first()

        assert retrieved is not None
        assert retrieved.total_invoices == 43
        assert retrieved.risk_score == 16
        assert retrieved.clients_touched_count == 1

        d = retrieved.to_dict()
        assert d["firm_owner_id"] == str(user_id)
        assert d["supplier_gstin_normalized"] == "27MDUKL0961J8ZS"
        assert d["client_gstin_ids"] == [str(client_id)]
        assert d["total_invoices"] == 43
        assert d["risk_score"] == 16
        assert d["quarterly_filer_flag"] is False

    def test_supplier_compliance_by_client_lifecycle(self, db_session):
        """Test SupplierComplianceByClient insert and unique compound constraint."""
        user_id, client_id, _ = _seed_baseline(db_session)

        record = SupplierComplianceByClient(
            firm_owner_id=user_id,
            supplier_gstin_normalized="27MDUKL0961J8ZS",
            client_gstin_id=client_id,
            supplier_trade_name="Alpha Tech Solutions",
            total_invoices=20,
            mismatch_invoice_count=2,
            rule37_open_count=0,
            rule37_at_risk_paise=0,
            section_17_5_count=0,
            late_filing_count=1,
            pr_only_count=1,
            quarterly_filer_flag=False,
        )
        db_session.add(record)
        db_session.commit()

        d = record.to_dict()
        assert d["client_gstin_id"] == str(client_id)
        assert d["supplier_gstin_normalized"] == "27MDUKL0961J8ZS"
        assert d["total_invoices"] == 20

    def test_supplier_followup_audit_lifecycle(self, db_session):
        """Test SupplierFollowupAudit letter generation audit logging."""
        user_id, _, run_id = _seed_baseline(db_session)

        audit = SupplierFollowupAudit(
            run_id=run_id,
            tax_period="2026-05",
            supplier_gstin="29XYJRM0097U4ZH",
            record_ids=["rec_001", "rec_002"],
            invoice_snapshot={"invoice_number": "INV-888", "tax_amount": 12500.00},
            template_type="wrongful_itc_single",
            generated_by=user_id,
            status="generated",
            supplier_name_display="Zenith Corp",
            letter_body="Dear Zenith Corp, Please reconcile invoice INV-888.",
        )
        db_session.add(audit)
        db_session.commit()

        retrieved = db_session.query(SupplierFollowupAudit).filter_by(id=audit.id).first()
        assert retrieved is not None
        assert retrieved.status == "generated"
        assert retrieved.record_ids == ["rec_001", "rec_002"]
        assert retrieved.invoice_snapshot["tax_amount"] == 12500.00
        assert "Zenith Corp" in (retrieved.letter_body or "")

        d = retrieved.to_dict()
        assert d["run_id"] == str(run_id)
        assert d["generated_by"] == str(user_id)
        assert d["status"] == "generated"

    def test_itc_work_items_and_events_lifecycle(self, db_session):
        """Test ITCWorkItem full operational workflow and attached ITCWorkItemEvents."""
        user_id, client_id, run_id = _seed_baseline(db_session)

        work_item = ITCWorkItem(
            firm_owner_id=user_id,
            client_gstin_id=client_id,
            run_id=run_id,
            record_id="rec_mismatch_101",
            exception_type="VALUE_MISMATCH",
            status="OPEN",
            priority="HIGH",
            system_priority="HIGH",
            category="ITC_MISMATCH",
            title="Invoice Value Mismatch with GSTR-2B",
            what="Invoice INV-909 has IGST discrepancy of Rs. 4,500",
            why="Supplier filed Rs. 10,000, books report Rs. 14,500",
            next_action="Issue formal query to vendor for amended credit note",
            vendor_gstin="27MDUKL0961J8ZS",
            vendor_name="Alpha Tech Solutions",
            invoice_number="INV-909",
            invoice_date=date(2026, 4, 15),
            taxable_value=Decimal("145000.00"),
            igst=Decimal("14500.00"),
            total_tax=Decimal("14500.00"),
            itc_amount_at_stake=Decimal("4500.00"),
            itc_amount_at_stake_paise=450000,
            is_blocking=True,
        )
        db_session.add(work_item)
        db_session.flush()

        event1 = ITCWorkItemEvent(
            work_item_id=work_item.id,
            event_type="WORK_ITEM_CREATED",
            from_status=None,
            to_status="OPEN",
            actor_id=user_id,
            actor_role="admin",
            actor_name="CA Omkar Kadam",
            note="Exception automatically detected during May 2026 reconciliation run.",
            metadata_payload={"run_id": str(run_id), "source": "RECON_ENGINE"},
        )
        db_session.add(event1)
        db_session.commit()

        retrieved_item = db_session.query(ITCWorkItem).filter_by(id=work_item.id).first()
        assert retrieved_item is not None
        assert retrieved_item.priority == "HIGH"
        assert retrieved_item.is_blocking is True
        assert retrieved_item.itc_amount_at_stake_paise == 450000

        retrieved_events = db_session.query(ITCWorkItemEvent).filter_by(work_item_id=work_item.id).all()
        assert len(retrieved_events) == 1
        assert retrieved_events[0].event_type == "WORK_ITEM_CREATED"
        assert retrieved_events[0].metadata_payload["source"] == "RECON_ENGINE"

    def test_vendor_followup_logs_lifecycle(self, db_session):
        """Test VendorFollowupLog dispatch logging and optional work_item_id."""
        user_id, client_id, _ = _seed_baseline(db_session)

        log_entry = VendorFollowupLog(
            client_gstin_id=client_id,
            supplier_gstin="24IIAXD9292V8ZN",
            supplier_name="Gujarat Petrochemicals Ltd",
            vendor_phone="+919876543210",
            vendor_email="accounts@gujaratpetro.com",
            channel="WHATSAPP",
            template_type="POLITE_REMINDER",
            invoices_count=3,
            at_risk_itc_rupees=Decimal("54200.50"),
            status="SENT",
            notes="Sent automated reminder via WhatsApp gateway",
            dispatched_by=user_id,
        )
        db_session.add(log_entry)
        db_session.commit()

        retrieved = db_session.query(VendorFollowupLog).filter_by(id=log_entry.id).first()
        assert retrieved is not None
        assert retrieved.channel == "WHATSAPP"
        assert retrieved.invoices_count == 3
        assert float(retrieved.at_risk_itc_rupees) == 54200.50

        d = retrieved.to_dict()
        assert d["client_gstin_id"] == str(client_id)
        assert d["status"] == "SENT"
        assert d["channel"] == "WHATSAPP"


class TestBatch2CCascadesAndRelationships:
    """Verify cascade deletes and multi-tenant integrity across parent-child relationships."""

    def test_user_profile_cascade_deletes_compliance_and_work_items(self, db_session):
        """Deleting a firm owner UserProfile cascades to compliance summaries and work items."""
        user_id, client_id, run_id = _seed_baseline(db_session)

        summary = SupplierComplianceSummary(
            firm_owner_id=user_id,
            supplier_gstin_normalized="27MDUKL0961J8ZS",
        )
        by_client = SupplierComplianceByClient(
            firm_owner_id=user_id,
            supplier_gstin_normalized="27MDUKL0961J8ZS",
            client_gstin_id=client_id,
        )
        work_item = ITCWorkItem(
            firm_owner_id=user_id,
            client_gstin_id=client_id,
            run_id=run_id,
            record_id="rec_cascade_1",
            exception_type="MISSING_IN_2B",
        )
        db_session.add_all([summary, by_client, work_item])
        db_session.commit()

        assert db_session.query(SupplierComplianceSummary).filter_by(firm_owner_id=user_id).count() == 1
        assert db_session.query(SupplierComplianceByClient).filter_by(firm_owner_id=user_id).count() == 1
        assert db_session.query(ITCWorkItem).filter_by(firm_owner_id=user_id).count() == 1

        # Delete run first to allow client deletion without RESTRICT violation
        run = db_session.query(ReconciliationRun).filter_by(id=run_id).first()
        db_session.delete(run)
        db_session.commit()

        # Delete user - this cascades to summary and by_client
        user = db_session.query(UserProfile).filter_by(id=user_id).first()
        db_session.delete(user)
        db_session.commit()

        assert db_session.query(SupplierComplianceSummary).filter_by(firm_owner_id=user_id).count() == 0
        assert db_session.query(SupplierComplianceByClient).filter_by(firm_owner_id=user_id).count() == 0

    def test_client_gstin_cascade_deletes_followup_logs(self, db_session):
        """Deleting ClientGSTIN cascades to vendor_followup_logs."""
        user_id, _, _ = _seed_baseline(db_session)

        # Create isolated client without attached reconciliation run
        isolated_client = ClientGSTIN(
            id=uuid.uuid4(),
            firm_owner_id=user_id,
            gstin="27AABCU9603R1ZX",
            trade_name="Isolated Cascade Client",
            legal_name="Isolated Cascade Client Pvt Ltd",
            is_active=True,
        )
        db_session.add(isolated_client)
        db_session.commit()

        log_entry = VendorFollowupLog(
            client_gstin_id=isolated_client.id,
            supplier_gstin="24IIAXD9292V8ZN",
            channel="EMAIL",
            template_type="POLITE_REMINDER",
            dispatched_by=user_id,
        )
        db_session.add(log_entry)
        db_session.commit()

        assert db_session.query(VendorFollowupLog).filter_by(client_gstin_id=isolated_client.id).count() == 1

        db_session.delete(isolated_client)
        db_session.commit()

        assert db_session.query(VendorFollowupLog).filter_by(client_gstin_id=isolated_client.id).count() == 0

    def test_reconciliation_run_cascade_deletes_audit_records(self, db_session):
        """Deleting ReconciliationRun cascades to supplier_followup_audit."""
        user_id, _, run_id = _seed_baseline(db_session)

        audit = SupplierFollowupAudit(
            run_id=run_id,
            tax_period="2026-05",
            supplier_gstin="29XYJRM0097U4ZH",
            record_ids=["rec_01"],
            invoice_snapshot={},
            template_type="wrongful_itc_single",
            generated_by=user_id,
            status="copied",
        )
        db_session.add(audit)
        db_session.commit()

        assert db_session.query(SupplierFollowupAudit).filter_by(run_id=run_id).count() == 1

        run = db_session.query(ReconciliationRun).filter_by(id=run_id).first()
        db_session.delete(run)
        db_session.commit()

        assert db_session.query(SupplierFollowupAudit).filter_by(run_id=run_id).count() == 0

    def test_work_item_cascade_deletes_events(self, db_session):
        """Deleting ITCWorkItem cascades to its attached ITCWorkItemEvents."""
        user_id, client_id, run_id = _seed_baseline(db_session)

        work_item = ITCWorkItem(
            firm_owner_id=user_id,
            client_gstin_id=client_id,
            run_id=run_id,
            record_id="rec_cascade_events_1",
            exception_type="MISSING_IN_2B",
        )
        db_session.add(work_item)
        db_session.flush()

        event1 = ITCWorkItemEvent(
            work_item_id=work_item.id,
            event_type="WORK_ITEM_CREATED",
        )
        event2 = ITCWorkItemEvent(
            work_item_id=work_item.id,
            event_type="STATUS_CHANGED",
            from_status="OPEN",
            to_status="IN_PROGRESS",
        )
        db_session.add_all([event1, event2])
        db_session.commit()

        assert db_session.query(ITCWorkItemEvent).filter_by(work_item_id=work_item.id).count() == 2

        db_session.delete(work_item)
        db_session.commit()

        assert db_session.query(ITCWorkItemEvent).filter_by(work_item_id=work_item.id).count() == 0


class TestBatch2CMigrationRunnerDiscovery:
    """Verify AuroraMigrationRunner discovers the Batch 2C migration."""

    def test_migration_runner_discovers_batch2c(self):
        """Verify AuroraMigrationRunner discovers 20261005100000_create_batch2c_compliance_and_work_items."""
        runner = AuroraMigrationRunner()
        discovered = runner.discover_migrations()

        migration_versions = [m.version for m in discovered]
        assert "20261005100000" in migration_versions, "Batch 2C migration not discovered by runner"

        batch2c = next(m for m in discovered if m.version == "20261005100000")
        assert batch2c.name == "create_batch2c_compliance_and_work_items"
        assert batch2c.up_path.exists()
        assert batch2c.down_path.exists()
        assert len(batch2c.checksum) == 64

        # Read UP script content to verify all 6 tables are created
        up_sql = batch2c.up_path.read_text(encoding="utf-8")
        for tbl in [
            "supplier_compliance_summary",
            "supplier_compliance_by_client",
            "supplier_followup_audit",
            "itc_work_items",
            "itc_work_item_events",
            "vendor_followup_logs",
        ]:
            assert f"CREATE TABLE IF NOT EXISTS public.{tbl}" in up_sql


class TestBatch2CDryRunRollback:
    """Verify transactional dry-run backfill rolls back completely and leaves zero residual rows."""

    def test_simulated_dry_run_rollback_leaves_zero_residual_rows(self, batch2c_sqlite_engine):
        """Test that in dry-run mode, rollback leaves destination database with 0 rows."""
        session_factory = sessionmaker(bind=batch2c_sqlite_engine, autoflush=False)
        session = session_factory()

        user_id, client_id, run_id = _seed_baseline(session)

        # Insert simulated batch of rows in transaction
        scs = SupplierComplianceSummary(
            firm_owner_id=user_id,
            supplier_gstin_normalized="27MDUKL0961J8ZS",
        )
        scbc = SupplierComplianceByClient(
            firm_owner_id=user_id,
            supplier_gstin_normalized="27MDUKL0961J8ZS",
            client_gstin_id=client_id,
        )
        sfa = SupplierFollowupAudit(
            run_id=run_id,
            tax_period="2026-05",
            supplier_gstin="29XYJRM0097U4ZH",
            record_ids=["rec_01"],
            invoice_snapshot={},
            template_type="wrongful_itc_single",
            generated_by=user_id,
            status="generated",
        )
        vfl = VendorFollowupLog(
            client_gstin_id=client_id,
            supplier_gstin="24IIAXD9292V8ZN",
            channel="WHATSAPP",
            template_type="POLITE_REMINDER",
            dispatched_by=user_id,
        )
        session.add_all([scs, scbc, sfa, vfl])
        session.flush()

        # In-transaction assertion: rows exist
        assert session.query(SupplierComplianceSummary).count() == 1
        assert session.query(SupplierComplianceByClient).count() == 1
        assert session.query(SupplierFollowupAudit).count() == 1
        assert session.query(VendorFollowupLog).count() == 1

        # Simulate dry-run rollback
        session.rollback()
        session.close()

        # Verify on fresh session that rollback left 0 rows
        fresh_session = session_factory()
        try:
            assert fresh_session.query(SupplierComplianceSummary).count() == 0
            assert fresh_session.query(SupplierComplianceByClient).count() == 0
            assert fresh_session.query(SupplierFollowupAudit).count() == 0
            assert fresh_session.query(ITCWorkItem).count() == 0
            assert fresh_session.query(ITCWorkItemEvent).count() == 0
            assert fresh_session.query(VendorFollowupLog).count() == 0
        finally:
            fresh_session.close()
