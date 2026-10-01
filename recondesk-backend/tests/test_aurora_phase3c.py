"""Tests for ReconDesk Dual-Auth / AWS Aurora Migration — Phase 3C.

Covers:
1. Tenancy Helper Convergence:
   - _resolve_firm_owner dual-read (Aurora hit no Supabase query, Aurora miss fallback).
   - resolve_firm_id and _staff_firm_owner_id dual-read.
   - _is_invited_user and resolve_user_role dual-read.
2. Single-Client Read Dual-Read (GET /api/clients/{client_id}):
   - Aurora client + firm owner -> success with Aurora data (no Supabase query).
   - Aurora client + assigned staff -> success with Aurora data (no Supabase query).
   - Aurora client + different firm -> hard HTTP 403 (no Supabase query).
   - Aurora client + unassigned staff -> hard HTTP 403 (no Supabase query).
   - Aurora authorization denial never falls back to Supabase.
   - Aurora client missing -> safe Supabase fallback.
   - Aurora disabled -> existing Supabase behavior.
   - Aurora repository failure -> safe Supabase fallback.
   - Response shape matches existing client schema.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import _is_invited_user, resolve_user_role
from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, TeamMember, UserProfile
from app.repositories.tenancy import (
    AuroraTenancyRepository,
    get_tenancy_repository,
    set_tenancy_repository,
)
from app.routers.clients import _resolve_firm_owner, get_client
from app.utils.audit import _staff_firm_owner_id, resolve_firm_id


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
# 1. Helper Convergence Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestHelperConvergence:
    """Verify Aurora dual-read in helper functions across clients.py, audit.py, database.py."""

    def test_resolve_firm_owner_aurora_hit_no_supabase(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """Aurora contains the user and firm anchor -> returns owner without querying Supabase."""
        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                TeamMember(
                    firm_owner_id=owner_id,
                    member_user_id=staff_id,
                    role="staff",
                    is_active=True,
                ),
            ])
            session.commit()

        mock_sb = MagicMock()
        resolved = _resolve_firm_owner(mock_sb, staff_id)
        assert resolved == owner_id
        # Supabase must NOT be called on Aurora hit
        mock_sb.table.assert_not_called()

    def test_resolve_firm_owner_aurora_miss_fallback(self, tenancy_repo):
        """User missing from Aurora -> falls back to Supabase logic."""
        uid = str(uuid.uuid4())
        mock_sb = MagicMock()
        mock_tm = MagicMock()
        mock_tm.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"firm_owner_id": "sb-firm-owner-999"}
        ]
        mock_sb.table.side_effect = lambda table: mock_tm if table == "team_members" else MagicMock()

        resolved = _resolve_firm_owner(mock_sb, uid, role="staff")
        assert resolved == "sb-firm-owner-999"
        mock_sb.table.assert_called_with("team_members")

    def test_resolve_firm_id_aurora_hit(self, tenancy_sqlite_engine, tenancy_repo):
        """resolve_firm_id derives firm owner from Aurora without querying Supabase."""
        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                TeamMember(
                    firm_owner_id=owner_id,
                    member_user_id=staff_id,
                    role="staff",
                    is_active=True,
                ),
            ])
            session.commit()

        mock_sb = MagicMock()
        # Test with dict
        res = resolve_firm_id(mock_sb, {"id": staff_id, "role": "staff"})
        assert res == owner_id
        mock_sb.table.assert_not_called()

        # Test with raw string user_id
        res_str = resolve_firm_id(mock_sb, staff_id)
        assert res_str == owner_id
        mock_sb.table.assert_not_called()

    def test_staff_firm_owner_id_aurora_hit(self, tenancy_sqlite_engine, tenancy_repo):
        """_staff_firm_owner_id uses Aurora repo when available."""
        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                TeamMember(
                    firm_owner_id=owner_id,
                    member_user_id=staff_id,
                    role="staff",
                    is_active=True,
                ),
            ])
            session.commit()

        mock_sb = MagicMock()
        res = _staff_firm_owner_id(mock_sb, staff_id)
        assert res == owner_id
        mock_sb.table.assert_not_called()

    def test_is_invited_user_aurora_membership(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """_is_invited_user returns True when user has active membership in Aurora."""
        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                TeamMember(
                    firm_owner_id=owner_id,
                    member_user_id=staff_id,
                    role="staff",
                    is_active=True,
                ),
            ])
            session.commit()

        mock_sb = MagicMock()
        is_invited = _is_invited_user(mock_sb, user_id=staff_id, email=None)
        assert is_invited is True
        mock_sb.table.assert_not_called()

    def test_resolve_user_role_aurora(self, tenancy_sqlite_engine, tenancy_repo):
        """resolve_user_role returns the canonical role from Aurora user profile."""
        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="owner", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
            ])
            session.commit()

        mock_sb = MagicMock()
        owner_role = resolve_user_role(None, user_id=owner_id, email=None, client=mock_sb)
        assert owner_role == "owner"

        staff_role = resolve_user_role(None, user_id=staff_id, email=None, client=mock_sb)
        assert staff_role == "staff"

        mock_sb.table.assert_not_called()

    def test_helpers_aurora_miss_preserves_supabase(self, tenancy_repo):
        """When user is absent from Aurora, all helpers fall back to Supabase."""
        uid = str(uuid.uuid4())
        mock_sb = MagicMock()

        # Mock team_members for _is_invited_user and _staff_firm_owner_id
        mock_tm = MagicMock()
        mock_tm.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "tm-1", "firm_owner_id": "sb-owner"}
        ]
        mock_tm.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "tm-1", "firm_owner_id": "sb-owner"}
        ]
        mock_sb.table.return_value = mock_tm

        # 1. _is_invited_user
        assert _is_invited_user(mock_sb, user_id=uid, email=None) is True
        mock_sb.table.assert_called_with("team_members")

        # 2. resolve_user_role
        role = resolve_user_role(None, user_id=uid, email=None, client=mock_sb)
        assert role == "staff"

        # 3. _staff_firm_owner_id
        owner = _staff_firm_owner_id(mock_sb, uid)
        assert owner == "sb-owner"

        # 4. resolve_firm_id
        fid = resolve_firm_id(mock_sb, {"id": uid, "role": "staff"})
        assert fid == "sb-owner"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Single-Client Read Dual-Read Tests (GET /api/clients/{client_id})
# ═══════════════════════════════════════════════════════════════════════════════


class TestSingleClientReadDualRead:
    """Targeted tests for get_client dual-read and hard denial rules."""

    @pytest.mark.asyncio
    async def test_get_client_aurora_firm_owner_success(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """1. Aurora client + firm owner -> success with Aurora data (no Supabase query)."""
        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=owner_id,
                    gstin="27TESTOWNER1111",
                    trade_name="Owner Trade Co",
                    legal_name="Owner Legal Pvt Ltd",
                    is_active=True,
                ),
            ])
            session.commit()

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            res = await get_client(
                client_id=cid,
                current_user={"id": owner_id, "role": "admin"},
            )

            assert res["id"] == cid
            assert res["gstin"] == "27TESTOWNER1111"
            assert res["trade_name"] == "Owner Trade Co"
            assert res["firm_owner_id"] == owner_id
            # Proves Supabase was NEVER queried!
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_aurora_assigned_staff_success(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """2. Aurora client + assigned staff -> success with Aurora data (no Supabase query)."""
        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                UserProfile(id=staff_id, role="staff", is_active=True),
                TeamMember(
                    firm_owner_id=owner_id,
                    member_user_id=staff_id,
                    role="staff",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=owner_id,
                    assigned_to=staff_id,
                    gstin="27TESTSTAFF1111",
                    trade_name="Staff Assigned Trade",
                    is_active=True,
                ),
            ])
            session.commit()

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            res = await get_client(
                client_id=cid,
                current_user={"id": staff_id, "role": "staff"},
            )

            assert res["id"] == cid
            assert res["gstin"] == "27TESTSTAFF1111"
            assert res["assigned_to"] == staff_id
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_aurora_different_firm_hard_403(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """3. Aurora client + different firm -> HARD HTTP 403 (no Supabase query)."""
        firm_a_owner = str(uuid.uuid4())
        firm_b_owner = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=firm_a_owner, role="admin", is_active=True),
                UserProfile(id=firm_b_owner, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=firm_a_owner,
                    gstin="27TESTDIFF11111",
                    is_active=True,
                ),
            ])
            session.commit()

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            # Firm B owner attempts to read Firm A's client
            with pytest.raises(HTTPException) as exc_info:
                await get_client(
                    client_id=cid,
                    current_user={"id": firm_b_owner, "role": "admin"},
                )

            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == "not allowed"
            # Critical: Supabase is NOT consulted after authorization denial!
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_aurora_unassigned_staff_hard_403(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """4. Aurora client + unassigned staff -> HARD HTTP 403 (no Supabase query)."""
        owner_id = str(uuid.uuid4())
        assigned_staff_id = str(uuid.uuid4())
        unassigned_staff_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                UserProfile(id=assigned_staff_id, role="staff", is_active=True),
                UserProfile(id=unassigned_staff_id, role="staff", is_active=True),
                TeamMember(
                    firm_owner_id=owner_id,
                    member_user_id=assigned_staff_id,
                    role="staff",
                    is_active=True,
                ),
                TeamMember(
                    firm_owner_id=owner_id,
                    member_user_id=unassigned_staff_id,
                    role="staff",
                    is_active=True,
                ),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=owner_id,
                    assigned_to=assigned_staff_id,
                    gstin="27UNASSIGNED111",
                    is_active=True,
                ),
            ])
            session.commit()

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            with pytest.raises(HTTPException) as exc_info:
                await get_client(
                    client_id=cid,
                    current_user={"id": unassigned_staff_id, "role": "staff"},
                )

            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == "not allowed"
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_aurora_inactive_client_hard_403(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """5. Inactive client in Aurora -> HARD HTTP 403 Access denied (no Supabase query)."""
        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=owner_id,
                    gstin="27INACTIVE11111",
                    is_active=False,  # Inactive / soft-deleted
                ),
            ])
            session.commit()

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            with pytest.raises(HTTPException) as exc_info:
                await get_client(
                    client_id=cid,
                    current_user={"id": owner_id, "role": "admin"},
                )

            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == "Access denied"
            mock_get_sb.assert_not_called()
            mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_aurora_miss_fallback_to_supabase(self, tenancy_repo):
        """6. Aurora client missing -> Supabase fallback executed."""
        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_builder = MagicMock()
            mock_sb.table.return_value = mock_builder
            mock_builder.select.return_value = mock_builder
            mock_builder.eq.return_value = mock_builder
            mock_builder.limit.return_value = mock_builder
            mock_builder.execute.return_value = MagicMock(
                data=[{
                    "id": cid,
                    "firm_owner_id": owner_id,
                    "gstin": "27FALLBACK11111",
                    "is_active": True,
                }]
            )
            mock_get_sb.return_value = mock_sb

            res = await get_client(
                client_id=cid,
                current_user={"id": owner_id, "role": "admin"},
            )

            assert res["id"] == cid
            assert res["gstin"] == "27FALLBACK11111"
            mock_sb.table.assert_called_with("client_gstins")

    @pytest.mark.asyncio
    async def test_get_client_aurora_disabled_fallback(self):
        """7. Aurora disabled (repository is None) -> Supabase continues working."""
        set_tenancy_repository(None)
        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with patch("app.routers.clients.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_builder = MagicMock()
            mock_sb.table.return_value = mock_builder
            mock_builder.select.return_value = mock_builder
            mock_builder.eq.return_value = mock_builder
            mock_builder.limit.return_value = mock_builder
            mock_builder.execute.return_value = MagicMock(
                data=[{
                    "id": cid,
                    "firm_owner_id": owner_id,
                    "gstin": "27DISABLED11111",
                    "is_active": True,
                }]
            )
            mock_get_sb.return_value = mock_sb

            res = await get_client(
                client_id=cid,
                current_user={"id": owner_id, "role": "admin"},
            )

            assert res["id"] == cid
            assert res["gstin"] == "27DISABLED11111"
            mock_sb.table.assert_called_with("client_gstins")

    @pytest.mark.asyncio
    async def test_get_client_aurora_repository_failure_safe_fallback(
        self, tenancy_repo
    ):
        """8. Aurora repository exception -> safe fallback to Supabase."""
        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        # Simulate database error on get_client_gstin
        with patch.object(
            tenancy_repo, "get_client_gstin", side_effect=RuntimeError("DB disconnected")
        ):
            with patch("app.routers.clients.get_supabase") as mock_get_sb:
                mock_sb = MagicMock()
                mock_builder = MagicMock()
                mock_sb.table.return_value = mock_builder
                mock_builder.select.return_value = mock_builder
                mock_builder.eq.return_value = mock_builder
                mock_builder.limit.return_value = mock_builder
                mock_builder.execute.return_value = MagicMock(
                    data=[{
                        "id": cid,
                        "firm_owner_id": owner_id,
                        "gstin": "27SAFEFAIL11111",
                        "is_active": True,
                    }]
                )
                mock_get_sb.return_value = mock_sb

                res = await get_client(
                    client_id=cid,
                    current_user={"id": owner_id, "role": "admin"},
                )

                assert res["id"] == cid
                assert res["gstin"] == "27SAFEFAIL11111"
                mock_sb.table.assert_called_with("client_gstins")

    @pytest.mark.asyncio
    async def test_get_client_aurora_response_shape_preserved(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """9. Returned Aurora data preserves all expected fields of the API response shape."""
        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, role="admin", is_active=True),
                ClientGSTIN(
                    id=cid,
                    firm_owner_id=owner_id,
                    gstin="27SHAPETEST1111",
                    trade_name="Shape Test Trader",
                    legal_name="Shape Test Private Limited",
                    state_code="27",
                    registration_type="Regular",
                    scheme_type="regular",
                    filing_frequency="monthly",
                    contact_name="Ramesh Kumar",
                    contact_email="ramesh@shapetest.in",
                    contact_phone="+919876543210",
                    is_active=True,
                    is_demo=False,
                ),
            ])
            session.commit()

        res = await get_client(
            client_id=cid,
            current_user={"id": owner_id, "role": "admin"},
        )

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
            assert field in res, f"Expected field '{field}' missing from Aurora response"

        assert res["id"] == cid
        assert res["firm_owner_id"] == owner_id
        assert res["gstin"] == "27SHAPETEST1111"
        assert res["trade_name"] == "Shape Test Trader"
        assert res["legal_name"] == "Shape Test Private Limited"
        assert res["state_code"] == "27"
        assert res["contact_name"] == "Ramesh Kumar"
        assert res["is_active"] is True
