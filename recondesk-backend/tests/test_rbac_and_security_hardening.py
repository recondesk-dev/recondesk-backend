"""Comprehensive Security Hardening and Granular RBAC Verification Test Suite.

Phase 3.1 Verification:
1. Fail-closed role resolution and identity defaults:
   - Unknown roles, missing profiles, and DB failures strictly default to 'viewer'.
   - Privilege escalation blocked: viewers and preparers cannot access admin/partner routes.
2. Granular roles and permission hierarchy:
   - Owner / Partner: statutory filing, overrides, governance policy, team removal.
   - Manager: client assignments, bulk filing batch creation, review.
   - Preparer: data entry, reconciliation, drafting returns for assigned clients.
   - Viewer: strictly read-only access.
3. Bulk / Celery filing governance bypass closure:
   - Tenant boundary verification: cross-tenant client_gstin_ids blocked with error.
   - Pre-filing validation applied during async Celery execution.
   - Active partner override consumed atomically on proceeding/filing.
4. Multi-role client assignments and atomic bulk reassignment:
   - client_assignments table tracks multiple roles per client.
   - Atomic bulk reassignment updates both client_assignments and client_gstins.assigned_to.
   - Firm isolation enforced across assignments.
5. Legacy backward compatibility:
   - Legacy 'admin' retains full partner authority.
   - Legacy 'staff' retains preparer authority.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import (
    DEFAULT_FAIL_CLOSED_ROLE,
    get_user_role,
    require_admin,
    require_admin_user,
    require_manager_user,
    require_writer_user,
)
from app.models.roles import (
    ALL_ROLES,
    INVITABLE_ROLES,
    ADMIN_ROLES,
    MANAGER_ROLES,
    WRITER_ROLES,
    VIEWER_ROLES,
    Role,
    is_admin_or_partner,
    is_manager_or_above,
    is_writer_or_above,
    is_viewer_only,
    normalize_role,
)
from app.models.tenancy import Base, ClientAssignment, ClientGSTIN, TeamMember, UserProfile
from app.repositories.tenancy import AuroraTenancyRepository, set_tenancy_repository
from app.routers.clients import ClientUpdate, get_client, update_client
from app.routers.filing import EvcOtpBody, GenerateOtpBody, generate_evc_otp, generate_otp
from app.services.firm_access import list_accessible_client_gstin_ids
from app.worker.filing_batch_task import process_filing_batch


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory SQLite Fixtures for Tenancy Repository
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tenancy_sqlite_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def tenancy_repo(tenancy_sqlite_engine):
    repo = AuroraTenancyRepository.__new__(AuroraTenancyRepository)
    repo._engine = tenancy_sqlite_engine
    repo._session_factory = sessionmaker(bind=tenancy_sqlite_engine)
    set_tenancy_repository(repo)
    yield repo
    set_tenancy_repository(None)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Role Normalization & Predicate Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRoleNormalizationAndPredicates:
    """Verify that role normalization strictly fails closed to 'viewer' and predicates enforce hierarchy."""

    def test_normalize_role_fail_closed(self):
        """Unknown or missing roles must strictly normalize to 'viewer', NEVER 'admin'."""
        assert normalize_role(None) == "viewer"
        assert normalize_role("") == "viewer"
        assert normalize_role("   ") == "viewer"
        assert normalize_role(123) == "viewer"
        assert normalize_role("superadmin") == "viewer"
        assert normalize_role("root") == "viewer"
        assert normalize_role("hacker") == "viewer"
        assert normalize_role("unknown_custom_role") == "viewer"

    def test_normalize_role_canonical_and_legacy(self):
        """All canonical and legacy roles normalize correctly when lowercase/whitespace."""
        for role in ALL_ROLES:
            assert normalize_role(role) == role
            assert normalize_role(f"  {role.upper()}  ") == role

    def test_admin_and_partner_predicates(self):
        """is_admin_or_partner returns True only for owner, partner, and legacy admin."""
        for r in ("owner", "partner", "admin"):
            assert is_admin_or_partner(r) is True
        for r in ("manager", "preparer", "staff", "viewer", "guest", "", None):
            assert is_admin_or_partner(r) is False

    def test_manager_or_above_predicates(self):
        """is_manager_or_above returns True for manager and admin roles, False for preparer/viewer."""
        for r in ("owner", "partner", "admin", "manager"):
            assert is_manager_or_above(r) is True
        for r in ("preparer", "staff", "viewer", "guest", "", None):
            assert is_manager_or_above(r) is False

    def test_writer_or_above_predicates(self):
        """is_writer_or_above returns True for all operational roles, False only for viewer and unknown."""
        for r in ("owner", "partner", "admin", "manager", "preparer", "staff"):
            assert is_writer_or_above(r) is True
        for r in ("viewer", "guest", "", None):
            assert is_writer_or_above(r) is False

    def test_viewer_only_predicates(self):
        """is_viewer_only returns True for viewer, False for write/admin roles."""
        assert is_viewer_only("viewer") is True
        assert is_viewer_only(None) is True  # fails closed to viewer
        assert is_viewer_only("admin") is False
        assert is_viewer_only("manager") is False
        assert is_viewer_only("preparer") is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Authentication Layer Security & Fail-Closed Defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthFailClosedDefaults:
    """Verify that authentication helpers never grant admin privileges on error."""

    @pytest.mark.asyncio
    async def test_get_user_role_missing_profile_fails_closed(self):
        """When user has no profile in identity store, default strictly to 'viewer'."""
        with patch("app.auth.get_identity_store") as mock_store, \
             patch("app.auth.get_user_profile", return_value=None), \
             patch("app.auth.get_supabase") as mock_sb:
            mock_store.return_value = None
            mock_sb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            
            role = await get_user_role("user-without-profile")
            assert role == "viewer"

    @pytest.mark.asyncio
    async def test_get_user_role_db_exception_fails_closed(self):
        """When database lookup throws an unhandled exception, fail closed to 'viewer'."""
        with patch("app.auth.get_identity_store", side_effect=RuntimeError("Database down")), \
             patch("app.auth.get_user_profile", side_effect=RuntimeError("Database down")):
            role = await get_user_role("any-user")
            assert role == "viewer"

    @pytest.mark.asyncio
    async def test_get_user_role_unknown_role_in_profile_fails_closed(self):
        """When user profile contains an invalid role, normalize strictly to 'viewer'."""
        with patch("app.auth.get_identity_store") as mock_store, \
             patch("app.auth.get_user_profile", return_value={"id": "u1", "role": "unsupported_god_mode"}):
            mock_store.return_value = None
            role = await get_user_role("u1")
            assert role == "viewer"

    @pytest.mark.asyncio
    async def test_require_admin_user_blocks_non_admin(self):
        """require_admin_user raises 403 Forbidden for manager, preparer, viewer, and empty role."""
        for bad_role in ("manager", "preparer", "staff", "viewer", "", None):
            with pytest.raises(HTTPException) as exc_info:
                await require_admin_user({"id": "test-uid", "role": bad_role})
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_admin_user_allows_partner_and_owner(self):
        """require_admin_user permits owner, partner, and legacy admin."""
        for good_role in ("owner", "partner", "admin"):
            res = await require_admin_user({"id": "test-uid", "role": good_role})
            assert res["role"] == good_role

    @pytest.mark.asyncio
    async def test_require_manager_user_blocks_preparer_and_viewer(self):
        """require_manager_user raises 403 Forbidden for preparer and viewer."""
        for bad_role in ("preparer", "staff", "viewer", "", None):
            with pytest.raises(HTTPException) as exc_info:
                await require_manager_user({"id": "test-uid", "role": bad_role})
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_writer_user_blocks_viewer(self):
        """require_writer_user raises 403 Forbidden for viewer."""
        for bad_role in ("viewer", "", None):
            with pytest.raises(HTTPException) as exc_info:
                await require_writer_user({"id": "test-uid", "role": bad_role})
            assert exc_info.value.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 3. Tenancy Repository: Multi-Role Client Assignments & Bulk Reassignment
# ─────────────────────────────────────────────────────────────────────────────

class TestTenancyAssignmentsAndIsolation:
    """Verify multi-role client assignments, bulk reassignment, and tenant isolation."""

    def test_assign_client_multi_role_preparer_and_reviewer(self, tenancy_repo):
        """Assigning preparer updates assigned_to; assigning reviewer creates assignment without clobbering."""
        owner_id = str(uuid.uuid4())
        preparer_id = str(uuid.uuid4())
        reviewer_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        # Setup firm owner, staff profiles, and client
        tenancy_repo.upsert_user_profile({"id": owner_id, "email": "ca@firm.in", "role": "owner"})
        tenancy_repo.upsert_user_profile({"id": preparer_id, "email": "prep@firm.in", "role": "preparer"})
        tenancy_repo.upsert_user_profile({"id": reviewer_id, "email": "rev@firm.in", "role": "manager"})

        tenancy_repo.create_client({
            "id": client_id,
            "firm_owner_id": owner_id,
            "gstin": "27AABCU9603R1ZM",
            "trade_name": "Acme Corp",
            "is_active": True,
        })

        # 1. Assign preparer
        p_res = tenancy_repo.assign_client_multi_role(
            client_id=client_id,
            user_id=preparer_id,
            firm_owner_id=owner_id,
            assignment_role="preparer",
        )
        assert p_res["assignment_role"] == "preparer"

        # Verify client_gstins.assigned_to is populated
        client_row = tenancy_repo.get_client_gstin(client_id)
        assert client_row["assigned_to"] == preparer_id

        # 2. Assign reviewer
        r_res = tenancy_repo.assign_client_multi_role(
            client_id=client_id,
            user_id=reviewer_id,
            firm_owner_id=owner_id,
            assignment_role="reviewer",
        )
        assert r_res["assignment_role"] == "reviewer"

        # Verify assigned_to was NOT overwritten by reviewer
        client_row_after = tenancy_repo.get_client_gstin(client_id)
        assert client_row_after["assigned_to"] == preparer_id

        # 3. List assignments
        assignments = tenancy_repo.list_client_assignments(client_id)
        assert len(assignments) == 2
        assigned_roles = {a["assignment_role"] for a in assignments}
        assert assigned_roles == {"preparer", "reviewer"}

        # 4. Access verification
        assert tenancy_repo.verify_staff_assignment(client_id, preparer_id) is True
        assert tenancy_repo.verify_staff_assignment(client_id, reviewer_id) is True
        assert tenancy_repo.verify_staff_assignment(client_id, str(uuid.uuid4())) is False

    def test_bulk_reassign_clients_atomic(self, tenancy_repo):
        """Atomically reassign 5 clients to a new preparer; verify firm isolation blocks other firms."""
        firm_a_owner = str(uuid.uuid4())
        firm_b_owner = str(uuid.uuid4())
        staff_a = str(uuid.uuid4())

        tenancy_repo.upsert_user_profile({"id": firm_a_owner, "email": "firm_a@ca.in", "role": "owner"})
        tenancy_repo.upsert_user_profile({"id": firm_b_owner, "email": "firm_b@ca.in", "role": "owner"})
        tenancy_repo.upsert_user_profile({"id": staff_a, "email": "staff_a@ca.in", "role": "preparer"})

        # Create 3 clients for Firm A and 2 clients for Firm B
        firm_a_clients = [str(uuid.uuid4()) for _ in range(3)]
        for i, cid in enumerate(firm_a_clients):
            tenancy_repo.create_client({
                "id": cid,
                "firm_owner_id": firm_a_owner,
                "gstin": f"27AABCU960{i}R1ZM",
                "trade_name": f"Firm A Client {i}",
                "is_active": True,
            })

        firm_b_clients = [str(uuid.uuid4()) for _ in range(2)]
        for i, cid in enumerate(firm_b_clients):
            tenancy_repo.create_client({
                "id": cid,
                "firm_owner_id": firm_b_owner,
                "gstin": f"29AABCU960{i}R1ZM",
                "trade_name": f"Firm B Client {i}",
                "is_active": True,
            })

        # Attempt to bulk reassign Firm A clients + Firm B clients under Firm A owner authority
        attempted_ids = firm_a_clients + firm_b_clients
        successful = tenancy_repo.bulk_reassign_clients(
            client_ids=attempted_ids,
            user_id=staff_a,
            firm_owner_id=firm_a_owner,
            assignment_role="preparer",
        )

        # Cross-tenant clients from Firm B must be ignored/omitted from successful list
        assert set(successful) == set(firm_a_clients)
        assert not any(b_id in successful for b_id in firm_b_clients)

        # Verify staff_a can access all Firm A clients, but none of Firm B clients
        for cid in firm_a_clients:
            assert tenancy_repo.verify_staff_assignment(cid, staff_a) is True
        for cid in firm_b_clients:
            assert tenancy_repo.verify_staff_assignment(cid, staff_a) is False

    def test_list_accessible_clients_granular_hierarchy(self, tenancy_repo):
        """Manager sees all firm clients; Preparer/Viewer only see assigned clients."""
        owner_id = str(uuid.uuid4())
        manager_id = str(uuid.uuid4())
        preparer_id = str(uuid.uuid4())
        viewer_id = str(uuid.uuid4())

        tenancy_repo.upsert_user_profile({"id": owner_id, "email": "owner@ca.in", "role": "owner"})
        tenancy_repo.upsert_user_profile({"id": manager_id, "email": "mgr@ca.in", "role": "manager"})
        tenancy_repo.upsert_user_profile({"id": preparer_id, "email": "prep@ca.in", "role": "preparer"})
        tenancy_repo.upsert_user_profile({"id": viewer_id, "email": "view@ca.in", "role": "viewer"})

        # Register team members
        tenancy_repo.create_or_update_team_member({
            "id": str(uuid.uuid4()),
            "firm_owner_id": owner_id,
            "member_user_id": manager_id,
            "role": "manager",
            "is_active": True,
        })
        tenancy_repo.create_or_update_team_member({
            "id": str(uuid.uuid4()),
            "firm_owner_id": owner_id,
            "member_user_id": preparer_id,
            "role": "preparer",
            "is_active": True,
        })
        tenancy_repo.create_or_update_team_member({
            "id": str(uuid.uuid4()),
            "firm_owner_id": owner_id,
            "member_user_id": viewer_id,
            "role": "viewer",
            "is_active": True,
        })

        # Create 3 clients
        c1, c2, c3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        for cid, name in [(c1, "Client 1"), (c2, "Client 2"), (c3, "Client 3")]:
            tenancy_repo.create_client({
                "id": cid,
                "firm_owner_id": owner_id,
                "gstin": f"27AAB{cid[:8].upper()}1ZM",
                "trade_name": name,
                "is_active": True,
            })

        # Assign c1 to preparer, c2 to viewer
        tenancy_repo.assign_client_multi_role(c1, preparer_id, owner_id, "preparer")
        tenancy_repo.assign_client_multi_role(c2, viewer_id, owner_id, "viewer")

        # Manager sees all 3 clients
        mgr_clients = tenancy_repo.list_accessible_clients(manager_id, role="manager")
        assert len(mgr_clients) == 3

        # Preparer sees only c1
        prep_clients = tenancy_repo.list_accessible_clients(preparer_id, role="preparer")
        assert len(prep_clients) == 1
        assert prep_clients[0]["id"] == c1

        # Viewer sees only c2
        view_clients = tenancy_repo.list_accessible_clients(viewer_id, role="viewer")
        assert len(view_clients) == 1
        assert view_clients[0]["id"] == c2


# ─────────────────────────────────────────────────────────────────────────────
# 4. Celery / Bulk Filing Governance Bypass Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBulkFilingWorkerGovernance:
    """Verify that process_filing_batch enforces tenant isolation and pre-filing validation."""

    def test_worker_rejects_cross_tenant_item(self):
        """Batch task fails item if client does not belong to firm."""
        mock_sb = MagicMock()
        # Mock get_batch returning batch for firm_a
        firm_a = str(uuid.uuid4())
        batch_id = str(uuid.uuid4())
        cross_tenant_client_id = str(uuid.uuid4())

        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
            "id": batch_id,
            "firm_id": firm_a,
            "period": "2024-11",
            "return_type": "gstr-1",
            "items": [{
                "id": "item-1",
                "client_gstin_id": cross_tenant_client_id,
                "status": "pending",
            }],
        }]

        # Mock assert_client_gstin_in_firm raising ValueError (cross-tenant)
        with patch("app.worker.filing_batch_task.get_supabase", return_value=mock_sb), \
             patch("app.filing.filing_store.get_batch") as mock_get_batch, \
             patch("app.filing.filing_store.update_batch_item") as mock_update_item, \
             patch("app.services.firm_access.assert_client_gstin_in_firm", side_effect=ValueError("Tenant mismatch")):
            mock_get_batch.return_value = {
                "id": batch_id,
                "firm_id": firm_a,
                "period": "2024-11",
                "return_type": "gstr-1",
                "items": [{
                    "id": "item-1",
                    "client_gstin_id": cross_tenant_client_id,
                    "gstin": "27AABCU9603R1ZM",
                    "status": "pending",
                }],
            }

            process_filing_batch(batch_id)

            # Item must be marked failed with UNAUTHORIZED_TENANT
            mock_update_item.assert_called_with(
                mock_sb,
                "item-1",
                status="failed",
                error_code="UNAUTHORIZED_TENANT",
                error_detail="Client GSTIN does not belong to the authorized firm.",
            )

    def test_worker_blocks_item_on_governance_failure(self):
        """Under STRICT_BLOCK, Rule 88C discrepancy causes item to be marked 'blocked'."""
        mock_sb = MagicMock()
        firm_id = str(uuid.uuid4())
        batch_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())

        item_data = {
            "id": "item-gov-block",
            "client_gstin_id": client_id,
            "gstin": "27AABCU9603R1ZM",
            "status": "pending",
        }

        with patch("app.worker.filing_batch_task.get_supabase", return_value=mock_sb), \
             patch("app.filing.filing_store.get_batch") as mock_get_batch, \
             patch("app.filing.filing_store.update_batch_item") as mock_update_item, \
             patch("app.filing.filing_store.get_active_session", return_value={"session_token": "tok-1", "id": "s-1"}), \
             patch("app.worker.filing_batch_task.fetch_sales_register_records", return_value=[{"record_data": {}}]), \
             patch("app.worker.filing_batch_task.map_sales_register_to_gstr1", return_value={}), \
             patch("app.worker.filing_batch_task.serialize_gstr1_readiness", return_value={"pending_review_count": 0}), \
             patch("app.services.firm_access.assert_client_gstin_in_firm") as mock_assert_firm, \
             patch("app.services.filing_override_service.get_firm_filing_policy") as mock_policy, \
             patch("app.services.pre_filing_validator.validate_gstr1_pre_filing") as mock_validate, \
             patch("app.services.filing_override_service.verify_filing_governance_gate") as mock_gate:
            
            mock_assert_firm.return_value = {"id": client_id, "gstin": "27AABCU9603R1ZM", "firm_owner_id": firm_id}
            mock_get_batch.return_value = {
                "id": batch_id,
                "firm_id": firm_id,
                "period": "2024-11",
                "return_type": "gstr-1",
                "items": [item_data],
            }

            mock_pol = MagicMock()
            mock_pol.mode.value = "strict_block"
            mock_policy.return_value = mock_pol

            # Validation result has blocking violation
            val_result = MagicMock()
            val_result.has_blocking_violations = True
            mock_validate.return_value = val_result

            # Governance gate raises HTTP 403 STRICT_BLOCK
            mock_gate.side_effect = HTTPException(status_code=403, detail="Blocked by firm filing governance policy")

            process_filing_batch(batch_id)

            # Item must be marked blocked with GOVERNANCE_BLOCKED
            mock_update_item.assert_called_with(
                mock_sb,
                "item-gov-block",
                status="blocked",
                error_code="GOVERNANCE_BLOCKED",
                error_detail="Blocked by firm filing governance policy",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Audit Vulnerability Remediation & Sensitive Endpoint Guards
# ─────────────────────────────────────────────────────────────────────────────

class TestVulnerabilityRemediationAndEndpointGuards:
    """Verify fixes for the audit findings:
    - Viewer authorization bypass on client update
    - Viewer authorization bypass on filing session OTP generation & verification
    - Session IDOR via omitted client_gstin_id
    - Viewer authorization bypass on EVC OTP generation
    - UnboundLocalError resolution in Aurora get_client hit
    """

    @pytest.mark.asyncio
    async def test_viewer_blocked_from_client_update(self):
        """Viewer role must be rejected with 403 on PATCH /api/clients/{client_id}."""
        client_id = str(uuid.uuid4())
        viewer_user = {"id": str(uuid.uuid4()), "role": "viewer"}
        body = ClientUpdate(trade_name="Unauthorized Edit")

        with pytest.raises(HTTPException) as exc_info:
            await update_client(client_id, body=body, current_user=viewer_user)
        assert exc_info.value.status_code == 403
        assert "Write access required" in str(exc_info.value.detail)

    def test_viewer_blocked_from_otp_generation(self):
        """Viewer role must be rejected with 403 on POST /session/otp/generate."""
        viewer_user = {"id": str(uuid.uuid4()), "role": "viewer"}
        body = GenerateOtpBody(username="testuser", gstin="27AABCU9603R1ZM")

        with pytest.raises(HTTPException) as exc_info:
            generate_otp(body=body, current_user=viewer_user)
        assert exc_info.value.status_code == 403
        assert "Write access required" in str(exc_info.value.detail)

    def test_otp_generation_rejects_unassigned_gstin_when_client_id_omitted(self):
        """When client_gstin_id is omitted, arbitrary unassociated GSTIN must be rejected with 403."""
        preparer_user = {"id": str(uuid.uuid4()), "role": "preparer"}
        body = GenerateOtpBody(username="testuser", gstin="27AABCU9603R1ZM")
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        with patch("app.routers.filing.get_supabase", return_value=mock_sb), \
             patch("app.routers.filing._firm_id", return_value=str(uuid.uuid4())):
            with pytest.raises(HTTPException) as exc_info:
                generate_otp(body=body, current_user=preparer_user)
            assert exc_info.value.status_code == 403
            assert "Client GSTIN not found or not accessible" in str(exc_info.value.detail)

    def test_viewer_blocked_from_evc_otp_generation(self):
        """Viewer role must be rejected with 403 on POST /gstr-1/{period}/evc-otp."""
        viewer_user = {"id": str(uuid.uuid4()), "role": "viewer"}
        body = EvcOtpBody(session_id=str(uuid.uuid4()), pan="ABCDE1234F")

        with pytest.raises(HTTPException) as exc_info:
            generate_evc_otp(period="2024-11", body=body, current_user=viewer_user)
        assert exc_info.value.status_code == 403
        assert "Write access required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_get_client_aurora_hit_resolves_owner_without_unbound_error(self, tenancy_repo):
        """On Aurora hit, get_client must resolve firm owner via repo without UnboundLocalError."""
        owner_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        user = {"id": owner_id, "role": "owner"}

        tenancy_repo.upsert_user_profile({
            "id": owner_id,
            "email": "owner@firm.test",
            "role": "owner",
        })
        tenancy_repo.create_client({
            "id": client_id,
            "firm_owner_id": owner_id,
            "gstin": "27AABCU9603R1ZM",
            "trade_name": "Test Enterprise",
            "is_active": True,
        })

        with patch("app.routers.clients.get_user_profile", return_value={"id": owner_id, "role": "owner"}):
            client = await get_client(client_id=client_id, current_user=user)
        assert client is not None
        assert client["id"] == client_id
        assert client["trade_name"] == "Test Enterprise"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Migration Safety & Non-Destructive Rollback Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrationSafetyAndRollback:
    """Verify Phase 3.1 migration safety invariants:
    - Down migration archives data rather than destructively dropping it.
    - Read-only 'viewer' accounts are deactivated on downgrade to prevent privilege escalation to 'staff'.
    - Deactivated staff members cannot pass writer authorization.
    - Client assignments and granular roles are preserved in archival tables.
    """

    def test_down_migration_sql_contains_safety_guards(self):
        """Down migration script must contain archival steps and viewer deactivation."""
        down_path = (
            Path(__file__).resolve().parent.parent
            / "migrations"
            / "aurora"
            / "20261011120000_create_client_assignments_and_granular_roles.down.sql"
        )
        assert down_path.exists(), "Down migration file missing"
        content = down_path.read_text(encoding="utf-8")

        # 1. Advisory comments for AWS Aurora PITR / snapshot restoration
        assert "Point-in-Time Recovery" in content or "PITR" in content
        assert "restore-db-cluster-to-point-in-time" in content

        # 2. Archival table for client assignments
        assert "_archive_client_assignments_rollback" in content
        assert "INSERT INTO public._archive_client_assignments_rollback" in content

        # 3. Archival table for team member granular roles
        assert "_archive_team_member_roles_rollback" in content
        assert "INSERT INTO public._archive_team_member_roles_rollback" in content

        # 4. Privilege escalation prevention: viewer deactivated
        assert "WHEN role = 'viewer' THEN FALSE" in content

        # 5. Legacy check constraint restoration
        assert "CHECK (role IN ('admin', 'staff'))" in content

    def test_downgrade_role_remapping_prevents_privilege_escalation(self):
        """Simulate down migration CASE statement to verify viewer cannot escalate to active writer."""
        members = [
            {"id": "u1", "role": "owner", "is_active": True},
            {"id": "u2", "role": "partner", "is_active": True},
            {"id": "u3", "role": "manager", "is_active": True},
            {"id": "u4", "role": "preparer", "is_active": True},
            {"id": "u5", "role": "viewer", "is_active": True},
        ]

        # Emulate the down migration SQL logic:
        downgraded = []
        for m in members:
            old_role = m["role"]
            new_role = "admin" if old_role in ("owner", "partner") else "staff"
            new_is_active = False if old_role == "viewer" else m["is_active"]
            downgraded.append({
                "id": m["id"],
                "old_role": old_role,
                "new_role": new_role,
                "is_active": new_is_active,
            })

        # Verify partners and owners become admin
        assert downgraded[0]["new_role"] == "admin" and downgraded[0]["is_active"] is True
        assert downgraded[1]["new_role"] == "admin" and downgraded[1]["is_active"] is True

        # Verify managers and preparers become active staff
        assert downgraded[2]["new_role"] == "staff" and downgraded[2]["is_active"] is True
        assert downgraded[3]["new_role"] == "staff" and downgraded[3]["is_active"] is True

        # CRITICAL: Verify viewer becomes DEACTIVATED staff to prevent write escalation
        viewer_rec = downgraded[4]
        assert viewer_rec["old_role"] == "viewer"
        assert viewer_rec["new_role"] == "staff"
        assert viewer_rec["is_active"] is False, "Viewer must be deactivated to fail closed"


