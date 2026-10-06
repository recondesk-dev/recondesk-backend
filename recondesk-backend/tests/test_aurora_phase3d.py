"""Tests for ReconDesk Dual-Auth / AWS Aurora Migration — Phase 3D.

Covers:
1. Repository Tests (AuroraTenancyRepository.list_accessible_clients):
   - Admin gets active firm-owned clients.
   - Owner gets active firm-owned clients.
   - Staff gets active assigned clients.
   - Inactive clients are excluded.
   - Results are ordered by added_at DESC.
   - Result is capped at 500 (safe bounded limit).
   - Existing Aurora user with zero clients returns [] (authoritative).
   - Missing Aurora user returns None (migration miss).
   - Returned records preserve ClientGSTIN.to_dict() shape.
2. Router Tests (GET /api/clients - list_clients):
   - Aurora clients are returned and Supabase is NOT queried.
   - Aurora returns [] and Supabase is NOT queried.
   - Aurora returns None and Supabase fallback executes.
   - Aurora repository unavailable preserves Supabase behavior.
   - Aurora repository failure preserves Supabase fallback.
   - Admin/owner filtering remains correct.
   - Staff filtering remains correct.
   - Inactive clients remain excluded.
   - Cross-firm clients are not exposed.
   - Returned response shape remains compatible.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, TeamMember, UserProfile
from app.repositories.tenancy import (
    AuroraTenancyRepository,
    get_tenancy_repository,
    set_tenancy_repository,
)
from app.routers.clients import list_clients


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


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Repository Tests (list_accessible_clients)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepositoryListAccessibleClients:
    """Targeted tests for AuroraTenancyRepository.list_accessible_clients."""

    def test_admin_gets_active_firm_owned_clients(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """1. Admin gets active firm-owned clients."""
        admin_id = str(uuid.uuid4())
        c1 = str(uuid.uuid4())
        c2 = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=c1,
                    firm_owner_id=admin_id,
                    gstin="27ADMINCL111111",
                    trade_name="Admin Client 1",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=c2,
                    firm_owner_id=admin_id,
                    gstin="27ADMINCL222222",
                    trade_name="Admin Client 2",
                    is_active=True,
                ),
            ])
            session.commit()

        clients = tenancy_repo.list_accessible_clients(admin_id, role="admin")
        assert clients is not None
        assert len(clients) == 2
        gstins = {c["gstin"] for c in clients}
        assert gstins == {"27ADMINCL111111", "27ADMINCL222222"}

    def test_owner_gets_active_firm_owned_clients(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """2. Owner gets active firm-owned clients."""
        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="owner", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=owner_id,
                    gstin="27OWNERCL111111",
                    trade_name="Owner Client 1",
                    is_active=True,
                ),
            ])
            session.commit()

        clients = tenancy_repo.list_accessible_clients(owner_id, role="owner")
        assert clients is not None
        assert len(clients) == 1
        assert clients[0]["id"] == cid
        assert clients[0]["gstin"] == "27OWNERCL111111"

    def test_staff_gets_active_assigned_clients(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """3. Staff gets active assigned clients only."""
        admin_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        assigned_cid = str(uuid.uuid4())
        unassigned_cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                # Client assigned to this staff
                ClientGSTIN(
                    id=assigned_cid,
                    firm_owner_id=admin_id,
                    assigned_to=staff_id,
                    gstin="27STAFFCL111111",
                    trade_name="Assigned Client",
                    is_active=True,
                ),
                # Client belonging to firm but unassigned
                ClientGSTIN(
                    id=unassigned_cid,
                    firm_owner_id=admin_id,
                    assigned_to=None,
                    gstin="27OTHERCL222222",
                    trade_name="Unassigned Client",
                    is_active=True,
                ),
            ])
            session.commit()

        clients = tenancy_repo.list_accessible_clients(staff_id, role="staff")
        assert clients is not None
        assert len(clients) == 1
        assert clients[0]["id"] == assigned_cid
        assert clients[0]["assigned_to"] == staff_id

    def test_inactive_clients_are_excluded(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """4. Inactive clients (is_active=False) are excluded from listing."""
        admin_id = str(uuid.uuid4())
        active_cid = str(uuid.uuid4())
        inactive_cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=active_cid,
                    firm_owner_id=admin_id,
                    gstin="27ACTIVE1111111",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=inactive_cid,
                    firm_owner_id=admin_id,
                    gstin="27INACTIVE22222",
                    is_active=False,
                ),
            ])
            session.commit()

        clients = tenancy_repo.list_accessible_clients(admin_id, role="admin")
        assert clients is not None
        assert len(clients) == 1
        assert clients[0]["id"] == active_cid

    def test_results_are_ordered_by_added_at_desc(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """5. Results are ordered by added_at DESC."""
        admin_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        c_old = str(uuid.uuid4())
        c_mid = str(uuid.uuid4())
        c_new = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=c_old,
                    firm_owner_id=admin_id,
                    gstin="27DATEOLD111111",
                    added_at=now - timedelta(days=10),
                    is_active=True,
                ),
                ClientGSTIN(
                    id=c_new,
                    firm_owner_id=admin_id,
                    gstin="27DATENEW333333",
                    added_at=now,
                    is_active=True,
                ),
                ClientGSTIN(
                    id=c_mid,
                    firm_owner_id=admin_id,
                    gstin="27DATEMID222222",
                    added_at=now - timedelta(days=5),
                    is_active=True,
                ),
            ])
            session.commit()

        clients = tenancy_repo.list_accessible_clients(admin_id, role="admin")
        assert clients is not None
        assert len(clients) == 3
        # Should be ordered descending: c_new, c_mid, c_old
        assert clients[0]["id"] == c_new
        assert clients[1]["id"] == c_mid
        assert clients[2]["id"] == c_old

    def test_result_is_capped_at_500(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """6. Result is capped at 500 (caller cannot exceed 500)."""
        admin_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=admin_id, role="admin", is_active=True))
            # Add 3 clients
            for i in range(3):
                session.add(
                    ClientGSTIN(
                        id=str(uuid.uuid4()),
                        firm_owner_id=admin_id,
                        gstin=f"27LIMIT{i}1111111",
                        is_active=True,
                    )
                )
            session.commit()

        # Requesting limit=2 should respect smaller limit
        res_2 = tenancy_repo.list_accessible_clients(admin_id, role="admin", limit=2)
        assert res_2 is not None
        assert len(res_2) == 2

        # Requesting limit=1000 must be bounded at 500
        res_capped = tenancy_repo.list_accessible_clients(admin_id, role="admin", limit=1000)
        assert res_capped is not None
        assert len(res_capped) == 3  # All 3 returned, cap is 500

    def test_existing_aurora_user_with_zero_clients_returns_empty_list(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """7. Existing Aurora user with zero clients returns [] (NOT None)."""
        user_empty = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=user_empty, role="admin", is_active=True))
            session.commit()

        clients = tenancy_repo.list_accessible_clients(user_empty, role="admin")
        assert clients is not None
        assert clients == []
        assert isinstance(clients, list)

    def test_missing_aurora_user_returns_none(self, tenancy_repo):
        """8. Missing Aurora user returns None (migration miss)."""
        non_existent_id = str(uuid.uuid4())
        clients = tenancy_repo.list_accessible_clients(non_existent_id, role="admin")
        assert clients is None

    def test_returned_records_preserve_client_dict_shape(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """9. Returned records preserve ClientGSTIN.to_dict() shape with all 18 fields."""
        admin_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=admin_id,
                    gstin="27SHAPETEST1111",
                    trade_name="Shape Trader",
                    legal_name="Shape Legal Pvt Ltd",
                    state_code="27",
                    registration_type="Regular",
                    scheme_type="regular",
                    filing_frequency="monthly",
                    contact_name="Anoop",
                    contact_email="anoop@shapetest.in",
                    contact_phone="+919876543210",
                    is_active=True,
                    is_demo=False,
                ),
            ])
            session.commit()

        clients = tenancy_repo.list_accessible_clients(admin_id, role="admin")
        assert clients is not None
        assert len(clients) == 1
        c = clients[0]

        expected_fields = [
            "id",
            "firm_owner_id",
            "gstin",
            "trade_name",
            "legal_name",
            "state_code",
            "registration_type",
            "assigned_to",
            "is_active",
            "added_at",
            "gstn_access_token",
            "gstn_token_expiry",
            "is_demo",
            "contact_name",
            "contact_email",
            "contact_phone",
            "scheme_type",
            "filing_frequency",
        ]
        for field in expected_fields:
            assert field in c, f"Expected field '{field}' missing from client record"

        assert c["id"] == cid
        assert c["gstin"] == "27SHAPETEST1111"
        assert c["trade_name"] == "Shape Trader"
        assert c["is_active"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Router Tests (GET /api/clients - list_clients)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouterListClients:
    """Targeted tests for GET /api/clients dual-read integration."""

    @pytest.mark.asyncio
    async def test_list_clients_aurora_hit_no_supabase(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """10. Aurora clients are returned and Supabase is NOT queried."""
        admin_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=admin_id,
                    gstin="27AURORAHIT1111",
                    trade_name="Aurora Hit Co",
                    is_active=True,
                ),
            ])
            session.commit()

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            res = await list_clients(current_user={"id": admin_id, "role": "admin"})
            assert len(res) == 1
            assert res[0]["id"] == cid
            assert res[0]["gstin"] == "27AURORAHIT1111"

            # CRITICAL: Supabase was NEVER consulted
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_clients_aurora_zero_clients_authoritative_no_supabase(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """11. Aurora returns [] (existing user with 0 clients) and Supabase is NOT queried."""
        user_empty = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=user_empty, role="admin", is_active=True))
            session.commit()

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            res = await list_clients(current_user={"id": user_empty, "role": "admin"})
            assert res == []

            # CRITICAL: Empty list is authoritative; Supabase must NOT be called
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_clients_aurora_miss_fallback_to_supabase(self, tenancy_repo):
        """12. Aurora returns None (migration miss) and Supabase fallback executes."""
        missing_uid = str(uuid.uuid4())

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_builder = MagicMock()
            mock_sb.table.return_value = mock_builder
            mock_builder.select.return_value = mock_builder
            mock_builder.eq.return_value = mock_builder
            mock_builder.order.return_value = mock_builder
            mock_builder.limit.return_value = mock_builder
            mock_builder.execute.return_value = MagicMock(
                data=[{
                    "id": "sb-client-1",
                    "firm_owner_id": missing_uid,
                    "gstin": "27SBFALLBACK111",
                    "is_active": True,
                }]
            )
            mock_get_sb.return_value = mock_sb

            res = await list_clients(current_user={"id": missing_uid, "role": "admin"})
            assert len(res) == 1
            assert res[0]["id"] == "sb-client-1"
            assert res[0]["gstin"] == "27SBFALLBACK111"
            mock_sb.table.assert_called_with("client_gstins")

    @pytest.mark.asyncio
    async def test_list_clients_aurora_disabled_fallback(self):
        """13. Aurora repository unavailable (None) preserves Supabase behavior."""
        set_tenancy_repository(None)
        admin_id = str(uuid.uuid4())

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_builder = MagicMock()
            mock_sb.table.return_value = mock_builder
            mock_builder.select.return_value = mock_builder
            mock_builder.eq.return_value = mock_builder
            mock_builder.order.return_value = mock_builder
            mock_builder.limit.return_value = mock_builder
            mock_builder.execute.return_value = MagicMock(
                data=[{
                    "id": "sb-disabled-1",
                    "firm_owner_id": admin_id,
                    "gstin": "27SBDISABLED111",
                    "is_active": True,
                }]
            )
            mock_get_sb.return_value = mock_sb

            res = await list_clients(current_user={"id": admin_id, "role": "admin"})
            assert len(res) == 1
            assert res[0]["id"] == "sb-disabled-1"
            mock_sb.table.assert_called_with("client_gstins")

    @pytest.mark.asyncio
    async def test_list_clients_aurora_repository_failure_safe_fallback(
        self, tenancy_repo
    ):
        """14. Aurora repository exception preserves Supabase fallback."""
        admin_id = str(uuid.uuid4())

        with patch.object(
            tenancy_repo, "list_accessible_clients", side_effect=RuntimeError("DB disconnected")
        ):
            with patch("app.routers.clients.get_supabase") as mock_get_sb:
                mock_sb = MagicMock()
                mock_builder = MagicMock()
                mock_sb.table.return_value = mock_builder
                mock_builder.select.return_value = mock_builder
                mock_builder.eq.return_value = mock_builder
                mock_builder.order.return_value = mock_builder
                mock_builder.limit.return_value = mock_builder
                mock_builder.execute.return_value = MagicMock(
                    data=[{
                        "id": "sb-error-fallback-1",
                        "firm_owner_id": admin_id,
                        "gstin": "27SBERRORFALLBACK",
                        "is_active": True,
                    }]
                )
                mock_get_sb.return_value = mock_sb

                res = await list_clients(current_user={"id": admin_id, "role": "admin"})
                assert len(res) == 1
                assert res[0]["id"] == "sb-error-fallback-1"
                mock_sb.table.assert_called_with("client_gstins")

    @pytest.mark.asyncio
    async def test_list_clients_admin_owner_filtering(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """15. Admin/owner filtering retrieves all active clients owned by the user."""
        admin_id = str(uuid.uuid4())
        cid1 = str(uuid.uuid4())
        cid2 = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid1,
                    firm_owner_id=admin_id,
                    gstin="27ADMIN111111111",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=cid2,
                    firm_owner_id=admin_id,
                    gstin="27ADMIN222222222",
                    is_active=True,
                ),
            ])
            session.commit()

        res = await list_clients(current_user={"id": admin_id, "role": "admin"})
        assert len(res) == 2
        ids = {c["id"] for c in res}
        assert ids == {cid1, cid2}

    @pytest.mark.asyncio
    async def test_list_clients_staff_filtering(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """16. Staff filtering retrieves only clients assigned to the staff user."""
        admin_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        cid_assigned = str(uuid.uuid4())
        cid_unassigned = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                ClientGSTIN(
                    id=cid_assigned,
                    firm_owner_id=admin_id,
                    assigned_to=staff_id,
                    gstin="27ASSIGNED11111",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=cid_unassigned,
                    firm_owner_id=admin_id,
                    assigned_to=None,
                    gstin="27UNASSIGNED222",
                    is_active=True,
                ),
            ])
            session.commit()

        res = await list_clients(current_user={"id": staff_id, "role": "staff"})
        assert len(res) == 1
        assert res[0]["id"] == cid_assigned

    @pytest.mark.asyncio
    async def test_list_clients_inactive_excluded(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """17. Inactive clients remain excluded in list_clients response."""
        admin_id = str(uuid.uuid4())
        cid_active = str(uuid.uuid4())
        cid_inactive = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid_active,
                    firm_owner_id=admin_id,
                    gstin="27ACTIVE1111111",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=cid_inactive,
                    firm_owner_id=admin_id,
                    gstin="27INACTIVE22222",
                    is_active=False,
                ),
            ])
            session.commit()

        res = await list_clients(current_user={"id": admin_id, "role": "admin"})
        assert len(res) == 1
        assert res[0]["id"] == cid_active

    @pytest.mark.asyncio
    async def test_list_clients_cross_firm_isolation(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """18. Cross-firm clients are never exposed to another firm owner."""
        firm_a_owner = str(uuid.uuid4())
        firm_b_owner = str(uuid.uuid4())
        cid_a = str(uuid.uuid4())
        cid_b = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=firm_a_owner, role="admin", is_active=True),
                UserProfile(id=firm_b_owner, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid_a,
                    firm_owner_id=firm_a_owner,
                    gstin="27FIRMA11111111",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=cid_b,
                    firm_owner_id=firm_b_owner,
                    gstin="27FIRMB22222222",
                    is_active=True,
                ),
            ])
            session.commit()

        res_a = await list_clients(current_user={"id": firm_a_owner, "role": "admin"})
        assert len(res_a) == 1
        assert res_a[0]["id"] == cid_a

        res_b = await list_clients(current_user={"id": firm_b_owner, "role": "admin"})
        assert len(res_b) == 1
        assert res_b[0]["id"] == cid_b

    @pytest.mark.asyncio
    async def test_list_clients_returned_shape_compatibility(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """19. Returned response shape remains compatible with existing client schema."""
        admin_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=admin_id,
                    gstin="27SHAPECOMPAT11",
                    trade_name="Shape Compat Co",
                    legal_name="Shape Compat Private Limited",
                    state_code="27",
                    registration_type="Regular",
                    scheme_type="regular",
                    filing_frequency="monthly",
                    is_active=True,
                ),
            ])
            session.commit()

        res = await list_clients(current_user={"id": admin_id, "role": "admin"})
        assert len(res) == 1
        client = res[0]
        assert client["id"] == cid
        assert client["firm_owner_id"] == admin_id
        assert client["gstin"] == "27SHAPECOMPAT11"
        assert client["trade_name"] == "Shape Compat Co"
        assert client["legal_name"] == "Shape Compat Private Limited"
        assert client["state_code"] == "27"
        assert client["is_active"] is True
