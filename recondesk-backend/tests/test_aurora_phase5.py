"""Tests for ReconDesk Dual-Auth / AWS Aurora Migration — Phase 5.

Phase 5: Tenancy & Client Mutation Convergence
Comprehensive test suite verifying:
1. Dual-write behavior across all tenancy and client mutation paths.
2. Distributed sync pending coordinator and failure resilience.
3. Inline reconciliation from Supabase to Aurora on sync pending.
4. Supabase fallback when Aurora is down during sync pending.
5. Invariant preservation: authoritative empty [] when clean.
6. Foreign key auto-seed safety.
7. Tri-state return semantics (None, [], populated).
8. Absence of tokens/secrets in sync and mirror log records.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, TeamMember, UserProfile
from app.models.user import AutoApproveThresholdUpdate, ProfileUpdateRequest
from app.repositories.tenancy import (
    AuroraTenancyRepository,
    get_tenancy_repository,
    set_tenancy_repository,
)
from app.routers.clients import (
    AssignClientBody,
    ClientCreate,
    ClientUpdate,
    assign_client,
    create_client,
    delete_client,
    list_clients,
    update_client,
)
from app.routers.team import (
    TeamInviteBody,
    accept_team_invite,
    invite_team_member,
    remove_team_member,
)
from app.routers.users import (
    onboarding_complete as users_onboarding_complete,
    set_demo_tour_seen,
    set_showcase_seen,
    update_auto_approve_threshold,
    update_profile,
)
from app.database import ensure_user_profile
from app.services.tenancy_sync import (
    clear_tenancy_sync_pending,
    is_tenancy_sync_pending,
    mark_tenancy_sync_pending,
    mirror_team_member_create_to_aurora,
    reconcile_user_tenancy_from_supabase,
)


@pytest.fixture
def tenancy_sqlite_engine():
    """Create a temporary SQLite engine with tenancy tables."""
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
def tenancy_repo(tenancy_sqlite_engine) -> AuroraTenancyRepository:
    """Provide an AuroraTenancyRepository backed by SQLite."""
    factory = sessionmaker(
        bind=tenancy_sqlite_engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    repo = AuroraTenancyRepository(session_factory=factory)
    set_tenancy_repository(repo)
    yield repo
    set_tenancy_repository(None)


@pytest.fixture(autouse=True)
def clean_sync_registry():
    """Ensure tenancy sync pending flags are wiped between tests."""
    from app.services import tenancy_sync
    with tenancy_sync._local_registry_lock:
        tenancy_sync._local_sync_registry.clear()
    yield
    with tenancy_sync._local_registry_lock:
        tenancy_sync._local_sync_registry.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Client Mutations Dual-Write Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClientMutationsDualWrite:
    """Tests for client creation, update, assign, soft-delete, and restore."""

    @pytest.mark.asyncio
    async def test_create_client_dual_write_success(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """1. Supabase client creation writes to Aurora with exact same UUID and fields."""
        admin_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        gstin = "27ABCDE1234F1Z5"

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=admin_id, role="admin", is_active=True))
            session.commit()

        body = ClientCreate(
            gstin=gstin,
            trade_name="Test Corp",
            legal_name="Test Corporation Pvt Ltd",
            scheme_type="regular",
            filing_frequency="monthly",
        )
        current_user = {"id": admin_id, "role": "admin"}

        fake_sb_row = {
            "id": client_id,
            "firm_owner_id": admin_id,
            "gstin": gstin,
            "trade_name": "Test Corp",
            "legal_name": "Test Corporation Pvt Ltd",
            "state_code": "27",
            "scheme_type": "regular",
            "filing_frequency": "monthly",
            "is_active": True,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        # select check for existing soft-deleted
        mock_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        # insert
        mock_table.insert.return_value.execute.return_value.data = [fake_sb_row]
        # select single
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = fake_sb_row

        with patch("app.routers.clients.get_supabase", return_value=mock_sb), \
             patch("app.routers.clients.assert_gstin_capacity"), \
             patch("app.routers.clients._verify_gstin", new_callable=AsyncMock) as mock_v, \
             patch("app.routers.clients.log_audit", new_callable=AsyncMock), \
             patch("app.routers.clients.invalidate_user_dashboard"):
            mock_v.return_value = {"status": "Active"}

            resp = await create_client(body=body, current_user=current_user)
            assert resp.status_code == 201

        # Verify record exists in Aurora with exact same id and fields
        aurora_client = tenancy_repo.get_client_gstin(client_id)
        assert aurora_client is not None
        assert aurora_client["id"] == client_id
        assert aurora_client["gstin"] == gstin
        assert aurora_client["firm_owner_id"] == admin_id
        assert aurora_client["trade_name"] == "Test Corp"
        assert aurora_client["is_active"] is True
        assert not is_tenancy_sync_pending(admin_id)

    @pytest.mark.asyncio
    async def test_create_client_aurora_failure_non_blocking(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """2. Aurora write failure during POST /api/clients does not 500; returns 201; marks sync pending."""
        admin_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        gstin = "27FAILT1234A1Z5"

        body = ClientCreate(
            gstin=gstin,
            trade_name="Fail Test Corp",
            scheme_type="regular",
            filing_frequency="monthly",
        )
        current_user = {"id": admin_id, "role": "admin"}

        fake_sb_row = {
            "id": client_id,
            "firm_owner_id": admin_id,
            "gstin": gstin,
            "trade_name": "Fail Test Corp",
            "state_code": "27",
            "scheme_type": "regular",
            "filing_frequency": "monthly",
            "is_active": True,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        mock_table.insert.return_value.execute.return_value.data = [fake_sb_row]
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = fake_sb_row

        with patch("app.routers.clients.get_supabase", return_value=mock_sb), \
             patch("app.routers.clients.assert_gstin_capacity"), \
             patch("app.routers.clients._verify_gstin", new_callable=AsyncMock) as mock_v, \
             patch("app.routers.clients.log_audit", new_callable=AsyncMock), \
             patch("app.routers.clients.invalidate_user_dashboard"), \
             patch.object(tenancy_repo, "create_client", side_effect=Exception("Simulated Aurora Outage")):
            mock_v.return_value = {"status": "Active"}

            resp = await create_client(body=body, current_user=current_user)
            # Must succeed with 201 despite Aurora failure
            assert resp.status_code == 201

        # Must have marked sync pending for admin_id
        assert is_tenancy_sync_pending(admin_id) is True

    @pytest.mark.asyncio
    async def test_update_client_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """6. PATCH /api/clients/{id} updates both stores."""
        admin_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=client_id,
                    firm_owner_id=admin_id,
                    gstin="27UPDATE1234F1Z",
                    trade_name="Old Name",
                    is_active=True,
                ),
            ])
            session.commit()

        body = ClientUpdate(trade_name="New Updated Name")
        current_user = {"id": admin_id, "role": "admin"}

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": client_id, "firm_owner_id": admin_id, "is_active": True}
        ]
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": client_id,
            "firm_owner_id": admin_id,
            "trade_name": "New Updated Name",
            "is_active": True,
        }

        with patch("app.routers.clients.get_supabase", return_value=mock_sb):
            res = await update_client(client_id=client_id, body=body, current_user=current_user)
            assert res["trade_name"] == "New Updated Name"

        # Check Aurora updated
        aurora_client = tenancy_repo.get_client_gstin(client_id)
        assert aurora_client is not None
        assert aurora_client["trade_name"] == "New Updated Name"

    @pytest.mark.asyncio
    async def test_assign_client_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """7. PATCH /api/clients/{id}/assign updates both stores."""
        admin_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                ClientGSTIN(
                    id=client_id,
                    firm_owner_id=admin_id,
                    gstin="27ASSIGN1234F1Z",
                    assigned_to=None,
                    is_active=True,
                ),
            ])
            session.commit()

        body = AssignClientBody(assigned_to=staff_id)

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        # client lookup
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": client_id, "firm_owner_id": admin_id, "is_active": True}
        ]
        # team member lookup
        mock_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": str(uuid.uuid4())}
        ]
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": client_id,
            "firm_owner_id": admin_id,
            "assigned_to": staff_id,
            "is_active": True,
        }

        with patch("app.routers.clients.get_supabase", return_value=mock_sb):
            res = await assign_client(client_id=client_id, body=body, admin_id=admin_id)
            assert res["assigned_to"] == staff_id

        aurora_client = tenancy_repo.get_client_gstin(client_id)
        assert aurora_client["assigned_to"] == staff_id

    @pytest.mark.asyncio
    async def test_soft_delete_client_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """8. DELETE /api/clients/{id} soft deletes in both stores (is_active = False)."""
        admin_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=client_id,
                    firm_owner_id=admin_id,
                    gstin="27DELET1234A1Z5",
                    is_active=True,
                ),
            ])
            session.commit()

        current_user = {"id": admin_id, "role": "admin"}

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": client_id, "is_active": False, "trade_name": "Deleted Co"}
        ]

        with patch("app.routers.clients.get_supabase", return_value=mock_sb), \
             patch("app.routers.clients.log_audit", new_callable=AsyncMock), \
             patch("app.routers.clients.invalidate_user_dashboard"):
            await delete_client(client_id=client_id, current_user=current_user)

        aurora_client = tenancy_repo.get_client_gstin(client_id)
        assert aurora_client["is_active"] is False

    @pytest.mark.asyncio
    async def test_restore_client_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """9. Re-creating previously deleted client restores is_active = True in both stores."""
        admin_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        gstin = "27RESTO1234A1Z5"

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=client_id,
                    firm_owner_id=admin_id,
                    gstin=gstin,
                    is_active=False,
                ),
            ])
            session.commit()

        body = ClientCreate(
            gstin=gstin,
            trade_name="Restored Co",
            scheme_type="regular",
            filing_frequency="monthly",
        )
        current_user = {"id": admin_id, "role": "admin"}

        fake_restored_row = {
            "id": client_id,
            "firm_owner_id": admin_id,
            "gstin": gstin,
            "trade_name": "Restored Co",
            "is_active": True,
        }

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        # existing soft-deleted found!
        mock_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": client_id, "is_active": False}
        ]
        mock_table.update.return_value.eq.return_value.execute.return_value.data = [fake_restored_row]
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = fake_restored_row

        with patch("app.routers.clients.get_supabase", return_value=mock_sb), \
             patch("app.routers.clients.log_audit", new_callable=AsyncMock), \
             patch("app.routers.clients.invalidate_user_dashboard"):
            resp = await create_client(body=body, current_user=current_user)
            assert resp.status_code == 200

        aurora_client = tenancy_repo.get_client_gstin(client_id)
        assert aurora_client["is_active"] is True
        assert aurora_client["trade_name"] == "Restored Co"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Sync Pending & Recovery Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSyncPendingAndRecovery:
    """Tests verifying pending sync behavior, reconciliation, and fallback."""

    @pytest.mark.asyncio
    async def test_sync_pending_triggers_reconciliation(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """3. Next GET /api/clients detects pending sync, reconciles, and returns all clients."""
        admin_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        gstin = "27RECON1234A1Z5"

        # Initially, admin profile exists in Aurora, but client is missing
        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=admin_id, role="admin", is_active=True))
            session.commit()

        # Mark sync pending for admin
        mark_tenancy_sync_pending(admin_id, action="create_client", entity_type="client_gstin", entity_id=client_id)
        assert is_tenancy_sync_pending(admin_id) is True

        # Supabase mock contains the newly created client
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": admin_id, "role": "admin", "is_active": True}
        ]
        mock_table.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": client_id,
                "firm_owner_id": admin_id,
                "gstin": gstin,
                "trade_name": "Reconciled Co",
                "is_active": True,
            }
        ]

        with patch("app.database.get_supabase", return_value=mock_sb):
            clients = await list_clients(current_user={"id": admin_id, "role": "admin"})

        # Aurora should now have the reconciled client, and pending flag is cleared!
        assert len(clients) == 1
        assert clients[0]["id"] == client_id
        assert clients[0]["gstin"] == gstin
        assert is_tenancy_sync_pending(admin_id) is False

    @pytest.mark.asyncio
    async def test_sync_pending_aurora_down_falls_back(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """4. Next GET /api/clients detects pending sync, reconciliation fails because Aurora is down, falls back to Supabase."""
        admin_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        mark_tenancy_sync_pending(admin_id, action="create_client", entity_type="client_gstin", entity_id=client_id)

        # Mock Supabase for list_clients fallback query
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"id": client_id, "firm_owner_id": admin_id, "trade_name": "Fallback Client", "is_active": True}
        ]

        # Simulate reconciliation failure (e.g. Aurora connection refused)
        with patch("app.services.tenancy_sync.reconcile_user_tenancy_from_supabase", return_value=False), \
             patch("app.routers.clients.get_supabase", return_value=mock_sb):
            clients = await list_clients(current_user={"id": admin_id, "role": "admin"})

        assert len(clients) == 1
        assert clients[0]["trade_name"] == "Fallback Client"

    @pytest.mark.asyncio
    async def test_clean_state_authoritative_empty(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """5. When sync is not pending and Aurora is healthy, empty Aurora clients returns [] without querying Supabase."""
        admin_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=admin_id, role="admin", is_active=True))
            session.commit()

        assert is_tenancy_sync_pending(admin_id) is False

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            clients = await list_clients(current_user={"id": admin_id, "role": "admin"})

            assert clients == []
            # Phase 3D invariant preserved: Supabase was NEVER queried
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. User Profile Mutations Dual-Write Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestUserProfileMutationsDualWrite:
    """Tests for user profile updates, onboarding, threshold, and ensure."""

    @pytest.mark.asyncio
    async def test_profile_update_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """10. PATCH /api/users/profile updates both stores."""
        user_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=user_id, email="ca@example.com", full_name="Old CA", role="admin", is_active=True))
            session.commit()

        payload = ProfileUpdateRequest(
            full_name="New CA Name",
            phone="9876543210",
            firm_name="Premier Tax Advisors",
            icai_membership_number="ICAI-12345",
            firm_gstin="27AAAAA0000A1Z5",
            firm_city="Mumbai",
        )
        current_user = {"id": user_id, "email": "ca@example.com", "role": "admin"}

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.return_value.data = [{"id": user_id}]

        with patch("app.routers.users.get_supabase", return_value=mock_sb), \
             patch("app.routers.users.get_user_profile", return_value={"id": user_id, "role": "admin", "full_name": "New CA Name"}):
            resp = await update_profile(payload=payload, current_user=current_user)
            assert resp.full_name == "New CA Name"

        # Check Aurora
        prof = tenancy_repo.get_user_profile(user_id)
        assert prof is not None
        assert prof["full_name"] == "New CA Name"
        assert prof["firm_name"] == "Premier Tax Advisors"
        assert prof["firm_city"] == "Mumbai"

    @pytest.mark.asyncio
    async def test_onboarding_complete_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """11. PATCH /api/users/onboarding-complete updates both stores."""
        user_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=user_id, onboarding_completed=False, role="admin", is_active=True))
            session.commit()

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.return_value.data = [{"id": user_id}]

        with patch("app.routers.users.get_supabase", return_value=mock_sb):
            resp = await users_onboarding_complete(current_user={"id": user_id})
            assert resp == {"success": True}

        prof = tenancy_repo.get_user_profile(user_id)
        assert prof["onboarding_completed"] is True

    @pytest.mark.asyncio
    async def test_auto_approve_threshold_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """12. PATCH /api/users/auto-approve-threshold updates both stores."""
        user_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=user_id, auto_approve_confidence_threshold=95, role="admin", is_active=True))
            session.commit()

        payload = AutoApproveThresholdUpdate(auto_approve_confidence_threshold=80)
        current_user = {"id": user_id, "role": "admin"}

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.return_value.data = [{"id": user_id}]

        with patch("app.routers.users.get_supabase", return_value=mock_sb), \
             patch("app.routers.users.get_user_profile", return_value={"id": user_id, "role": "admin", "auto_approve_confidence_threshold": 80}):
            resp = await update_auto_approve_threshold(payload=payload, current_user=current_user)
            assert resp.auto_approve_confidence_threshold == 80

        prof = tenancy_repo.get_user_profile(user_id)
        assert prof["auto_approve_confidence_threshold"] == 80

    def test_ensure_user_profile_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """16. ensure_user_profile() writes to Aurora if missing."""
        user_id = str(uuid.uuid4())
        email = "auto@example.com"

        assert tenancy_repo.get_user_profile(user_id) is None

        mock_sb = MagicMock()
        mock_auth = MagicMock()
        mock_auth_user = MagicMock()
        mock_auth_user.user.email = email
        mock_auth.admin.get_user_by_id.return_value = mock_auth_user
        mock_sb.auth = mock_auth

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        mock_table.insert.return_value.execute.return_value.data = [
            {"id": user_id, "email": email, "role": "admin", "is_active": True}
        ]

        with patch("app.database.get_supabase", return_value=mock_sb), \
             patch("app.database._is_invited_user", return_value=False):
            prof = ensure_user_profile(user_id, client=mock_sb)
            assert prof["id"] == user_id

        aurora_prof = tenancy_repo.get_user_profile(user_id)
        assert aurora_prof is not None
        assert aurora_prof["id"] == user_id


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Team Mutations Dual-Write Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTeamMutationsDualWrite:
    """Tests for team invitations, acceptance, and removal."""

    @pytest.mark.asyncio
    async def test_team_invite_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """13. POST /api/team/invite writes pending invite to both stores."""
        admin_id = str(uuid.uuid4())
        invite_email = "staff@firm.com"

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=admin_id, role="admin", is_active=True))
            session.commit()

        body = TeamInviteBody(email=invite_email, role="staff")
        bg_tasks = MagicMock()

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.eq.return_value.is_.return_value.eq.return_value.execute.return_value.data = []
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        mock_table.insert.return_value.execute.return_value.data = [{"id": str(uuid.uuid4())}]

        with patch("app.routers.team.get_supabase", return_value=mock_sb), \
             patch("app.routers.team.get_user_profile", return_value={"id": admin_id, "role": "admin", "firm_name": "CA Firm"}), \
             patch("app.routers.team.log_action", new_callable=AsyncMock):
            res = await invite_team_member(body=body, background_tasks=bg_tasks, admin_id=admin_id)
            assert res == {"invited": True}

        # Check Aurora team_members
        with Session(tenancy_sqlite_engine) as session:
            tm = session.query(TeamMember).filter_by(firm_owner_id=admin_id, invited_email=invite_email).first()
            assert tm is not None
            assert tm.role == "staff"
            assert tm.is_active is False

    @pytest.mark.asyncio
    async def test_team_accept_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """14. POST /api/team/accept/{token} activates member in both stores and sets role to staff."""
        admin_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        member_row_id = str(uuid.uuid4())
        token = "secret-invite-token-12345"

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                UserProfile(id=staff_id, email="accepted@firm.com", role="admin", is_active=True),
                TeamMember(
                    id=member_row_id,
                    firm_owner_id=admin_id,
                    invited_email="accepted@firm.com",
                    invite_token=token,
                    invite_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                    is_active=False,
                ),
            ])
            session.commit()

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        invite_data = {
            "id": member_row_id,
            "firm_owner_id": admin_id,
            "invited_email": "accepted@firm.com",
            "invite_token": token,
            "invite_expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
        mock_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            invite_data
        ]
        mock_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        # user profile check
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": staff_id, "email": "accepted@firm.com"}
        ]
        mock_table.update.return_value.eq.return_value.execute.return_value.data = [{"id": member_row_id}]

        with patch("app.routers.team.get_supabase", return_value=mock_sb), \
             patch("app.routers.team._user_profile_row_for_email", return_value={"id": staff_id, "email": "accepted@firm.com"}):
            res = await accept_team_invite(token=token)
            assert res["status"] == "accepted"

        # Verify team member is active in Aurora
        with Session(tenancy_sqlite_engine) as session:
            tm = session.query(TeamMember).filter_by(id=member_row_id).first()
            assert tm.is_active is True
            assert str(tm.member_user_id) == staff_id

        # Verify staff role updated in Aurora
        prof = tenancy_repo.get_user_profile(staff_id)
        assert prof["role"] == "staff"

    @pytest.mark.asyncio
    async def test_team_remove_dual_write(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """15. DELETE /api/team/members/{id} deactivates in both stores."""
        admin_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        member_row_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                TeamMember(
                    id=member_row_id,
                    firm_owner_id=admin_id,
                    member_user_id=staff_id,
                    is_active=True,
                ),
            ])
            session.commit()

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": member_row_id}
        ]
        mock_table.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": member_row_id}]

        with patch("app.routers.team.get_supabase", return_value=mock_sb), \
             patch("app.routers.team.log_action", new_callable=AsyncMock):
            res = await remove_team_member(member_id=member_row_id, admin_id=admin_id)
            assert res == {"removed": True}

        with Session(tenancy_sqlite_engine) as session:
            tm = session.query(TeamMember).filter_by(id=member_row_id).first()
            assert tm.is_active is False
            assert tm.member_user_id is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Foreign Key Safety & Security Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestForeignKeysAndSecurity:
    """Tests for FK auto-seeding safety and absence of secrets in sync logs."""

    def test_fk_safety_auto_seed_owner(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """17. Creating client when firm owner profile is missing in Aurora does not FK fail; auto-seeds profile."""
        missing_owner_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        assert tenancy_repo.get_user_profile(missing_owner_id) is None

        # Should not raise ForeignKeyViolation
        created = tenancy_repo.create_client({
            "id": client_id,
            "firm_owner_id": missing_owner_id,
            "gstin": "27AUTOOWNER1234",
            "is_active": True,
        })
        assert created["id"] == client_id

        # Profile was auto-seeded
        prof = tenancy_repo.get_user_profile(missing_owner_id)
        assert prof is not None
        assert prof["id"] == missing_owner_id
        assert prof["is_active"] is True

    def test_fk_safety_auto_seed_assignee(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """18. Assigning client to staff not yet in Aurora does not FK fail; auto-seeds profile."""
        owner_id = str(uuid.uuid4())
        missing_staff_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=owner_id, role="admin", is_active=True))
            session.commit()

        assert tenancy_repo.get_user_profile(missing_staff_id) is None

        created = tenancy_repo.create_client({
            "id": client_id,
            "firm_owner_id": owner_id,
            "gstin": "27AUTOSTAFF1234",
            "assigned_to": missing_staff_id,
            "is_active": True,
        })
        assert created["assigned_to"] == missing_staff_id

        staff_prof = tenancy_repo.get_user_profile(missing_staff_id)
        assert staff_prof is not None
        assert staff_prof["id"] == missing_staff_id
        assert staff_prof["role"] == "staff"

    def test_no_secrets_in_sync_logs(
        self, tenancy_repo, caplog
    ):
        """23. Verify that log records from sync/mirror do not contain invite tokens, passwords, or auth tokens."""
        firm_owner_id = str(uuid.uuid4())
        member_id = str(uuid.uuid4())
        secret_token = "SUPER_SECRET_INVITE_TOKEN_XYZ_12345"

        member_row = {
            "id": member_id,
            "firm_owner_id": firm_owner_id,
            "invited_email": "target@example.com",
            "invite_token": secret_token,
            "role": "staff",
        }

        with patch.object(tenancy_repo, "create_or_update_team_member", side_effect=Exception("DB Failure")):
            with caplog.at_level(logging.WARNING):
                mirror_team_member_create_to_aurora(member_row, firm_owner_id)

        # Check logs
        log_text = caplog.text
        assert secret_token not in log_text
        assert "password" not in log_text.lower()
        assert "token" not in log_text.lower() or "create_team_member" in log_text


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Tri-State & Bounded Limit Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriStateAndBounds:
    """Tests verifying tri-state return values and bounded limit enforcement."""

    def test_tri_state_none_allows_fallback(self, tenancy_repo):
        """19. list_accessible_clients returns None for user not in Aurora; caller falls back to Supabase."""
        unknown_id = str(uuid.uuid4())
        res = tenancy_repo.list_accessible_clients(unknown_id, role="admin")
        assert res is None

    def test_tri_state_empty_forbids_fallback(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """20. list_accessible_clients returns [] for existing user with 0 clients; caller does NOT fall back."""
        user_id = str(uuid.uuid4())
        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=user_id, role="admin", is_active=True))
            session.commit()

        res = tenancy_repo.list_accessible_clients(user_id, role="admin")
        assert res == []

    def test_tri_state_populated_forbids_fallback(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """21. list_accessible_clients returns list; caller does NOT fall back."""
        user_id = str(uuid.uuid4())
        c1 = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=user_id, role="admin", is_active=True),
                ClientGSTIN(id=c1, firm_owner_id=user_id, gstin="27TEST111111111", is_active=True),
            ])
            session.commit()

        res = tenancy_repo.list_accessible_clients(user_id, role="admin")
        assert isinstance(res, list)
        assert len(res) == 1
        assert res[0]["id"] == c1

    def test_bounded_limit_enforced(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """22. list_accessible_clients respects limit, max 500."""
        user_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=user_id, role="admin", is_active=True))
            clients = [
                ClientGSTIN(
                    id=str(uuid.uuid4()),
                    firm_owner_id=user_id,
                    gstin=f"27BOUND{i:04d}1Z1",
                    is_active=True,
                )
                for i in range(10)
            ]
            session.add_all(clients)
            session.commit()

        # Custom limit 3
        res = tenancy_repo.list_accessible_clients(user_id, role="admin", limit=3)
        assert len(res) == 3

        # Default limit
        res_default = tenancy_repo.list_accessible_clients(user_id, role="admin")
        assert len(res_default) == 10
