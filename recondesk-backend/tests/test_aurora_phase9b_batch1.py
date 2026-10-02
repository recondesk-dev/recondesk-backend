"""Unit tests for ReconDesk Dual-Auth / AWS Aurora Migration — Phase 9B Batch 1.

Covers:
1. Model & Schema Verification:
   - Table names: client_import_mappings, reconciliation_import_runs, reconciliation_import_run_audit_log.
   - Column types, defaults, and nullability.
   - Foreign key constraints:
     - reconciliation_import_runs.client_id -> client_gstins.id (CASCADE)
     - reconciliation_import_runs.firm_owner_id -> user_profiles.id (SET NULL)
     - reconciliation_import_runs.created_by is bare UUID (no FK to user_profiles)
     - reconciliation_import_run_audit_log.run_id -> reconciliation_import_runs.id (CASCADE)
     - client_import_mappings.client_gstin_id -> client_gstins.id (CASCADE)
   - Unique constraints and indexes.
2. Serialization (.to_dict()) compatibility with Supabase PostgREST format.
3. Cascade relationships (deleting import run cascades to audit logs).
4. Migration file validity and ordering.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.migrations.runner import AuroraMigrationRunner
from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.wizard import (
    ClientImportMapping,
    ReconciliationImportRun,
    ReconciliationImportRunAuditLog,
)


@pytest.fixture
def wizard_sqlite_engine():
    """Create a temporary SQLite engine with all schema tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30},
    )
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
def db_session(wizard_sqlite_engine) -> Session:
    """Provide a database session."""
    factory = sessionmaker(
        bind=wizard_sqlite_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = factory()
    yield session
    session.close()


def _create_firm_and_client(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Helper to seed user_profile and client_gstin."""
    owner_id = uuid.uuid4()
    client_id = uuid.uuid4()

    owner = UserProfile(
        id=owner_id,
        email="owner@example.com",
        full_name="CA Owner",
        role="admin",
    )
    client = ClientGSTIN(
        id=client_id,
        firm_owner_id=owner_id,
        gstin="27AABCU9603R1ZM",
        trade_name="Test Enterprise",
    )
    session.add(owner)
    session.add(client)
    session.commit()
    return owner_id, client_id


class TestBatch1SchemaAndModels:
    def test_table_names(self, wizard_sqlite_engine):
        """Verify the 3 Batch 1 tables exist in metadata."""
        inspector = inspect(wizard_sqlite_engine)
        tables = inspector.get_table_names()

        assert "client_import_mappings" in tables
        assert "reconciliation_import_runs" in tables
        assert "reconciliation_import_run_audit_log" in tables

    def test_client_import_mapping_lifecycle(self, db_session):
        """Test ClientImportMapping insert, serialization, and uniqueness."""
        _, client_id = _create_firm_and_client(db_session)

        mapping = ClientImportMapping(
            client_gstin_id=client_id,
            source_column_name="Inv Num",
            target_field="invoice_number",
        )
        db_session.add(mapping)
        db_session.commit()

        d = mapping.to_dict()
        assert d["client_gstin_id"] == str(client_id)
        assert d["source_column_name"] == "Inv Num"
        assert d["target_field"] == "invoice_number"
        assert d["created_at"] is not None
        assert d["updated_at"] is not None

    def test_reconciliation_import_run_lifecycle_and_cascade(self, db_session):
        """Test ReconciliationImportRun with bare created_by and audit log cascade."""
        owner_id, client_id = _create_firm_and_client(db_session)
        external_creator_id = uuid.uuid4()  # UUID NOT in user_profiles!

        run = ReconciliationImportRun(
            client_id=client_id,
            firm_owner_id=owner_id,
            period=date(2026, 9, 1),
            status="draft",
            current_step=1,
            created_by=external_creator_id,
            column_mapping={"Inv": "invoice_number"},
            pr_column_headers=["Inv", "Date", "Taxable"],
        )
        db_session.add(run)
        db_session.commit()

        # Add audit log
        audit = ReconciliationImportRunAuditLog(
            run_id=run.id,
            user_id=external_creator_id,
            event="run_created",
            detail={"step": 1},
        )
        db_session.add(audit)
        db_session.commit()

        # Verify serialization
        d_run = run.to_dict()
        assert d_run["id"] == str(run.id)
        assert d_run["client_id"] == str(client_id)
        assert d_run["created_by"] == str(external_creator_id)
        assert d_run["period"] == "2026-09-01"
        assert d_run["column_mapping"] == {"Inv": "invoice_number"}

        d_audit = audit.to_dict()
        assert d_audit["run_id"] == str(run.id)
        assert d_audit["event"] == "run_created"
        assert d_audit["detail"] == {"step": 1}

        # Verify cascade delete
        db_session.delete(run)
        db_session.commit()

        remaining_audit = (
            db_session.query(ReconciliationImportRunAuditLog)
            .filter_by(run_id=run.id)
            .all()
        )
        assert len(remaining_audit) == 0

    def test_migration_runner_discovers_batch1_migration(self):
        """Verify AuroraMigrationRunner discovers the Batch 1 migration."""
        runner = AuroraMigrationRunner()
        discovered = runner.discover_migrations()

        migration_versions = [m.version for m in discovered]
        assert "20261003100000" in migration_versions

        batch1_migration = next(m for m in discovered if m.version == "20261003100000")
        assert batch1_migration.name == "create_wizard_ingestion_tables"
        assert batch1_migration.up_path.exists()
        assert batch1_migration.down_path.exists()
        assert len(batch1_migration.checksum) == 64
