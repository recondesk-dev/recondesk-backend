-- ============================================================================
-- Migration: 20261011220000_create_maker_checker_approvals.up.sql
-- Description: Phase 3.2 - Maker-Checker Return Filing Approvals
--              Introduces durable return approval lifecycle and tamper-evident audit trail.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.return_filing_approvals
CREATE TABLE IF NOT EXISTS public.return_filing_approvals (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id                 UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    return_type                     VARCHAR(20) NOT NULL CHECK (return_type IN ('GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C')),
    status                          VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                                    CHECK (status IN (
                                        'DRAFT',
                                        'PREPARED',
                                        'UNDER_REVIEW',
                                        'APPROVED',
                                        'REJECTED',
                                        'SAVED',
                                        'OFFSET_COMPLETE',
                                        'FILED'
                                    )),
    figures_digest                  VARCHAR(64) NOT NULL DEFAULT '',
    validation_digest               VARCHAR(64) NOT NULL DEFAULT '',
    figures_summary                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    preparer_id                     UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    preparer_name                   VARCHAR(255) NOT NULL DEFAULT '',
    preparer_role                   VARCHAR(50) NOT NULL DEFAULT '',
    prepared_at                     TIMESTAMPTZ,
    submission_notes                TEXT DEFAULT '',
    approver_id                     UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    approver_name                   VARCHAR(255) NOT NULL DEFAULT '',
    approver_role                   VARCHAR(50) NOT NULL DEFAULT '',
    approved_at                     TIMESTAMPTZ,
    approval_notes                  TEXT DEFAULT '',
    rejected_by                     UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    rejected_by_name                VARCHAR(255) NOT NULL DEFAULT '',
    rejected_by_role                VARCHAR(50) NOT NULL DEFAULT '',
    rejected_at                     TIMESTAMPTZ,
    rejection_reason                TEXT DEFAULT '',
    filing_run_id                   UUID REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_return_filing_approvals UNIQUE (firm_id, client_gstin_id, period, return_type)
);

CREATE INDEX IF NOT EXISTS idx_return_approvals_lookup
    ON public.return_filing_approvals (firm_id, client_gstin_id, period, return_type);

CREATE INDEX IF NOT EXISTS idx_return_approvals_status
    ON public.return_filing_approvals (status);

CREATE INDEX IF NOT EXISTS idx_return_approvals_digest
    ON public.return_filing_approvals (figures_digest);

COMMENT ON TABLE public.return_filing_approvals IS
    'Durable maker-checker approval state for GST returns (GSTR-1, GSTR-3B).';


-- 2. Table: public.return_approval_audit_trail
CREATE TABLE IF NOT EXISTS public.return_approval_audit_trail (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id                     UUID NOT NULL REFERENCES public.return_filing_approvals (id) ON DELETE CASCADE,
    firm_id                         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id                 UUID REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL,
    return_type                     VARCHAR(20) NOT NULL,
    action                          VARCHAR(50) NOT NULL,
    from_status                     VARCHAR(30),
    to_status                       VARCHAR(30) NOT NULL,
    actor_id                        UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name                      VARCHAR(255) NOT NULL DEFAULT '',
    actor_role                      VARCHAR(50) NOT NULL DEFAULT '',
    figures_digest                  VARCHAR(64) NOT NULL DEFAULT '',
    notes                           TEXT DEFAULT '',
    rejection_reason                TEXT DEFAULT '',
    metadata                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_return_audit_approval
    ON public.return_approval_audit_trail (approval_id);

CREATE INDEX IF NOT EXISTS idx_return_audit_firm
    ON public.return_approval_audit_trail (firm_id, created_at DESC);

COMMENT ON TABLE public.return_approval_audit_trail IS
    'Immutable tenant-scoped audit log for all maker-checker return filing approval actions.';


-- 3. Non-Destructive Restoration from Rollback Archives (if present)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_return_filing_approvals_rollback'
    ) THEN
        INSERT INTO public.return_filing_approvals (
            id, firm_id, client_gstin_id, gstin, period, return_type,
            status, figures_digest, validation_digest, figures_summary,
            preparer_id, preparer_name, preparer_role, prepared_at, submission_notes,
            approver_id, approver_name, approver_role, approved_at, approval_notes,
            rejected_by, rejected_by_name, rejected_by_role, rejected_at, rejection_reason,
            filing_run_id, created_at, updated_at
        )
        SELECT approval_id, firm_id, client_gstin_id, gstin, period, return_type,
               status, figures_digest, validation_digest, figures_summary,
               preparer_id, preparer_name, preparer_role, prepared_at, submission_notes,
               approver_id, approver_name, approver_role, approved_at, approval_notes,
               rejected_by, rejected_by_name, rejected_by_role, rejected_at, rejection_reason,
               filing_run_id, created_at, updated_at
        FROM public._archive_return_filing_approvals_rollback
        ON CONFLICT (firm_id, client_gstin_id, period, return_type) DO NOTHING;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_return_approval_audit_trail_rollback'
    ) THEN
        INSERT INTO public.return_approval_audit_trail (
            id, approval_id, firm_id, client_gstin_id, gstin, period, return_type,
            action, from_status, to_status, actor_id, actor_name, actor_role,
            figures_digest, notes, rejection_reason, metadata, created_at
        )
        SELECT entry_id, approval_id, firm_id, client_gstin_id, gstin, period, return_type,
               action, from_status, to_status, actor_id, actor_name, actor_role,
               figures_digest, notes, rejection_reason, metadata, created_at
        FROM public._archive_return_approval_audit_trail_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;
END $$;

