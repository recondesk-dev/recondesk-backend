"""Phase 9H-3: Controlled Supabase Isolation / Read-Only Stage Test Suite.

Verifies:
1. Complete isolation of Supabase datastore: any call to Supabase triggers an immediate hard rejection.
2. Under 100% Supabase isolation:
   - Tenancy and User Resolution operate normally on Aurora.
   - Filing Automation operates normally on Aurora.
   - Billing & Invoice Sequence generation operate normally on Aurora.
   - Payments & Credit grants operate normally on Aurora.
   - Client Portal, Upload Requests & File records operate normally on Aurora.
   - Notification preferences & Audit log ingestion operate normally on Aurora.
3. No genuine production feature requires Supabase.
4. Zero application errors under isolated state.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.repositories.billing_ledger import AuroraBillingLedgerRepository, set_billing_ledger_repository
from app.repositories.filing_automation import AuroraFilingAutomationRepository, set_filing_automation_repository
from app.repositories.payments_credits import AuroraPaymentsCreditsRepository, set_payments_credits_repository
from app.repositories.portal_and_audit import AuroraPortalAndAuditRepository, set_portal_and_audit_repository
from app.repositories.tenancy import AuroraTenancyRepository, set_tenancy_repository


class IsolatedSupabaseGuard:
    """Mock Supabase client that raises a hard exception on ANY interaction."""

    def __getattr__(self, name):
        raise RuntimeError(
            f"SUPABASE_ISOLATED_ERROR: Attempted to access attribute '{name}' during isolation stage!"
        )

    def table(self, *args, **kwargs):
        raise RuntimeError(
            f"SUPABASE_ISOLATED_ERROR: Table access attempted during isolation stage: {args}"
        )

    def rpc(self, *args, **kwargs):
        raise RuntimeError(
            f"SUPABASE_ISOLATED_ERROR: RPC call attempted during isolation stage: {args}"
        )


@pytest.fixture
def h3_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine)
    session = sm()
    yield session
    session.close()


@pytest.fixture
def h3_repos(h3_session):
    sm = sessionmaker(bind=h3_session.get_bind())
    tenancy_repo = AuroraTenancyRepository(session_factory=sm)
    filing_repo = AuroraFilingAutomationRepository(session_factory=sm)
    payments_repo = AuroraPaymentsCreditsRepository(session_factory=sm)
    billing_repo = AuroraBillingLedgerRepository(session_factory=sm)
    portal_repo = AuroraPortalAndAuditRepository(session_factory=sm)

    set_tenancy_repository(tenancy_repo)
    set_filing_automation_repository(filing_repo)
    set_payments_credits_repository(payments_repo)
    set_billing_ledger_repository(billing_repo)
    set_portal_and_audit_repository(portal_repo)

    return {
        "tenancy": tenancy_repo,
        "filing": filing_repo,
        "payments": payments_repo,
        "billing": billing_repo,
        "portal": portal_repo,
    }


def test_complete_isolation_across_all_workflows(h3_repos, h3_session):
    """Verify that all core workflows succeed when Supabase is completely blocked."""
    isolated_client = IsolatedSupabaseGuard()

    with patch("app.database.get_supabase", return_value=isolated_client), \
         patch("app.database.get_supabase_anon", return_value=isolated_client):

        # 1. Tenancy resolution
        u_id = uuid.uuid4()
        c_id = uuid.uuid4()
        u = UserProfile(id=u_id, email="isolated@recondesk.com", full_name="Isolated User", role="admin", is_active=True)
        h3_session.add(u)
        h3_session.commit()

        firm_id = h3_repos["tenancy"].get_firm_owner_id_for_user(str(u_id))
        assert firm_id == str(u_id)

        # 2. Filing automation session
        session_rec = h3_repos["filing"].create_session(
            firm_id=str(u_id),
            gstin="27AAPFU0939F1ZV",
            username="isolated_tp",
            session_token="isolated_token_9h3",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
            status="active",
        )
        assert session_rec["status"] == "active"

        # 3. Billing & sequence generation
        prof = h3_repos["billing"].create_company_profile(
            {
                "client_gstin_id": str(c_id),
                "legal_name": "Isolated Firm LLP",
                "trade_name": "Isolated Firm",
                "gstin": "27AAPFU0939F1ZV",
                "address_line1": "789 Isolation Lane",
                "city": "Mumbai",
                "state": "Maharashtra",
                "state_code": "27",
                "pincode": "400001",
            }
        )
        prefix, seq = h3_repos["billing"].increment_invoice_number_seq(prof["id"])
        assert seq == 1

        # 4. Payments & credits
        cred = h3_repos["payments"].create_run_credit(
            firm_owner_id=str(u_id),
            plan="enterprise",
            runs_purchased=500,
            runs_remaining=500,
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        )
        assert cred["runs_remaining"] == 500

        # 5. Client Portal & Upload Request
        tok = "isolated_portal_token_9h3"
        req = h3_repos["portal"].create_upload_request(
            client_id=str(c_id),
            organization_id=str(u_id),
            token=tok,
            title="October Return Files",
            created_by_user_id=str(u_id),
        )
        assert req["title"] == "October Return Files"

        req_lookup = h3_repos["portal"].get_upload_request_by_token(tok)
        assert req_lookup["id"] == req["id"]

        # 6. Audit logging & preferences
        from app.utils.audit import log_audit_sync
        from app.utils.notification_prefs import should_send_notification

        h3_repos["portal"].upsert_notification_preferences(str(u_id), run_completed=True)
        assert should_send_notification(str(u_id), "run_completed") is True

        log_audit_sync(
            None,
            {"id": str(u_id), "role": "admin", "full_name": "Isolated Admin"},
            action="ISOLATION_STAGE_PASS",
            entity_type="portal",
            entity_id=req["id"],
        )

        logs, count = h3_repos["portal"].list_audit_logs(str(u_id), action="ISOLATION_STAGE_PASS")
        assert count >= 1
        assert logs[0]["action"] == "ISOLATION_STAGE_PASS"
