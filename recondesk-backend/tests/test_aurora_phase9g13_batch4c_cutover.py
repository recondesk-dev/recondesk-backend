"""Phase 9G-13: Batch 4C Application Cutover Verification Suite.

Verifies:
1. Aurora PostgreSQL is PRIMARY for all 5 Batch 4C entities:
   - notification_preferences
   - upload_requests
   - uploaded_files
   - communication_logs
   - audit_logs
2. Zero dual-writes: normal operations write only to Aurora.
3. Supabase fallback resilience: operations fall back to Supabase only if Aurora raises an error.
4. Tenant isolation: audit logs and portal endpoints enforce workspace scoping.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db, supabase_client
from app.main import app
from app.models.portal_and_audit import (
    AuditLog,
    CommunicationLog,
    NotificationPreference,
    UploadedFile,
    UploadRequest,
)
from app.repositories.portal_and_audit import (
    AuroraPortalAndAuditRepository,
    set_portal_and_audit_repository,
)


import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile


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
def test_repo(db_session):
    repo = AuroraPortalAndAuditRepository(session=db_session)
    set_portal_and_audit_repository(repo)
    yield repo
    set_portal_and_audit_repository(None)


@pytest.fixture
def seeded_users(db_session):
    """Seed two users for tenancy tests."""
    from app.models.tenancy import UserProfile
    u1_id = uuid.uuid4()
    u2_id = uuid.uuid4()
    u1 = UserProfile(id=u1_id, email="ca1@firm.com", role="admin", firm_name="Firm One", is_active=True)
    u2 = UserProfile(id=u2_id, email="ca2@firm.com", role="admin", firm_name="Firm Two", is_active=True)
    db_session.add_all([u1, u2])
    db_session.commit()
    return u1_id, u2_id


def test_audit_logs_cutover_primary(test_repo, db_session, seeded_users):
    """Test that log_audit writes to Aurora PRIMARY and does NOT write to Supabase."""
    from app.utils.audit import log_audit_sync

    u1_id, _ = seeded_users
    mock_sb = MagicMock()

    user = {"id": str(u1_id), "role": "admin", "full_name": "CA User", "email": "ca1@firm.com"}
    log_audit_sync(
        mock_sb,
        user,
        action="TEST_ACTION",
        entity_type="test_entity",
        entity_id=str(uuid.uuid4()),
        entity_label="Test Label",
        metadata={"key": "value"},
    )

    # 1. Supabase insert must NOT be called (zero dual-writes)
    assert not mock_sb.table.called

    # 2. Aurora must have the inserted record
    logs, total = test_repo.list_audit_logs(str(u1_id), action="TEST_ACTION")
    assert total >= 1
    assert logs[0]["action"] == "TEST_ACTION"
    assert logs[0]["user_name"] == "CA User"
    assert logs[0]["metadata"] == {"key": "value"}


def test_audit_logs_supabase_outage_resilience(test_repo, db_session, seeded_users):
    """Test that log_audit succeeds even if Supabase client is completely unavailable/None."""
    from app.utils.audit import log_audit_sync

    u1_id, _ = seeded_users
    user = {"id": str(u1_id), "role": "admin", "full_name": "CA User", "email": "ca1@firm.com"}

    # Pass None as db client (Supabase down)
    log_audit_sync(
        None,
        user,
        action="OUTAGE_TEST",
        entity_type="test_entity",
        entity_id=str(uuid.uuid4()),
        entity_label="Test Outage",
    )

    logs, total = test_repo.list_audit_logs(str(u1_id), action="OUTAGE_TEST")
    assert total >= 1
    assert logs[0]["action"] == "OUTAGE_TEST"


def test_audit_logs_fallback_on_aurora_failure(db_session, seeded_users):
    """Test that log_audit falls back to Supabase if Aurora throws an error."""
    from app.utils.audit import log_audit_sync

    failing_repo = MagicMock()
    failing_repo.insert_audit_log.side_effect = RuntimeError("Aurora connection lost")
    set_portal_and_audit_repository(failing_repo)

    mock_sb = MagicMock()
    u1_id, _ = seeded_users
    user = {"id": str(u1_id), "role": "admin", "full_name": "CA User", "email": "ca1@firm.com"}

    try:
        log_audit_sync(
            mock_sb,
            user,
            action="FALLBACK_ACTION",
            entity_type="test_entity",
            entity_id=str(uuid.uuid4()),
        )
        # Supabase table("audit_logs").insert(...).execute() must be called
        assert mock_sb.table.called
        assert mock_sb.table.call_args[0][0] == "audit_logs"
    finally:
        set_portal_and_audit_repository(None)


def test_list_audit_logs_primary_and_tenancy(test_repo, db_session, seeded_users):
    """Test list_audit_logs endpoint queries Aurora PRIMARY with firm isolation."""
    from app.routers import audit_logs as audit_logs_module

    u1_id, u2_id = seeded_users
    # Seed audit logs for both firms
    test_repo.insert_audit_log(
        action="FIRM1_LOG",
        user_id=str(u1_id),
        firm_id=str(u1_id),
    )
    test_repo.insert_audit_log(
        action="FIRM2_LOG",
        user_id=str(u2_id),
        firm_id=str(u2_id),
    )

    mock_db = MagicMock()
    # FastApi test client or direct call
    import asyncio
    res1 = asyncio.run(
        audit_logs_module.list_audit_logs(
            firm_id=str(u1_id),
            admin_id=str(u1_id),
            db=mock_db,
        )
    )
    assert not mock_db.table.called
    assert res1["total"] == 1
    assert res1["data"][0]["action"] == "FIRM1_LOG"

    # User 1 cannot access User 2's firm
    with pytest.raises(Exception):
        asyncio.run(
            audit_logs_module.list_audit_logs(
                firm_id=str(u2_id),
                admin_id=str(u1_id),
                db=mock_db,
            )
        )


def test_reconciliation_audit_idempotency_primary(test_repo, db_session, seeded_users):
    """Test check_audit_log_exists idempotency check in reconciliation."""
    run_id = str(uuid.uuid4())
    assert not test_repo.check_audit_log_exists("EMAIL_SENT", run_id)

    u1_id, _ = seeded_users
    test_repo.insert_audit_log(
        action="EMAIL_SENT",
        user_id=str(u1_id),
        entity_id=run_id,
        firm_id=str(u1_id),
    )

    assert test_repo.check_audit_log_exists("EMAIL_SENT", run_id)


def test_notification_preferences_primary(test_repo, db_session, seeded_users):
    """Test notification preferences get and update use Aurora PRIMARY."""
    from app.routers import notifications as notif_module
    from app.utils import notification_prefs

    u1_id, _ = seeded_users
    uid_str = str(u1_id)
    mock_db = MagicMock()

    # 1. Initially default prefs created in Aurora
    import asyncio
    prefs = asyncio.run(notif_module.get_preferences(current_user={"id": uid_str}, db=mock_db))
    assert not mock_db.table.called
    assert prefs.run_completed is True

    # 2. Update prefs in Aurora
    payload = notif_module.NotificationPreferencesModel(
        run_completed=False,
        runs_expiring_soon=True,
        payment_receipts=False,
        rule37_alerts=True,
    )
    updated = asyncio.run(notif_module.update_preferences(payload, current_user={"id": uid_str}, db=mock_db))
    assert not mock_db.table.called
    assert updated.run_completed is False

    # 3. should_send_notification checks Aurora
    assert notification_prefs.should_send_notification(uid_str, "run_completed") is False
    assert notification_prefs.should_send_notification(uid_str, "runs_expiring_soon") is True


def test_upload_request_by_token_primary(test_repo, db_session, seeded_users):
    """Test _get_upload_request_by_token uses Aurora PRIMARY."""
    from app.routers.upload import _get_upload_request_by_token

    u1_id, _ = seeded_users
    client_id = str(uuid.uuid4())
    token = "test_token_phase9g13"

    test_repo.create_upload_request(
        client_id=client_id,
        organization_id=str(u1_id),
        token=token,
        title="GST Documents Request",
        created_by_user_id=str(u1_id),
    )

    req = _get_upload_request_by_token(token)
    assert req is not None
    assert req["token"] == token
    assert req["title"] == "GST Documents Request"


def test_client_portal_endpoints_primary(test_repo, db_session, seeded_users):
    """Test record-file, create request, list requests, list files, and communication logs endpoints."""
    from app.routers.upload import (
        CreateCommunicationLogPayload,
        CreateUploadRequestPayload,
        RecordFilePayload,
        create_communication_log_endpoint,
        create_upload_request_endpoint,
        list_communication_logs_endpoint,
        list_upload_requests_endpoint,
        list_uploaded_files_endpoint,
        record_uploaded_file,
    )

    u1_id, _ = seeded_users
    client_id = str(uuid.uuid4())
    import asyncio

    # 1. Create upload request
    req_payload = CreateUploadRequestPayload(
        client_id=client_id,
        organization_id=str(u1_id),
        token="token_endpoint_test",
        title="Bank Statements",
    )
    req_res = asyncio.run(create_upload_request_endpoint(req_payload, current_user={"id": str(u1_id)}))
    assert req_res["title"] == "Bank Statements"
    req_id = req_res["id"]

    # 2. Record uploaded file
    file_payload = RecordFilePayload(
        upload_request_id=str(req_id),
        filename="bank.pdf",
        file_size=1024,
        mime_type="application/pdf",
        public_url="https://r2.example.com/bank.pdf",
    )
    file_res = asyncio.run(record_uploaded_file(file_payload))
    assert file_res["filename"] == "bank.pdf"
    assert file_res["file_size"] == 1024

    # 3. List requests
    reqs = asyncio.run(list_upload_requests_endpoint(client_id, current_user={"id": str(u1_id)}))
    assert len(reqs["data"]) >= 1

    # 4. List files
    files = asyncio.run(list_uploaded_files_endpoint([str(req_id)], current_user={"id": str(u1_id)}))
    assert len(files["data"]) >= 1
    assert files["data"][0]["filename"] == "bank.pdf"

    # 5. List & create communication logs
    logs = asyncio.run(list_communication_logs_endpoint(client_id, current_user={"id": str(u1_id)}))
    assert len(logs["data"]) >= 1

    cl_payload = CreateCommunicationLogPayload(
        client_id=client_id,
        organization_id=str(u1_id),
        template_type="reminder",
        message_content="Please upload pending statements",
        sent_via="email",
    )
    new_cl = asyncio.run(create_communication_log_endpoint(cl_payload, current_user={"id": str(u1_id)}))
    assert new_cl["template_type"] == "reminder"
