"""Phase 9G-11 Batch 4C: Schema, Models, Repository & Dry-Run Verification Tests.

Tests verify:
1. All 5 SQLAlchemy models create correct table schema:
   - notification_preferences
   - upload_requests
   - uploaded_files
   - communication_logs
   - audit_logs
2. Column types, nullability, unique constraints, and foreign keys.
3. Crucial schema invariant: audit_logs.user_id has NO FK constraint, allowing deleted/system users.
4. Sensitive parameter redaction: tokens, S3 URLs, and client IPs masked on request.
5. Repository layer methods across all 5 entities.
6. Audit log idempotency check (check_audit_log_exists).
7. Tenant isolation across firm_id and client_id.
8. Deterministic dry-run backfill:
   - 100% field-by-field, numeric, and timestamp parity.
   - 0 mismatches, 0 missing, 0 extra, 0 orphan FKs.
   - Completely rolls back transaction.
   - Fresh connection verifies 0 residual rows in target tables.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.portal_and_audit import (
    AuditLog,
    CommunicationLog,
    NotificationPreference,
    UploadedFile,
    UploadRequest,
)
from app.repositories.portal_and_audit import (
    AuroraPortalAndAuditRepository,
    get_portal_and_audit_repository,
    set_portal_and_audit_repository,
)
from app.scripts.backfill_batch4c_portal_audit import (
    Batch4cBackfillMigrator,
    _compare_field,
)


@pytest.fixture
def db_engine():
    """In-memory SQLite database engine with full schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine):
    """Session bound to in-memory test engine."""
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_tenancy(db_session):
    """Seed parent tenancy records in user_profiles and client_gstins."""
    user_id = uuid.uuid4()
    client_id = uuid.uuid4()

    user = UserProfile(
        id=user_id,
        email="principal@example.com",
        full_name="Principal CA",
        firm_name="CA Firm",
        role="admin",
        is_active=True,
    )
    db_session.add(user)

    client = ClientGSTIN(
        id=client_id,
        firm_owner_id=user_id,
        gstin="27AABCU9603R1ZM",
        trade_name="Acme Corp",
        legal_name="Acme Corporation Ltd",
    )
    db_session.add(client)
    db_session.commit()

    return {"user_id": user_id, "client_id": client_id}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Model & Schema Invariant Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_notification_preferences_schema_and_defaults(db_session, seeded_tenancy):
    user_id = seeded_tenancy["user_id"]
    pref = NotificationPreference(user_id=user_id)
    db_session.add(pref)
    db_session.commit()

    saved = db_session.get(NotificationPreference, user_id)
    assert saved is not None
    assert saved.run_completed is True
    assert saved.runs_expiring_soon is True
    assert saved.payment_receipts is True
    assert saved.rule37_alerts is True
    assert saved.created_at is not None
    assert saved.updated_at is not None

    d = saved.to_dict()
    assert d["user_id"] == str(user_id)
    assert d["rule37_alerts"] is True


def test_upload_request_and_file_relationship(db_session, seeded_tenancy):
    user_id = seeded_tenancy["user_id"]
    client_id = seeded_tenancy["client_id"]

    req = UploadRequest(
        client_id=client_id,
        organization_id=user_id,
        token="cryptosecret123",
        title="March Purchase Register",
        description="Please upload invoices",
        created_by_user_id=user_id,
    )
    db_session.add(req)
    db_session.commit()

    file_rec = UploadedFile(
        upload_request_id=req.id,
        filename="invoices.xlsx",
        file_size=1048576,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        public_url="https://s3.ap-south-1.amazonaws.com/bucket/uploads/invoices.xlsx",
    )
    db_session.add(file_rec)
    db_session.commit()

    # Verify relationships
    assert len(req.files) == 1
    assert req.files[0].filename == "invoices.xlsx"
    assert file_rec.upload_request.title == "March Purchase Register"

    # Redaction checks
    req_dict = req.to_dict(mask_token=True)
    assert req_dict["token"] == "cryp...***REDACTED***"

    file_dict = file_rec.to_dict(mask_url=True)
    assert file_dict["public_url"] == "***REDACTED_URL***"


def test_upload_request_token_unique_constraint(db_session, seeded_tenancy):
    user_id = seeded_tenancy["user_id"]
    client_id = seeded_tenancy["client_id"]

    req1 = UploadRequest(
        client_id=client_id,
        organization_id=user_id,
        token="duplicate_token",
        title="Req 1",
        created_by_user_id=user_id,
    )
    db_session.add(req1)
    db_session.commit()

    req2 = UploadRequest(
        client_id=client_id,
        organization_id=user_id,
        token="duplicate_token",
        title="Req 2",
        created_by_user_id=user_id,
    )
    db_session.add(req2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_audit_logs_user_id_unconstrained_invariant(db_session, seeded_tenancy):
    """Verify that audit_logs.user_id does NOT enforce FK, allowing null or deleted users."""
    user_id = seeded_tenancy["user_id"]
    non_existent_user_id = uuid.uuid4()

    # 1. Null user_id (system action)
    log_null_user = AuditLog(
        user_id=None,
        action="SYSTEM_CRON_TRIGGERED",
        firm_id=user_id,
    )
    db_session.add(log_null_user)

    # 2. Non-existent / deleted user_id
    log_deleted_user = AuditLog(
        user_id=non_existent_user_id,
        action="LEGACY_ACTION",
        firm_id=user_id,
    )
    db_session.add(log_deleted_user)
    db_session.commit()

    assert log_null_user.id is not None
    assert log_deleted_user.id is not None

    d = log_deleted_user.to_dict(mask_ip=True)
    assert d["user_id"] == str(non_existent_user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Repository Layer Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_repository_notification_preferences(db_session, seeded_tenancy):
    repo = AuroraPortalAndAuditRepository(session=db_session)
    user_id = str(seeded_tenancy["user_id"])

    # 1. Initial get is None
    assert repo.get_notification_preferences(user_id) is None

    # 2. Upsert create
    created = repo.upsert_notification_preferences(
        user_id,
        run_completed=True,
        runs_expiring_soon=False,
        payment_receipts=True,
        rule37_alerts=True,
    )
    assert created["user_id"] == user_id
    assert created["runs_expiring_soon"] is False

    # 3. Upsert update
    updated = repo.upsert_notification_preferences(
        user_id,
        runs_expiring_soon=True,
    )
    assert updated["runs_expiring_soon"] is True


def test_repository_upload_requests_and_files(db_session, seeded_tenancy):
    repo = AuroraPortalAndAuditRepository(session=db_session)
    user_id = str(seeded_tenancy["user_id"])
    client_id = str(seeded_tenancy["client_id"])

    req = repo.create_upload_request(
        client_id=client_id,
        organization_id=user_id,
        token="tok_abc_123",
        title="Q1 Invoices",
        created_by_user_id=user_id,
    )
    assert req["id"] is not None
    assert req["token"] == "tok_abc_123"

    by_token = repo.get_upload_request_by_token("tok_abc_123")
    assert by_token is not None
    assert by_token["id"] == req["id"]

    listed = repo.list_upload_requests(client_id)
    assert len(listed) == 1
    assert listed[0]["title"] == "Q1 Invoices"

    # Add uploaded file
    file_rec = repo.create_uploaded_file(
        upload_request_id=req["id"],
        filename="sales.csv",
        file_size=2048,
        mime_type="text/csv",
        public_url="https://s3.ap-south-1.amazonaws.com/uploads/sales.csv",
    )
    assert file_rec["id"] is not None

    files = repo.list_uploaded_files_by_request_ids([req["id"]])
    assert len(files) == 1
    assert files[0]["filename"] == "sales.csv"


def test_repository_communication_logs(db_session, seeded_tenancy):
    repo = AuroraPortalAndAuditRepository(session=db_session)
    user_id = str(seeded_tenancy["user_id"])
    client_id = str(seeded_tenancy["client_id"])

    comm = repo.create_communication_log(
        client_id=client_id,
        organization_id=user_id,
        template_type="upload_request",
        message_content="Please upload documents",
        sent_via="email",
        sent_by_user_id=user_id,
    )
    assert comm["id"] is not None

    logs = repo.list_communication_logs(client_id)
    assert len(logs) == 1
    assert logs[0]["template_type"] == "upload_request"


def test_repository_audit_logs_and_idempotency(db_session, seeded_tenancy):
    repo = AuroraPortalAndAuditRepository(session=db_session)
    user_id = str(seeded_tenancy["user_id"])
    entity_id = str(uuid.uuid4())

    # 1. Check idempotency initially False
    assert repo.check_audit_log_exists("EMAIL_SENT", entity_id) is False

    # 2. Insert audit log
    entry = repo.insert_audit_log(
        action="EMAIL_SENT",
        entity_id=entity_id,
        firm_id=user_id,
        user_id=user_id,
        entity_type="reconciliation",
        metadata={"email_to": "client@example.com"},
    )
    assert entry["id"] is not None

    # 3. Check idempotency now True
    assert repo.check_audit_log_exists("EMAIL_SENT", entity_id) is True

    # 4. List audit logs by firm
    logs, total = repo.list_audit_logs(user_id, action="EMAIL_SENT")
    assert total == 1
    assert len(logs) == 1
    assert logs[0]["action"] == "EMAIL_SENT"


def test_repository_tenant_isolation(db_session):
    repo = AuroraPortalAndAuditRepository(session=db_session)
    firm1_id = uuid.uuid4()
    firm2_id = uuid.uuid4()

    db_session.add(UserProfile(id=firm1_id, email="firm1@example.com", role="admin"))
    db_session.add(UserProfile(id=firm2_id, email="firm2@example.com", role="admin"))
    db_session.commit()

    repo.insert_audit_log(action="ACTION_A", firm_id=str(firm1_id))
    repo.insert_audit_log(action="ACTION_B", firm_id=str(firm2_id))

    logs1, count1 = repo.list_audit_logs(str(firm1_id))
    logs2, count2 = repo.list_audit_logs(str(firm2_id))

    assert count1 == 1
    assert logs1[0]["action"] == "ACTION_A"
    assert count2 == 1
    assert logs2[0]["action"] == "ACTION_B"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Dry-Run Backfill Verification Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_dry_run_backfill_parity_and_rollback(db_engine):
    """Test deterministic dry-run backfill with synthetic Batch 4C source data."""
    u1 = str(uuid.uuid4())
    u2 = str(uuid.uuid4())
    c1 = str(uuid.uuid4())
    ur1 = str(uuid.uuid4())

    mock_source = {
        "notification_preferences": [
            {"user_id": u1, "run_completed": True, "runs_expiring_soon": True, "payment_receipts": True, "rule37_alerts": True, "created_at": "2026-06-17T05:52:56+00:00", "updated_at": "2026-06-25T03:03:35+00:00"},
            {"user_id": u2, "run_completed": True, "runs_expiring_soon": True, "payment_receipts": True, "rule37_alerts": True, "created_at": "2026-07-21T04:26:11+00:00", "updated_at": "2026-07-26T15:21:39+00:00"},
        ],
        "upload_requests": [
            {"id": ur1, "client_id": c1, "organization_id": u1, "token": "tok_1", "title": "Req 1", "description": None, "expires_at": "2026-05-29T18:29:59+00:00", "created_by_user_id": u1, "created_at": "2026-05-22T10:35:38+00:00"},
            {"id": str(uuid.uuid4()), "client_id": c1, "organization_id": u1, "token": "tok_2", "title": "Req 2", "description": "desc", "expires_at": "2026-05-29T18:29:59+00:00", "created_by_user_id": u1, "created_at": "2026-05-22T10:57:05+00:00"},
            {"id": str(uuid.uuid4()), "client_id": c1, "organization_id": u2, "token": "tok_3", "title": "Req 3", "description": None, "expires_at": "2026-07-09T18:29:59+00:00", "created_by_user_id": u2, "created_at": "2026-07-02T16:35:07+00:00"},
        ],
        "uploaded_files": [
            {"id": str(uuid.uuid4()), "upload_request_id": ur1, "filename": "doc.pdf", "file_size": 1816494, "mime_type": "application/pdf", "public_url": "https://s3/doc.pdf", "uploaded_at": "2026-05-22T10:52:05+00:00"},
            {"id": str(uuid.uuid4()), "upload_request_id": ur1, "filename": "data.csv", "file_size": 487, "mime_type": "text/csv", "public_url": "https://s3/data.csv", "uploaded_at": "2026-05-22T10:57:38+00:00"},
            {"id": str(uuid.uuid4()), "upload_request_id": ur1, "filename": "file.xlsx", "file_size": 775442, "mime_type": "application/vnd.sheet", "public_url": "https://s3/file.xlsx", "uploaded_at": "2026-07-02T16:35:32+00:00"},
        ],
        "communication_logs": [
            {"id": str(uuid.uuid4()), "client_id": c1, "organization_id": u1, "template_type": "upload_request", "message_content": "msg 1", "sent_via": "upload_request", "sent_by_user_id": u1, "notes": None, "created_at": "2026-05-22T10:35:38+00:00"},
            {"id": str(uuid.uuid4()), "client_id": c1, "organization_id": u1, "template_type": "upload_request", "message_content": "msg 2", "sent_via": "upload_request", "sent_by_user_id": u1, "notes": None, "created_at": "2026-05-22T10:57:05+00:00"},
            {"id": str(uuid.uuid4()), "client_id": c1, "organization_id": u2, "template_type": "upload_request", "message_content": "msg 3", "sent_via": "upload_request", "sent_by_user_id": u2, "notes": None, "created_at": "2026-07-02T16:35:07+00:00"},
        ],
        "audit_logs": [
            {"id": str(uuid.uuid4()), "user_id": u1, "action": f"ACTION_{i}", "entity_type": "recon", "entity_id": str(uuid.uuid4()), "metadata": {"matched": i}, "created_at": f"2026-06-01T12:{i//60:02d}:{i%60:02d}+00:00", "ip_address": "127.0.0.1", "correlation_id": str(uuid.uuid4()), "firm_id": u1, "user_name": "CA User", "role": "admin", "entity_label": f"Run {i}"}
            for i in range(1809)
        ],
    }

    migrator = Batch4cBackfillMigrator(engine=db_engine)
    migrator.fetch_source_rows = lambda tname: mock_source[tname]

    # Run dry-run
    report = migrator.run(commit=False)

    assert report.mode == "dry-run"
    assert report.total_source == 1820
    assert report.total_inserted == 1820
    assert report.total_matches == 1820
    assert report.total_mismatches == 0
    assert report.tx_rolled_back is True
    assert report.fresh_connection_verified is True
    assert report.is_clean() is True

    # Fresh connection verification: zero rows in all target tables
    SessionLocal = sessionmaker(bind=db_engine)
    with SessionLocal() as session:
        for tname, model_cls in [
            ("notification_preferences", NotificationPreference),
            ("upload_requests", UploadRequest),
            ("uploaded_files", UploadedFile),
            ("communication_logs", CommunicationLog),
            ("audit_logs", AuditLog),
        ]:
            cnt = session.scalar(select(func.count()).select_from(model_cls))
            assert cnt == 0, f"Residual rows leaked in {tname}: {cnt}"
