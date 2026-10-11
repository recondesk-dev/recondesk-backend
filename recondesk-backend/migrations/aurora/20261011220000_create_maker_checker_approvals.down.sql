-- ============================================================================
-- Migration: 20261011220000_create_maker_checker_approvals.down.sql
-- Description: Phase 3.2 - Safe Non-Destructive Rollback of Maker-Checker Return Approvals
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration (e.g. `aws rds restore-db-cluster-to-point-in-time`).
-- Schema downgrades on live databases risk breaking transactional invariants
-- and statutory compliance if downstream applications or users wrote approvals
-- under Phase 3.2.
--
-- This script provides a NON-DESTRUCTIVE rollback pattern for staging/dev environments:
-- 1. Archives all audit trail history into `_archive_return_approval_audit_trail_rollback`.
-- 2. Archives all return filing approvals into `_archive_return_filing_approvals_rollback`.
-- 3. Safely drops active tables only after records are durably archived.
-- ============================================================================

-- 1. Archive return_approval_audit_trail before table removal to prevent permanent audit loss
CREATE TABLE IF NOT EXISTS public._archive_return_approval_audit_trail_rollback (
    archive_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id                        UUID NOT NULL,
    approval_id                     UUID NOT NULL,
    firm_id                         UUID NOT NULL,
    client_gstin_id                 UUID,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL,
    return_type                     VARCHAR(20) NOT NULL,
    action                          VARCHAR(50) NOT NULL,
    from_status                     VARCHAR(30),
    to_status                       VARCHAR(30) NOT NULL,
    actor_id                        UUID,
    actor_name                      VARCHAR(255) NOT NULL,
    actor_role                      VARCHAR(50) NOT NULL,
    figures_digest                  VARCHAR(64) NOT NULL,
    notes                           TEXT,
    rejection_reason                TEXT,
    metadata                        JSONB,
    created_at                      TIMESTAMPTZ NOT NULL,
    archived_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public._archive_return_approval_audit_trail_rollback (
    entry_id, approval_id, firm_id, client_gstin_id, gstin, period, return_type,
    action, from_status, to_status, actor_id, actor_name, actor_role,
    figures_digest, notes, rejection_reason, metadata, created_at
)
SELECT id, approval_id, firm_id, client_gstin_id, gstin, period, return_type,
       action, from_status, to_status, actor_id, actor_name, actor_role,
       figures_digest, notes, rejection_reason, metadata, created_at
FROM public.return_approval_audit_trail
ON CONFLICT (archive_id) DO NOTHING;

-- 2. Archive return_filing_approvals before table removal to prevent permanent approvals loss
CREATE TABLE IF NOT EXISTS public._archive_return_filing_approvals_rollback (
    archive_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id                     UUID NOT NULL,
    firm_id                         UUID NOT NULL,
    client_gstin_id                 UUID NOT NULL,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL,
    return_type                     VARCHAR(20) NOT NULL,
    status                          VARCHAR(30) NOT NULL,
    figures_digest                  VARCHAR(64) NOT NULL,
    validation_digest               VARCHAR(64) NOT NULL,
    figures_summary                 JSONB NOT NULL,
    preparer_id                     UUID,
    preparer_name                   VARCHAR(255) NOT NULL,
    preparer_role                   VARCHAR(50) NOT NULL,
    prepared_at                     TIMESTAMPTZ,
    submission_notes                TEXT,
    approver_id                     UUID,
    approver_name                   VARCHAR(255) NOT NULL,
    approver_role                   VARCHAR(50) NOT NULL,
    approved_at                     TIMESTAMPTZ,
    approval_notes                  TEXT,
    rejected_by                     UUID,
    rejected_by_name                VARCHAR(255) NOT NULL,
    rejected_by_role                VARCHAR(50) NOT NULL,
    rejected_at                     TIMESTAMPTZ,
    rejection_reason                TEXT,
    filing_run_id                   UUID,
    created_at                      TIMESTAMPTZ NOT NULL,
    updated_at                      TIMESTAMPTZ NOT NULL,
    archived_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public._archive_return_filing_approvals_rollback (
    approval_id, firm_id, client_gstin_id, gstin, period, return_type,
    status, figures_digest, validation_digest, figures_summary,
    preparer_id, preparer_name, preparer_role, prepared_at, submission_notes,
    approver_id, approver_name, approver_role, approved_at, approval_notes,
    rejected_by, rejected_by_name, rejected_by_role, rejected_at, rejection_reason,
    filing_run_id, created_at, updated_at
)
SELECT id, firm_id, client_gstin_id, gstin, period, return_type,
       status, figures_digest, validation_digest, figures_summary,
       preparer_id, preparer_name, preparer_role, prepared_at, submission_notes,
       approver_id, approver_name, approver_role, approved_at, approval_notes,
       rejected_by, rejected_by_name, rejected_by_role, rejected_at, rejection_reason,
       filing_run_id, created_at, updated_at
FROM public.return_filing_approvals
ON CONFLICT (archive_id) DO NOTHING;

-- 3. Safely drop active tables now that records are fully archived
DROP TABLE IF EXISTS public.return_approval_audit_trail CASCADE;
DROP TABLE IF EXISTS public.return_filing_approvals CASCADE;
