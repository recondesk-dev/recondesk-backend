"""Tests for AWS Aurora Tenancy Layer (Phase 3B).

Covers:
1. Tenancy Schema and SQLAlchemy Models (UserProfile, TeamMember, ClientGSTIN).
2. AuroraTenancyRepository operations (profiles, roles, active checks, firm scoping, client access).
3. Aurora Session Authorization Context Helpers (SET LOCAL transaction context, session isolation).
4. Dual-Read and Supabase Fallback in database.py and firm_access.py.
5. Critical Security Invariant: Authorization denials in Aurora NEVER fall through to Supabase.
6. Identity Separation: Cognito sub != canonical ReconDesk user_profiles.id.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    clear_aurora_session_context,
    get_aurora_session_context,
    set_aurora_session_context,
)
from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, TeamMember, UserProfile
from app.repositories.tenancy import (
    AuroraTenancyRepository,
    get_tenancy_repository,
    set_tenancy_repository,
)


@pytest.fixture
def tenancy_sqlite_engine():
    """Create a temporary SQLite engine with all tenancy tables."""
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
# 1. Tenancy Schema and SQLAlchemy Models
# ═══════════════════════════════════════════════════════════════════════════════


class TestTenancySchemaAndModels:
    """Verify SQLAlchemy declarative models, mappings, constraints, and .to_dict() helpers."""

    def test_user_profile_model_properties_and_to_dict(self, tenancy_sqlite_engine):
        uid = str(uuid.uuid4())
        session = Session(tenancy_sqlite_engine)
        profile = UserProfile(
            id=uid,
            email="ca.owner@firm.example",
            full_name="CA Owner",
            firm_name="Owner Firm & Co",
            role="owner",
            is_active=True,
            plan="enterprise",
        )
        session.add(profile)
        session.commit()

        loaded = session.scalar(select(UserProfile).where(UserProfile.id == uid))
        assert loaded is not None
        assert loaded.id == uid
        assert loaded.email == "ca.owner@firm.example"
        assert loaded.full_name == "CA Owner"
        assert loaded.firm_name == "Owner Firm & Co"
        assert loaded.role == "owner"
        assert loaded.is_active is True
        assert loaded.plan == "enterprise"

        as_dict = loaded.to_dict()
        assert as_dict["id"] == uid
        assert as_dict["email"] == "ca.owner@firm.example"
        assert as_dict["role"] == "owner"
        assert as_dict["plan"] == "enterprise"
        session.close()

    def test_team_member_model_properties_and_to_dict(self, tenancy_sqlite_engine):
        owner_id = str(uuid.uuid4())
        member_id = str(uuid.uuid4())
        tm_id = str(uuid.uuid4())

        session = Session(tenancy_sqlite_engine)
        owner = UserProfile(id=owner_id, email="owner@firm.com", role="admin")
        member = UserProfile(id=member_id, email="staff@firm.com", role="staff")
        tm = TeamMember(
            id=tm_id,
            firm_owner_id=owner_id,
            member_user_id=member_id,
            role="staff",
            is_active=True,
        )
        session.add_all([owner, member, tm])
        session.commit()

        loaded_tm = session.scalar(select(TeamMember).where(TeamMember.id == tm_id))
        assert loaded_tm is not None
        assert loaded_tm.firm_owner_id == owner_id
        assert loaded_tm.member_user_id == member_id
        assert loaded_tm.role == "staff"
        assert loaded_tm.is_active is True

        d = loaded_tm.to_dict()
        assert d["id"] == tm_id
        assert d["firm_owner_id"] == owner_id
        assert d["member_user_id"] == member_id
        session.close()

    def test_client_gstin_model_properties_and_to_dict(self, tenancy_sqlite_engine):
        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        session = Session(tenancy_sqlite_engine)
        owner = UserProfile(id=owner_id, email="owner@firm.com", role="admin")
        staff = UserProfile(id=staff_id, email="staff@firm.com", role="staff")
        client = ClientGSTIN(
            id=client_id,
            firm_owner_id=owner_id,
            gstin="27ABCDE1234F1Z5",
            trade_name="Acme Corp",
            legal_name="Acme Corporation Ltd",
            assigned_to=staff_id,
            is_active=True,
        )
        session.add_all([owner, staff, client])
        session.commit()

        loaded_c = session.scalar(select(ClientGSTIN).where(ClientGSTIN.id == client_id))
        assert loaded_c is not None
        assert loaded_c.firm_owner_id == owner_id
        assert loaded_c.gstin == "27ABCDE1234F1Z5"
        assert loaded_c.trade_name == "Acme Corp"
        assert loaded_c.legal_name == "Acme Corporation Ltd"
        assert loaded_c.assigned_to == staff_id
        assert loaded_c.is_active is True

        cd = loaded_c.to_dict()
        assert cd["id"] == client_id
        assert cd["firm_owner_id"] == owner_id
        assert cd["gstin"] == "27ABCDE1234F1Z5"
        assert cd["trade_name"] == "Acme Corp"
        session.close()

    def test_ddl_migration_files_exist_and_match(self):
        """Verify the Aurora migration files exist and contain valid PostgreSQL DDL statements."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        up_path = os.path.join(
            base_dir, "migrations", "aurora", "20260930183000_create_tenancy_tables.up.sql"
        )
        down_path = os.path.join(
            base_dir, "migrations", "aurora", "20260930183000_create_tenancy_tables.down.sql"
        )
        assert os.path.exists(up_path), f"Missing up migration: {up_path}"
        assert os.path.exists(down_path), f"Missing down migration: {down_path}"

        with open(up_path, "r", encoding="utf-8") as f:
            up_content = f.read()

        assert "CREATE TABLE IF NOT EXISTS public.user_profiles" in up_content
        assert "CREATE TABLE IF NOT EXISTS public.team_members" in up_content
        assert "CREATE TABLE IF NOT EXISTS public.client_gstins" in up_content
        assert "uq_client_gstins_firm_gstin" in up_content
        assert "idx_client_gstins_firm_owner_id" in up_content
        assert "idx_client_gstins_assigned_to" in up_content

        with open(down_path, "r", encoding="utf-8") as f:
            down_content = f.read()

        assert "DROP TABLE IF EXISTS public.client_gstins" in down_content
        assert "DROP TABLE IF EXISTS public.team_members" in down_content
        assert "DROP TABLE IF EXISTS public.user_profiles" in down_content


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Aurora Tenancy Repository Operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuroraTenancyRepositoryOperations:
    """Verify repository methods against an SQLite test session."""

    def test_get_user_profile_lookup(self, tenancy_sqlite_engine, tenancy_repo):
        uid = str(uuid.uuid4())
        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=uid, email="test@firm.com", role="owner", is_active=True))
            session.commit()

        prof = tenancy_repo.get_user_profile(uid)
        assert prof is not None
        assert prof["id"] == uid
        assert prof["email"] == "test@firm.com"

        assert tenancy_repo.get_user_profile("nonexistent-uid") is None

    def test_is_user_active_tri_state(self, tenancy_sqlite_engine, tenancy_repo):
        active_id = str(uuid.uuid4())
        inactive_id = str(uuid.uuid4())
        absent_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=active_id, email="act@firm.com", is_active=True),
                UserProfile(id=inactive_id, email="inact@firm.com", is_active=False),
            ])
            session.commit()

        assert tenancy_repo.is_user_active(active_id) is True
        assert tenancy_repo.is_user_active(inactive_id) is False
        assert tenancy_repo.is_user_active(absent_id) is None

    def test_get_user_role(self, tenancy_sqlite_engine, tenancy_repo):
        admin_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        absent_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=admin_id, email="admin@firm.com", role="admin"),
                UserProfile(id=staff_id, email="staff@firm.com", role="staff"),
            ])
            session.commit()

        assert tenancy_repo.get_user_role(admin_id) == "admin"
        assert tenancy_repo.get_user_role(staff_id) == "staff"
        assert tenancy_repo.get_user_role(absent_id) is None

    def test_is_firm_owner(self, tenancy_sqlite_engine, tenancy_repo):
        owner_id = str(uuid.uuid4())
        client_owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="owner"),
                UserProfile(id=client_owner_id, email="clientowner@firm.com", role="staff"),
                UserProfile(id=staff_id, email="staff@firm.com", role="staff"),
                ClientGSTIN(id=cid, firm_owner_id=client_owner_id, gstin="27CLIENTOWNER1", is_active=True),
            ])
            session.commit()

        assert tenancy_repo.is_firm_owner(owner_id) is True
        assert tenancy_repo.is_firm_owner(client_owner_id) is True  # owns clients
        assert tenancy_repo.is_firm_owner(staff_id) is False

    def test_get_firm_owner_id_for_user(self, tenancy_sqlite_engine, tenancy_repo):
        owner_id = str(uuid.uuid4())
        staff_tm_id = str(uuid.uuid4())
        staff_assigned_id = str(uuid.uuid4())
        unlinked_id = str(uuid.uuid4())
        tm_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                UserProfile(id=staff_tm_id, email="tm@firm.com", role="staff"),
                UserProfile(id=staff_assigned_id, email="ass@firm.com", role="staff"),
                UserProfile(id=unlinked_id, email="unlinked@firm.com", role="staff"),
                TeamMember(id=tm_id, firm_owner_id=owner_id, member_user_id=staff_tm_id, is_active=True),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27TEST111111111", assigned_to=staff_assigned_id, is_active=True),
            ])
            session.commit()

        assert tenancy_repo.get_firm_owner_id_for_user(owner_id) == owner_id
        assert tenancy_repo.get_firm_owner_id_for_user(staff_tm_id) == owner_id
        assert tenancy_repo.get_firm_owner_id_for_user(staff_assigned_id) == owner_id
        assert tenancy_repo.get_firm_owner_id_for_user(unlinked_id) is None

    def test_list_accessible_client_gstin_ids(self, tenancy_sqlite_engine, tenancy_repo):
        owner_id = str(uuid.uuid4())
        staff1_id = str(uuid.uuid4())
        staff2_id = str(uuid.uuid4())
        zero_clients_user_id = str(uuid.uuid4())
        absent_user_id = str(uuid.uuid4())
        c1 = str(uuid.uuid4())
        c2 = str(uuid.uuid4())
        c_inactive = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                UserProfile(id=staff1_id, email="staff1@firm.com", role="staff"),
                UserProfile(id=staff2_id, email="staff2@firm.com", role="staff"),
                UserProfile(id=zero_clients_user_id, email="zero@firm.com", role="admin"),
                ClientGSTIN(id=c1, firm_owner_id=owner_id, gstin="27AAAAA1111A1Z1", assigned_to=staff1_id, is_active=True),
                ClientGSTIN(id=c2, firm_owner_id=owner_id, gstin="27BBBBB2222B1Z2", assigned_to=staff2_id, is_active=True),
                ClientGSTIN(id=c_inactive, firm_owner_id=owner_id, gstin="27CCCCC3333C1Z3", assigned_to=staff1_id, is_active=False),
            ])
            session.commit()

        # Admin sees all active clients in firm
        admin_clients = tenancy_repo.list_accessible_client_gstin_ids(owner_id, role="admin")
        assert admin_clients == {c1, c2}
        assert c_inactive not in admin_clients

        # Staff1 sees only c1
        staff1_clients = tenancy_repo.list_accessible_client_gstin_ids(staff1_id, role="staff")
        assert staff1_clients == {c1}

        # Staff2 sees only c2
        staff2_clients = tenancy_repo.list_accessible_client_gstin_ids(staff2_id, role="staff")
        assert staff2_clients == {c2}

        # User in Aurora with zero accessible clients -> returns set() (NOT None)
        zero_clients = tenancy_repo.list_accessible_client_gstin_ids(zero_clients_user_id, role="admin")
        assert zero_clients == set()
        assert zero_clients is not None

        # User absent from Aurora -> returns None (permits Supabase fallback)
        absent_clients = tenancy_repo.list_accessible_client_gstin_ids(absent_user_id, role="admin")
        assert absent_clients is None

    def test_verify_firm_ownership_tri_state(self, tenancy_sqlite_engine, tenancy_repo):
        firm_a_owner = str(uuid.uuid4())
        firm_b_owner = str(uuid.uuid4())
        c_id = str(uuid.uuid4())
        absent_c_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=firm_a_owner, email="a@firm.com", role="admin"),
                UserProfile(id=firm_b_owner, email="b@firm.com", role="admin"),
                ClientGSTIN(id=c_id, firm_owner_id=firm_a_owner, gstin="27OWNERTEST111", is_active=True),
            ])
            session.commit()

        # Matches owner: True
        assert tenancy_repo.verify_firm_ownership(c_id, firm_a_owner) is True
        # Belongs to another firm: False (DENIAL)
        assert tenancy_repo.verify_firm_ownership(c_id, firm_b_owner) is False
        # Client absent: None (INFRASTRUCTURE MISS)
        assert tenancy_repo.verify_firm_ownership(absent_c_id, firm_a_owner) is None

    def test_verify_staff_assignment_tri_state(self, tenancy_sqlite_engine, tenancy_repo):
        owner_id = str(uuid.uuid4())
        staff_a = str(uuid.uuid4())
        staff_b = str(uuid.uuid4())
        c_active = str(uuid.uuid4())
        c_inactive = str(uuid.uuid4())
        absent_c = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                UserProfile(id=staff_a, email="a@firm.com", role="staff"),
                UserProfile(id=staff_b, email="b@firm.com", role="staff"),
                ClientGSTIN(id=c_active, firm_owner_id=owner_id, gstin="27ACTIVE111111", assigned_to=staff_a, is_active=True),
                ClientGSTIN(id=c_inactive, firm_owner_id=owner_id, gstin="27INACTIVE1111", assigned_to=staff_a, is_active=False),
            ])
            session.commit()

        # Assigned and active: True
        assert tenancy_repo.verify_staff_assignment(c_active, staff_a) is True
        # Assigned but different staff: False (DENIAL)
        assert tenancy_repo.verify_staff_assignment(c_active, staff_b) is False
        # Assigned but client inactive: False (DENIAL)
        assert tenancy_repo.verify_staff_assignment(c_inactive, staff_a) is False
        # Client absent in Aurora: None (INFRASTRUCTURE MISS)
        assert tenancy_repo.verify_staff_assignment(absent_c, staff_a) is None

    def test_get_team_membership(self, tenancy_sqlite_engine, tenancy_repo):
        owner_id = str(uuid.uuid4())
        staff_active = str(uuid.uuid4())
        staff_inactive = str(uuid.uuid4())
        absent_staff = str(uuid.uuid4())
        tm1 = str(uuid.uuid4())
        tm2 = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                UserProfile(id=staff_active, email="s1@firm.com", role="staff"),
                UserProfile(id=staff_inactive, email="s2@firm.com", role="staff"),
                TeamMember(id=tm1, firm_owner_id=owner_id, member_user_id=staff_active, is_active=True),
                TeamMember(id=tm2, firm_owner_id=owner_id, member_user_id=staff_inactive, is_active=False),
            ])
            session.commit()

        # Active team member returns dict
        active_mem = tenancy_repo.get_team_membership(staff_active)
        assert active_mem is not None
        assert active_mem["id"] == tm1
        assert active_mem["firm_owner_id"] == owner_id

        # Inactive team member returns None
        assert tenancy_repo.get_team_membership(staff_inactive) is None
        # Nonexistent returns None
        assert tenancy_repo.get_team_membership(absent_staff) is None

    def test_user_can_access_firm_repository(self, tenancy_sqlite_engine, tenancy_repo):
        owner_id = str(uuid.uuid4())
        staff_tm = str(uuid.uuid4())
        staff_client = str(uuid.uuid4())
        unrelated = str(uuid.uuid4())
        tm_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="o@firm.com", role="admin"),
                UserProfile(id=staff_tm, email="s_tm@firm.com", role="staff"),
                UserProfile(id=staff_client, email="s_cl@firm.com", role="staff"),
                UserProfile(id=unrelated, email="unrel@firm.com", role="staff"),
                TeamMember(id=tm_id, firm_owner_id=owner_id, member_user_id=staff_tm, is_active=True),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27ACCESSTEST11", assigned_to=staff_client, is_active=True),
            ])
            session.commit()

        # Owner has access
        assert tenancy_repo.user_can_access_firm(owner_id, owner_id) is True
        # Team member has access
        assert tenancy_repo.user_can_access_firm(staff_tm, owner_id) is True
        # Assigned staff has access
        assert tenancy_repo.user_can_access_firm(staff_client, owner_id) is True
        # Unrelated user returns None (allows Supabase fallback)
        assert tenancy_repo.user_can_access_firm(unrelated, owner_id) is None

    def test_user_in_same_firm_repository(self, tenancy_sqlite_engine, tenancy_repo):
        owner_id = str(uuid.uuid4())
        staff_assigned = str(uuid.uuid4())
        staff_unassigned = str(uuid.uuid4())
        other_firm_owner = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        absent_cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="o@firm.com", role="admin"),
                UserProfile(id=other_firm_owner, email="other@firm.com", role="admin"),
                UserProfile(id=staff_assigned, email="s_ass@firm.com", role="staff"),
                UserProfile(id=staff_unassigned, email="s_unass@firm.com", role="staff"),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27SAMEFIRM111", assigned_to=staff_assigned, is_active=True),
            ])
            session.commit()

        # Owner is always in same firm: True
        assert tenancy_repo.user_in_same_firm(owner_id, owner_id, cid) is True
        # Assigned staff: True
        assert tenancy_repo.user_in_same_firm(staff_assigned, owner_id, cid) is True
        # Unassigned staff for client in Aurora: False (DENIAL)
        assert tenancy_repo.user_in_same_firm(staff_unassigned, owner_id, cid) is False
        # Other firm owner querying Firm A's client: False (DENIAL)
        assert tenancy_repo.user_in_same_firm(other_firm_owner, other_firm_owner, cid) is False
        # Client not in Aurora: None (INFRASTRUCTURE MISS)
        assert tenancy_repo.user_in_same_firm(staff_assigned, owner_id, absent_cid) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Session Authorization Context Helpers (SET LOCAL)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuroraSessionContextHelper:
    """Verify session-scoped authorization context setting, retrieval, and isolation."""

    def test_set_and_get_session_context(self, tenancy_sqlite_engine):
        session = Session(tenancy_sqlite_engine)
        uid = str(uuid.uuid4())
        foid = str(uuid.uuid4())
        role = "staff"

        set_aurora_session_context(session, user_id=uid, firm_owner_id=foid, role=role)
        ctx = get_aurora_session_context(session)

        assert ctx["user_id"] == uid
        assert ctx["firm_owner_id"] == foid
        assert ctx["role"] == "staff"
        session.close()

    def test_clear_session_context(self, tenancy_sqlite_engine):
        session = Session(tenancy_sqlite_engine)
        uid = str(uuid.uuid4())
        set_aurora_session_context(session, user_id=uid, role="admin")

        ctx = get_aurora_session_context(session)
        assert ctx["user_id"] == uid

        clear_aurora_session_context(session)
        ctx_after = get_aurora_session_context(session)
        assert ctx_after["user_id"] is None
        assert ctx_after["role"] is None
        session.close()

    def test_session_isolation_no_leakage(self, tenancy_sqlite_engine):
        session1 = Session(tenancy_sqlite_engine)
        session2 = Session(tenancy_sqlite_engine)

        uid1 = str(uuid.uuid4())
        set_aurora_session_context(session1, user_id=uid1, role="admin")

        ctx1 = get_aurora_session_context(session1)
        ctx2 = get_aurora_session_context(session2)

        assert ctx1["user_id"] == uid1
        assert ctx2["user_id"] is None  # Session 2 has no context
        session1.close()
        session2.close()

    def test_postgresql_set_config_execution(self):
        """Verify that when dialect is postgresql, set_config and current_setting are invoked with bound params."""
        mock_session = MagicMock(spec=Session)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_session.get_bind.return_value = mock_bind
        mock_session.info = {}

        uid = str(uuid.uuid4())
        foid = str(uuid.uuid4())
        set_aurora_session_context(mock_session, user_id=uid, firm_owner_id=foid, role="admin")

        # Must execute text statements with true for is_local
        calls = mock_session.execute.call_args_list
        assert len(calls) == 3
        sql_texts = [str(call[0][0]) for call in calls]
        assert any("app.current_user_id" in s for s in sql_texts)
        assert any("app.current_firm_owner_id" in s for s in sql_texts)
        assert any("app.current_user_role" in s for s in sql_texts)

    def test_transaction_end_clears_context_between_transactions(self, tenancy_sqlite_engine):
        """Prove that transaction A sets user A, transaction A ends (commits or rolls back),
        and transaction B does not inherit user A.
        """
        session = Session(tenancy_sqlite_engine)
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())

        # Transaction A: execute query, set user A
        session.execute(text("SELECT 1"))
        set_aurora_session_context(session, user_id=user_a, role="admin")
        ctx_a = get_aurora_session_context(session)
        assert ctx_a["user_id"] == user_a

        # Transaction A ends (commit)
        session.commit()

        # Transaction B starts: does NOT inherit user A
        session.execute(text("SELECT 1"))
        ctx_b = get_aurora_session_context(session)
        assert ctx_b["user_id"] is None
        assert ctx_b["firm_owner_id"] is None
        assert ctx_b["role"] is None

        # Transaction B sets user B
        set_aurora_session_context(session, user_id=user_b, role="staff")
        assert get_aurora_session_context(session)["user_id"] == user_b

        # Transaction B ends (rollback)
        session.rollback()

        # Next transaction C: does NOT inherit user B
        session.execute(text("SELECT 1"))
        ctx_c = get_aurora_session_context(session)
        assert ctx_c["user_id"] is None
        session.close()

    def test_postgresql_transaction_context_not_leaked(self):
        """Prove that under PostgreSQL, committed or reset transactions return empty settings."""
        mock_session = MagicMock(spec=Session)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_session.get_bind.return_value = mock_bind
        mock_session.info = {}

        # Simulating ended transaction where PostgreSQL settings have been reset
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {
            "user_id": "",
            "firm_owner_id": "",
            "role": "",
        }
        mock_session.execute.return_value = mock_result

        ctx = get_aurora_session_context(mock_session)
        assert ctx["user_id"] is None
        assert ctx["firm_owner_id"] is None
        assert ctx["role"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Dual-Read and Supabase Fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestDualReadAndSupabaseFallback:
    """Verify dual-read semantics across database.py and firm_access.py."""

    def test_get_user_profile_aurora_precedence(self, tenancy_sqlite_engine, tenancy_repo):
        from app.database import get_user_profile

        uid = str(uuid.uuid4())
        with Session(tenancy_sqlite_engine) as session:
            session.add(UserProfile(id=uid, email="aurora.user@firm.com", role="owner", is_active=True))
            session.commit()

        with patch("app.database.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_get_sb.return_value = mock_sb

            profile = get_user_profile(uid)
            assert profile is not None
            assert profile["id"] == uid
            assert profile["email"] == "aurora.user@firm.com"
            # Supabase must NOT be called when record is found in Aurora!
            mock_sb.table.assert_not_called()

    def test_get_user_profile_supabase_fallback_on_miss(self, tenancy_repo):
        from app.database import get_user_profile

        uid = str(uuid.uuid4())
        # User does not exist in Aurora

        with patch("app.database.get_supabase") as mock_get_sb:
            mock_sb = MagicMock()
            mock_builder = MagicMock()
            mock_sb.table.return_value = mock_builder
            mock_builder.select.return_value = mock_builder
            mock_builder.eq.return_value = mock_builder
            mock_builder.single.return_value = mock_builder
            mock_builder.execute.return_value = MagicMock(
                data={"id": uid, "email": "sb.user@firm.com", "role": "admin", "is_active": True}
            )
            mock_get_sb.return_value = mock_sb

            profile = get_user_profile(uid)
            assert profile is not None
            assert profile["id"] == uid
            assert profile["email"] == "sb.user@firm.com"
            mock_sb.table.assert_called_with("user_profiles")

    def test_assert_client_gstin_in_firm_aurora_authorized(self, tenancy_sqlite_engine, tenancy_repo):
        from app.services.firm_access import assert_client_gstin_in_firm

        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27AUTHCLIENT111", is_active=True),
            ])
            session.commit()

        mock_sb = MagicMock()
        # Should succeed without calling Supabase
        assert_client_gstin_in_firm(mock_sb, cid, owner_id)
        mock_sb.table.assert_not_called()

    def test_assert_client_gstin_in_firm_aurora_denial_never_falls_through(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """CRITICAL SECURITY TEST:
        When a client exists in Aurora but belongs to another firm,
        access MUST be denied with HTTP 403 immediately.
        It MUST NEVER fall through to Supabase!
        """
        from app.services.firm_access import assert_client_gstin_in_firm

        firm_a_owner = str(uuid.uuid4())
        firm_b_owner = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=firm_a_owner, email="a@firm.com", role="admin"),
                UserProfile(id=firm_b_owner, email="b@firm.com", role="admin"),
                # Client belongs to Firm A
                ClientGSTIN(id=cid, firm_owner_id=firm_a_owner, gstin="27DENIALTEST111", is_active=True),
            ])
            session.commit()

        mock_sb = MagicMock()
        # Firm B attempts to access Firm A's client: MUST raise 403 and NOT call Supabase
        with pytest.raises(HTTPException) as exc_info:
            assert_client_gstin_in_firm(mock_sb, cid, firm_b_owner)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "not allowed for this client"
        mock_sb.table.assert_not_called()

    def test_assert_client_gstin_in_firm_infrastructure_miss_falls_back(self, tenancy_repo):
        from app.services.firm_access import assert_client_gstin_in_firm

        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        # Client not in Aurora -> infrastructure miss -> falls back to Supabase

        mock_sb = MagicMock()
        mock_builder = MagicMock()
        mock_sb.table.return_value = mock_builder
        mock_builder.select.return_value = mock_builder
        mock_builder.eq.return_value = mock_builder
        mock_builder.limit.return_value = mock_builder
        mock_builder.execute.return_value = MagicMock(data=[{"id": cid}])

        assert_client_gstin_in_firm(mock_sb, cid, owner_id)
        mock_sb.table.assert_called_with("client_gstins")

    def test_list_accessible_client_gstin_ids_aurora_user_with_clients_no_supabase_fallback(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """Aurora user + clients -> returns client IDs -> no Supabase fallback."""
        from app.services.firm_access import list_accessible_client_gstin_ids

        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27DUALREAD11111", is_active=True),
            ])
            session.commit()

        mock_sb = MagicMock()
        current_user = {"id": owner_id, "role": "admin"}
        ids = list_accessible_client_gstin_ids(mock_sb, current_user)
        assert ids == {cid}
        mock_sb.table.assert_not_called()

    def test_list_accessible_client_gstin_ids_aurora_user_zero_clients_no_supabase_fallback(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        """Aurora user + zero accessible clients -> returns empty set -> NO Supabase fallback."""
        from app.services.firm_access import list_accessible_client_gstin_ids

        owner_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            # User exists in Aurora user_profiles, but has NO client_gstins rows
            session.add(UserProfile(id=owner_id, email="zero_clients@firm.com", role="admin"))
            session.commit()

        mock_sb = MagicMock()
        current_user = {"id": owner_id, "role": "admin"}
        ids = list_accessible_client_gstin_ids(mock_sb, current_user)
        assert ids == set()
        # CRITICAL: Empty set returned from Aurora MUST NOT trigger Supabase fallback!
        mock_sb.table.assert_not_called()

    def test_list_accessible_client_gstin_ids_user_absent_from_aurora_allows_supabase_fallback(
        self, tenancy_repo
    ):
        """User absent from Aurora -> returns None -> Supabase fallback allowed."""
        from app.services.firm_access import list_accessible_client_gstin_ids

        absent_user_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        mock_sb = MagicMock()
        mock_builder = MagicMock()
        mock_sb.table.return_value = mock_builder
        mock_builder.select.return_value = mock_builder
        mock_builder.eq.return_value = mock_builder
        mock_builder.execute.return_value = MagicMock(data=[{"id": cid}])

        current_user = {"id": absent_user_id, "role": "admin"}
        ids = list_accessible_client_gstin_ids(mock_sb, current_user)
        assert ids == {cid}
        # Supabase MUST be called when user is absent from Aurora
        mock_sb.table.assert_called_with("client_gstins")

    def test_get_firm_owner_for_client_dual_read(self, tenancy_sqlite_engine, tenancy_repo):
        from app.services.firm_access import get_firm_owner_for_client

        owner_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27OWNERDUAL1111", is_active=True),
            ])
            session.commit()

        mock_sb = MagicMock()
        resolved_owner = get_firm_owner_for_client(mock_sb, cid)
        assert resolved_owner == owner_id
        mock_sb.table.assert_not_called()

    def test_user_can_access_firm_dual_read(self, tenancy_sqlite_engine, tenancy_repo):
        from app.services.firm_access import user_can_access_firm

        owner_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                UserProfile(id=staff_id, email="staff@firm.com", role="staff"),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27CANACCESS111", assigned_to=staff_id, is_active=True),
            ])
            session.commit()

        mock_sb = MagicMock()
        current_user = {"id": staff_id, "role": "staff"}
        assert user_can_access_firm(mock_sb, current_user, owner_id) is True
        mock_sb.table.assert_not_called()

    def test_user_in_same_firm_dual_read_denial_no_fallback(self, tenancy_sqlite_engine, tenancy_repo):
        from app.services.firm_access import user_in_same_firm

        owner_id = str(uuid.uuid4())
        staff_a = str(uuid.uuid4())
        staff_b = str(uuid.uuid4())
        cid = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add_all([
                UserProfile(id=owner_id, email="owner@firm.com", role="admin"),
                UserProfile(id=staff_a, email="a@firm.com", role="staff"),
                UserProfile(id=staff_b, email="b@firm.com", role="staff"),
                ClientGSTIN(id=cid, firm_owner_id=owner_id, gstin="27SAMEFIRMDENY", assigned_to=staff_a, is_active=True),
            ])
            session.commit()

        mock_sb = MagicMock()
        # staff_b is NOT assigned to cid (which exists in Aurora) -> returns False without checking Supabase
        current_user = {"id": staff_b, "role": "staff"}
        result = user_in_same_firm(mock_sb, current_user, owner_id, cid)
        assert result is False
        mock_sb.table.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Authentication Identity Separation Regression Test
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthIdentitySeparation:
    """Regression test: Cognito claims.sub is NEVER confused with canonical user_profiles.id."""

    def test_cognito_sub_never_matches_canonical_user_profiles_id(
        self, tenancy_sqlite_engine, tenancy_repo
    ):
        cognito_sub = "cognito-provider-sub-abcdef-123456"
        canonical_user_id = str(uuid.uuid4())

        with Session(tenancy_sqlite_engine) as session:
            session.add(
                UserProfile(
                    id=canonical_user_id,
                    email="ca@firm.example",
                    role="admin",
                    is_active=True,
                )
            )
            session.commit()

        # Tenancy repository MUST query by canonical_user_id, NEVER cognito_sub
        assert tenancy_repo.get_user_profile(canonical_user_id) is not None
        assert tenancy_repo.get_user_profile(cognito_sub) is None

        # Active check with cognito_sub returns None (not found), not True
        assert tenancy_repo.is_user_active(cognito_sub) is None
        assert tenancy_repo.is_user_active(canonical_user_id) is True
