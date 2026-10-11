"""Automated Staging Aurora PostgreSQL Migration Validator (Phase 3.1).

Validates the Phase 3.1 Aurora schema migration against an isolated staging PostgreSQL database:
1. Safety: Fails closed if pointed to production Aurora cluster.
2. Applies prerequisite migrations (20260930183000 through 20261010230000).
3. Populates synthetic legacy tenancy data (firms, legacy admin/staff, active/inactive clients).
4. Applies Phase 3.1 upgrade (20261011120000_create_client_assignments_and_granular_roles.up.sql).
5. Validates:
   - Client assignment backfill row counts.
   - Legacy role compatibility.
   - Granular role constraints ('owner', 'partner', 'manager', 'preparer', 'viewer').
   - Foreign-key constraints and cascade behavior.
   - Unique multi-role constraint (client_gstin_id, user_id, assignment_role).
   - Cross-tenant isolation.
   - Idempotency & checksum tracking.
6. Validates rollback safety:
   - Archival of client assignments in _archive_client_assignments_rollback.
   - Archival of granular roles in _archive_team_member_roles_rollback.
   - Prevention of privilege escalation (viewer deactivated to fail closed).
   - Re-enforcement of legacy check constraint ('admin', 'staff').
7. Re-applies upgrade and validates data restoration from archive.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from app.aurora import mask_database_url, sanitize_db_error
from app.migrations.runner import AuroraMigrationRunner

_log = logging.getLogger("recondesk.staging.validator")

# Known production hostnames that must NEVER be targeted
_FORBIDDEN_PROD_HOST_PATTERNS = [
    "recondesk.cluster-cre2mcouo1xv.ap-south-1.rds.amazonaws.com",
    "prod",
    "production",
]


class StagingSafetyViolationError(Exception):
    """Raised when an operation targets production or an unsafe database."""


@dataclass
class ValidationReport:
    timestamp: str
    target_database: str
    postgres_version: str
    prerequisite_migrations_applied: int
    pre_upgrade_client_count: int
    pre_upgrade_active_assigned_count: int
    phase31_applied_successfully: bool
    backfill_assignment_count: int
    granular_roles_verified: bool
    invalid_role_rejected: bool
    duplicate_assignment_rejected: bool
    foreign_key_enforced: bool
    cross_tenant_isolation_verified: bool
    idempotent_reupgrade_verified: bool
    downgrade_archival_verified: bool
    downgrade_privilege_escalation_prevented: bool
    reupgrade_and_restore_verified: bool
    all_checks_passed: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_staging_database_safety(url_str: str) -> None:
    """Ensure the target connection URL is NOT production."""
    parsed = urlparse(url_str)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    for pattern in _FORBIDDEN_PROD_HOST_PATTERNS:
        if pattern in host:
            raise StagingSafetyViolationError(
                f"SAFETY BLOCK: Target database host '{host}' matches production pattern '{pattern}'. "
                f"Staging migration validation must NEVER be executed against production."
            )

    if "prod" in path or "production" in path:
        raise StagingSafetyViolationError(
            f"SAFETY BLOCK: Target database path '{path}' indicates a production database."
        )


class StagingMigrationValidator:
    """Executes and verifies migration safety against a PostgreSQL instance."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._runner = AuroraMigrationRunner(engine=engine)

    def get_pg_version(self) -> str:
        with self._engine.connect() as conn:
            return str(conn.execute(sa.text("SELECT version()")).scalar())

    def run_prerequisites(self) -> int:
        """Apply all migrations prior to Phase 3.1."""
        # Ensure standard roles expected by historical migrations exist in disposable staging DB
        with self._engine.begin() as conn:
            conn.exec_driver_sql("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
                        CREATE ROLE service_role;
                    END IF;
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
                        CREATE ROLE authenticated;
                    END IF;
                END
                $$;
            """)
        target_version = "20261010230000"
        applied = self._runner.run_upgrade(target_version=target_version)
        return len(applied)

    def seed_legacy_test_data(self) -> dict[str, Any]:
        """Populate representative legacy firms, team members, and clients."""
        with self._engine.begin() as conn:
            # Firm A: CA Principal
            owner_a_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                    INSERT INTO public.user_profiles (id, email, full_name, firm_name, role, is_active)
                    VALUES (:id, 'ca_firm_a@recondesk.test', 'CA Owner A', 'Firm A & Associates', 'admin', TRUE)
                    ON CONFLICT (id) DO NOTHING;
                """),
                {"id": owner_a_id},
            )

            # Firm B: Distinct CA Principal for cross-tenant testing
            owner_b_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                    INSERT INTO public.user_profiles (id, email, full_name, firm_name, role, is_active)
                    VALUES (:id, 'ca_firm_b@recondesk.test', 'CA Owner B', 'Firm B LLP', 'admin', TRUE)
                    ON CONFLICT (id) DO NOTHING;
                """),
                {"id": owner_b_id},
            )

            # Staff in Firm A
            staff_1_id = str(uuid.uuid4())
            staff_2_id = str(uuid.uuid4())
            for s_id, s_email, s_name in [
                (staff_1_id, "staff1@firm_a.test", "Staff One"),
                (staff_2_id, "staff2@firm_a.test", "Staff Two"),
            ]:
                conn.execute(
                    sa.text("""
                        INSERT INTO public.user_profiles (id, email, full_name, role, is_active)
                        VALUES (:id, :email, :name, 'staff', TRUE)
                        ON CONFLICT (id) DO NOTHING;
                    """),
                    {"id": s_id, "email": s_email, "name": s_name},
                )
                conn.execute(
                    sa.text("""
                        INSERT INTO public.team_members (firm_owner_id, member_user_id, role, is_active)
                        VALUES (:firm, :user, 'staff', TRUE)
                        ON CONFLICT (firm_owner_id, member_user_id) DO NOTHING;
                    """),
                    {"firm": owner_a_id, "user": s_id},
                )

            # Clients in Firm A
            # client 1: assigned to staff 1, active
            c1_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                    INSERT INTO public.client_gstins (id, firm_owner_id, gstin, trade_name, assigned_to, is_active)
                    VALUES (:id, :firm, '27AABCU9603R1ZM', 'Client 1 Alpha', :assigned, TRUE);
                """),
                {"id": c1_id, "firm": owner_a_id, "assigned": staff_1_id},
            )

            # client 2: assigned to staff 2, active
            c2_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                    INSERT INTO public.client_gstins (id, firm_owner_id, gstin, trade_name, assigned_to, is_active)
                    VALUES (:id, :firm, '27BBBCU9603R1ZN', 'Client 2 Beta', :assigned, TRUE);
                """),
                {"id": c2_id, "firm": owner_a_id, "assigned": staff_2_id},
            )

            # client 3: unassigned, active
            c3_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                    INSERT INTO public.client_gstins (id, firm_owner_id, gstin, trade_name, assigned_to, is_active)
                    VALUES (:id, :firm, '27CCCU9603R1ZO', 'Client 3 Gamma', NULL, TRUE);
                """),
                {"id": c3_id, "firm": owner_a_id},
            )

            # client 4: assigned to staff 1, but INACTIVE
            c4_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                    INSERT INTO public.client_gstins (id, firm_owner_id, gstin, trade_name, assigned_to, is_active)
                    VALUES (:id, :firm, '27DDDCU9603R1ZP', 'Client 4 Delta', :assigned, FALSE);
                """),
                {"id": c4_id, "firm": owner_a_id, "assigned": staff_1_id},
            )

            return {
                "owner_a_id": owner_a_id,
                "owner_b_id": owner_b_id,
                "staff_1_id": staff_1_id,
                "staff_2_id": staff_2_id,
                "c1_id": c1_id,
                "c2_id": c2_id,
                "c3_id": c3_id,
                "c4_id": c4_id,
            }

    def execute_validation_cycle(self) -> ValidationReport:
        """Run complete migration upgrade, safety tests, downgrade, and re-upgrade."""
        errors: list[str] = []
        pg_ver = self.get_pg_version()
        masked_url = mask_database_url(str(self._engine.url))

        # Step 1: Run prerequisite migrations
        prereqs_applied = self.run_prerequisites()

        # Step 2: Seed legacy data
        seed = self.seed_legacy_test_data()
        owner_a_id = seed["owner_a_id"]
        owner_b_id = seed["owner_b_id"]
        staff_1_id = seed["staff_1_id"]
        staff_2_id = seed["staff_2_id"]
        c1_id = seed["c1_id"]
        c2_id = seed["c2_id"]

        with self._engine.connect() as conn:
            pre_clients = conn.execute(sa.text("SELECT COUNT(*) FROM public.client_gstins")).scalar() or 0
            pre_active_assigned = conn.execute(
                sa.text("SELECT COUNT(*) FROM public.client_gstins WHERE assigned_to IS NOT NULL AND is_active = TRUE")
            ).scalar() or 0

        # Step 3: Apply Phase 3.1 upgrade
        phase31_applied = False
        try:
            up_records = self._runner.run_upgrade(target_version="20261011120000")
            phase31_applied = len(up_records) >= 1 or any(r.version == "20261011120000" for r in up_records)
        except Exception as exc:
            errors.append(f"Phase 3.1 upgrade failed: {sanitize_db_error(str(exc))}")

        # Step 4: Validate Backfill correctness
        backfill_count = 0
        with self._engine.connect() as conn:
            backfill_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM public.client_assignments")
            ).scalar() or 0

        if backfill_count != pre_active_assigned:
            errors.append(
                f"Backfill mismatch: expected {pre_active_assigned} active assignments, found {backfill_count}"
            )

        # Step 5: Test Granular Roles on team_members
        granular_roles_ok = False
        invalid_role_rejected = False
        try:
            with self._engine.begin() as conn:
                # Insert all canonical granular roles
                for r_name in ["owner", "partner", "manager", "preparer", "viewer"]:
                    m_user_id = str(uuid.uuid4())
                    conn.execute(
                        sa.text("""
                            INSERT INTO public.user_profiles (id, email, full_name, role, is_active)
                            VALUES (:id, :email, :name, :role, TRUE);
                        """),
                        {"id": m_user_id, "email": f"{r_name}@firm_a.test", "name": f"User {r_name}", "role": r_name},
                    )
                    conn.execute(
                        sa.text("""
                            INSERT INTO public.team_members (firm_owner_id, member_user_id, role, is_active)
                            VALUES (:firm, :user, :role, TRUE);
                        """),
                        {"firm": owner_a_id, "user": m_user_id, "role": r_name},
                    )
            granular_roles_ok = True
        except Exception as exc:
            errors.append(f"Granular roles insertion failed: {sanitize_db_error(str(exc))}")

        # Test invalid role rejection by CHECK constraint in dedicated transaction
        try:
            with self._engine.begin() as bad_conn:
                bad_user_id = str(uuid.uuid4())
                bad_conn.execute(
                    sa.text("""
                        INSERT INTO public.user_profiles (id, email, role, is_active)
                        VALUES (:id, 'bad@role.test', 'admin', TRUE);
                    """),
                    {"id": bad_user_id},
                )
                bad_conn.execute(
                    sa.text("""
                        INSERT INTO public.team_members (firm_owner_id, member_user_id, role, is_active)
                        VALUES (:firm, :user, 'unauthorized_superadmin', TRUE);
                    """),
                    {"firm": owner_a_id, "user": bad_user_id},
                )
            errors.append("Invalid role 'unauthorized_superadmin' was accepted! CHECK constraint failed.")
        except Exception:
            invalid_role_rejected = True

        # Step 6: Test Multi-Role Client Assignments & Constraints
        duplicate_rejected = False
        fk_enforced = False
        try:
            with self._engine.begin() as conn:
                # Insert secondary role 'reviewer' for staff_1 on c1
                conn.execute(
                    sa.text("""
                        INSERT INTO public.client_assignments (client_gstin_id, firm_owner_id, user_id, assignment_role)
                        VALUES (:cid, :firm, :uid, 'reviewer');
                    """),
                    {"cid": c1_id, "firm": owner_a_id, "uid": staff_1_id},
                )
        except Exception as exc:
            errors.append(f"Secondary role assignment failed: {sanitize_db_error(str(exc))}")

        # Test Duplicate constraint in dedicated transaction
        try:
            with self._engine.begin() as dup_conn:
                dup_conn.execute(
                    sa.text("""
                        INSERT INTO public.client_assignments (client_gstin_id, firm_owner_id, user_id, assignment_role)
                        VALUES (:cid, :firm, :uid, 'reviewer');
                    """),
                    {"cid": c1_id, "firm": owner_a_id, "uid": staff_1_id},
                )
            errors.append("Duplicate (client, user, role) was accepted! UNIQUE constraint failed.")
        except Exception:
            duplicate_rejected = True

        # Test Foreign-Key constraint in dedicated transaction
        try:
            with self._engine.begin() as fk_conn:
                fk_conn.execute(
                    sa.text("""
                        INSERT INTO public.client_assignments (client_gstin_id, firm_owner_id, user_id, assignment_role)
                        VALUES (:cid, :firm, :uid, 'reviewer');
                    """),
                    {"cid": str(uuid.uuid4()), "firm": owner_a_id, "uid": staff_1_id},
                )
            errors.append("Non-existent client_gstin_id was accepted! Foreign key constraint failed.")
        except Exception:
            fk_enforced = True

        # Step 7: Cross-Tenant Isolation
        cross_tenant_ok = False
        with self._engine.connect() as conn:
            firm_a_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM public.client_assignments WHERE firm_owner_id = :firm"),
                {"firm": owner_a_id},
            ).scalar() or 0
            firm_b_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM public.client_assignments WHERE firm_owner_id = :firm"),
                {"firm": owner_b_id},
            ).scalar() or 0

            # Firm B should have 0 assignments
            if firm_b_count == 0 and firm_a_count >= 3:
                cross_tenant_ok = True
            else:
                errors.append(f"Cross-tenant isolation error: Firm B has {firm_b_count} assignments (expected 0)")

        # Step 8: Idempotent Re-Upgrade Check
        idempotent_ok = False
        try:
            reup = self._runner.run_upgrade()
            idempotent_ok = (len(reup) == 0)
        except Exception as exc:
            errors.append(f"Idempotent upgrade re-run failed: {sanitize_db_error(str(exc))}")

        # Step 9: Downgrade & Archival Safety Test
        downgrade_archival_ok = False
        privilege_escalation_prevented = False
        try:
            reverted = self._runner.run_downgrade(steps=1)
            if reverted and "20261011120000" in reverted:
                with self._engine.connect() as conn:
                    # Check archival tables exist and hold rows
                    ca_archived = conn.execute(
                        sa.text("SELECT COUNT(*) FROM public._archive_client_assignments_rollback")
                    ).scalar() or 0
                    tm_archived = conn.execute(
                        sa.text("SELECT COUNT(*) FROM public._archive_team_member_roles_rollback")
                    ).scalar() or 0

                    if ca_archived >= 3 and tm_archived >= 5:
                        downgrade_archival_ok = True
                    else:
                        errors.append(
                            f"Downgrade archival count low: ca_archived={ca_archived}, tm_archived={tm_archived}"
                        )

                    # Verify viewer account is DEACTIVATED (is_active = FALSE)
                    viewer_records = conn.execute(
                        sa.text("""
                            SELECT tm.is_active, tm.role
                            FROM public.team_members tm
                            JOIN public._archive_team_member_roles_rollback arch
                              ON arch.team_member_id = tm.id
                            WHERE arch.original_role = 'viewer';
                        """)
                    ).fetchall()

                    all_viewers_deactivated = (
                        len(viewer_records) > 0 and all(r[0] is False and r[1] == "staff" for r in viewer_records)
                    )
                    if all_viewers_deactivated:
                        privilege_escalation_prevented = True
                    else:
                        errors.append(
                            f"Viewer privilege escalation: viewer active status = {viewer_records}"
                        )
        except Exception as exc:
            errors.append(f"Downgrade test failed: {sanitize_db_error(str(exc))}")

        # Step 10: Re-Upgrade & Restoration
        reupgrade_restore_ok = False
        try:
            re_up = self._runner.run_upgrade(target_version="20261011120000")
            if re_up:
                # Restore multi-role assignments from archive
                with self._engine.begin() as conn:
                    conn.execute(sa.text("""
                        INSERT INTO public.client_assignments (
                            client_gstin_id, firm_owner_id, user_id, assignment_role, assigned_at, assigned_by
                        )
                        SELECT client_gstin_id, firm_owner_id, user_id, assignment_role, assigned_at, assigned_by
                        FROM public._archive_client_assignments_rollback
                        ON CONFLICT (client_gstin_id, user_id, assignment_role) DO NOTHING;
                    """))
                    restored_count = conn.execute(
                        sa.text("SELECT COUNT(*) FROM public.client_assignments")
                    ).scalar() or 0
                    if restored_count >= 3:
                        reupgrade_restore_ok = True
                    else:
                        errors.append(f"Restoration count low: restored {restored_count}")
        except Exception as exc:
            errors.append(f"Re-upgrade and restoration failed: {sanitize_db_error(str(exc))}")

        all_ok = (len(errors) == 0 and phase31_applied and granular_roles_ok and
                  invalid_role_rejected and duplicate_rejected and fk_enforced and
                  cross_tenant_ok and idempotent_ok and downgrade_archival_ok and
                  privilege_escalation_prevented and reupgrade_restore_ok)

        return ValidationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            target_database=masked_url,
            postgres_version=pg_ver,
            prerequisite_migrations_applied=prereqs_applied,
            pre_upgrade_client_count=pre_clients,
            pre_upgrade_active_assigned_count=pre_active_assigned,
            phase31_applied_successfully=phase31_applied,
            backfill_assignment_count=backfill_count,
            granular_roles_verified=granular_roles_ok,
            invalid_role_rejected=invalid_role_rejected,
            duplicate_assignment_rejected=duplicate_rejected,
            foreign_key_enforced=fk_enforced,
            cross_tenant_isolation_verified=cross_tenant_ok,
            idempotent_reupgrade_verified=idempotent_ok,
            downgrade_archival_verified=downgrade_archival_ok,
            downgrade_privilege_escalation_prevented=privilege_escalation_prevented,
            reupgrade_and_restore_verified=reupgrade_restore_ok,
            all_checks_passed=all_ok,
            errors=errors,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="ReconDesk Staging PostgreSQL Migration Validator")
    parser.add_argument("--database-url", help="PostgreSQL connection string for disposable staging DB")
    args = parser.parse_args()

    import os
    db_url = args.database_url or os.getenv("STAGING_AURORA_DATABASE_URL")
    if not db_url:
        print("ERROR: Staging database URL must be provided via --database-url or STAGING_AURORA_DATABASE_URL env var.", file=sys.stderr)
        return 1

    try:
        verify_staging_database_safety(db_url)
    except StagingSafetyViolationError as exc:
        print(f"CRITICAL SAFETY ERROR: {exc}", file=sys.stderr)
        return 2

    engine = sa.create_engine(db_url)
    validator = StagingMigrationValidator(engine=engine)
    report = validator.execute_validation_cycle()

    import json
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.all_checks_passed else 1


if __name__ == "__main__":
    sys.exit(main())
