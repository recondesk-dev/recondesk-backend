-- ============================================================================
-- Migration: 20261011220000_create_maker_checker_approvals.sql
-- Description: Phase 3.2 - Maker-Checker Return Filing Approvals (Supabase)
-- ============================================================================

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

ALTER TABLE public.return_filing_approvals DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.return_approval_audit_trail DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.return_filing_approvals TO service_role;
GRANT ALL ON public.return_approval_audit_trail TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.return_filing_approvals TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.return_approval_audit_trail TO authenticated;
