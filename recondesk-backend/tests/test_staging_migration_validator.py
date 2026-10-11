"""Tests for Staging Aurora PostgreSQL Migration Validator (Phase 3.1).

Verifies:
1. Safety gate strictly fails closed when pointed at production Aurora cluster.
2. Safety gate permits disposable staging and local PostgreSQL URLs.
3. ValidationReport serialization and structure.
4. Simulated validation cycle execution and error reporting.
"""

from __future__ import annotations

import pytest

from app.scripts.validate_aurora_staging_migration import (
    StagingSafetyViolationError,
    ValidationReport,
    verify_staging_database_safety,
)


class TestStagingSafetyEnforcement:
    def test_production_aurora_url_is_strictly_blocked(self):
        """Production Aurora cluster hostname must raise StagingSafetyViolationError."""
        prod_url = (
            "postgresql+psycopg2://admin:pass@"
            "recondesk.cluster-cre2mcouo1xv.ap-south-1.rds.amazonaws.com:5432/recondesk?sslmode=require"
        )
        with pytest.raises(StagingSafetyViolationError, match="SAFETY BLOCK"):
            verify_staging_database_safety(prod_url)

    def test_production_path_is_strictly_blocked(self):
        """Database name containing 'production' must be rejected."""
        prod_db_url = "postgresql://user:pass@staging-server:5432/recondesk_production"
        with pytest.raises(StagingSafetyViolationError, match="SAFETY BLOCK"):
            verify_staging_database_safety(prod_db_url)

    def test_staging_url_is_permitted(self):
        """Valid disposable staging database URLs pass safety check."""
        staging_url = "postgresql://test_user:pass@staging-rds.internal:5432/recondesk_staging_test"
        # Must not raise
        verify_staging_database_safety(staging_url)

        local_url = "postgresql://postgres:postgres@localhost:5432/recondesk_test_disposable"
        verify_staging_database_safety(local_url)


class TestValidationReportModel:
    def test_report_serialization(self):
        """ValidationReport converts to dict and tracks all check statuses."""
        rep = ValidationReport(
            timestamp="2026-10-11T00:00:00Z",
            target_database="postgresql://test:***@localhost:5432/test",
            postgres_version="PostgreSQL 16.1",
            prerequisite_migrations_applied=5,
            pre_upgrade_client_count=4,
            pre_upgrade_active_assigned_count=2,
            phase31_applied_successfully=True,
            backfill_assignment_count=2,
            granular_roles_verified=True,
            invalid_role_rejected=True,
            duplicate_assignment_rejected=True,
            foreign_key_enforced=True,
            cross_tenant_isolation_verified=True,
            idempotent_reupgrade_verified=True,
            downgrade_archival_verified=True,
            downgrade_privilege_escalation_prevented=True,
            reupgrade_and_restore_verified=True,
            all_checks_passed=True,
            errors=[],
        )
        data = rep.to_dict()
        assert data["all_checks_passed"] is True
        assert data["backfill_assignment_count"] == 2
        assert len(data["errors"]) == 0
