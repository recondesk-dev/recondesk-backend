-- ============================================================================
-- Migration: 20261011120000_create_client_assignments_and_granular_roles.down.sql
-- Description: Phase 3.1 - Safe Non-Destructive Rollback of Granular RBAC & Client Assignments
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration (e.g. `aws rds restore-db-cluster-to-point-in-time`).
-- Schema downgrades on live databases risk breaking transactional invariants
-- and data integrity if downstream applications or users wrote data under Phase 3.1.
--
-- This script provides a NON-DESTRUCTIVE rollback pattern for staging/dev environments:
-- 1. Archives all multi-role assignments into `_archive_client_assignments_rollback`.
-- 2. Archives all team member role transitions into `_archive_team_member_roles_rollback`.
-- 3. Prevents privilege escalation: read-only 'viewer' accounts are deactivated
--    (is_active = FALSE) rather than promoted to active 'staff' (which possesses write permissions).
-- 4. Re-enforces legacy CHECK constraint ('admin', 'staff') without losing data.
-- ============================================================================

-- 1. Archive client_assignments before table removal to prevent permanent data loss
CREATE TABLE IF NOT EXISTS public._archive_client_assignments_rollback (
    archive_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID NOT NULL,
    client_gstin_id UUID NOT NULL,
    firm_owner_id UUID NOT NULL,
    user_id UUID NOT NULL,
    assignment_role VARCHAR(50) NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL,
    assigned_by UUID,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public._archive_client_assignments_rollback (
    assignment_id, client_gstin_id, firm_owner_id, user_id, assignment_role, assigned_at, assigned_by
)
SELECT id, client_gstin_id, firm_owner_id, user_id, assignment_role, assigned_at, assigned_by
FROM public.client_assignments
ON CONFLICT (archive_id) DO NOTHING;

-- Safely drop active client_assignments table now that records are fully archived
DROP TABLE IF EXISTS public.client_assignments CASCADE;

-- 2. Archive existing team member roles before modifying team_members
CREATE TABLE IF NOT EXISTS public._archive_team_member_roles_rollback (
    archive_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_member_id UUID NOT NULL,
    firm_owner_id UUID NOT NULL,
    member_user_id UUID,
    original_role VARCHAR(50) NOT NULL,
    original_is_active BOOLEAN NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public._archive_team_member_roles_rollback (
    team_member_id, firm_owner_id, member_user_id, original_role, original_is_active
)
SELECT id, firm_owner_id, member_user_id, role, is_active
FROM public.team_members
WHERE role NOT IN ('admin', 'staff');

-- 3. Remap granular roles to legacy roles before restoring constraint
-- CRITICAL SECURITY FIX: Prevent privilege escalation.
-- Legacy code grants write permissions to all active 'staff' (is_writer_or_above("staff") == True).
-- Remapping a read-only 'viewer' to active 'staff' would grant unauthorized write access!
-- Therefore, any user with role 'viewer' MUST be deactivated (is_active = FALSE)
-- to fail closed and prevent unauthorized writes.
UPDATE public.team_members
SET
    role = CASE
        WHEN role IN ('owner', 'partner') THEN 'admin'
        WHEN role IN ('manager', 'preparer') THEN 'staff'
        ELSE 'staff'
    END,
    is_active = CASE
        WHEN role = 'viewer' THEN FALSE
        ELSE is_active
    END
WHERE role NOT IN ('admin', 'staff');

-- 4. Restore legacy check constraint
ALTER TABLE public.team_members DROP CONSTRAINT IF EXISTS ck_team_members_role;
ALTER TABLE public.team_members DROP CONSTRAINT IF EXISTS team_members_role_check;
ALTER TABLE public.team_members ADD CONSTRAINT ck_team_members_role
    CHECK (role IN ('admin', 'staff'));
