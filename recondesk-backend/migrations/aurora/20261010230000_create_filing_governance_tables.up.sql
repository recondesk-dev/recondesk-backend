-- ============================================================================
-- Migration: 20261010230000_create_filing_governance_tables.up.sql
-- Description: Phase 2 - Filing Governance Policies and Single-Use Partner Overrides
--              Enforces server-side pre-filing compliance, auditability, and tamper-resistance.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.filing_governance_policies
CREATE TABLE IF NOT EXISTS public.filing_governance_policies (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                         UUID NOT NULL UNIQUE REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    mode                            VARCHAR(50) NOT NULL DEFAULT 'ADVISORY'
                                    CHECK (mode IN ('ADVISORY', 'PARTNER_OVERRIDE', 'STRICT_BLOCK')),
    rule_88c_amount_threshold      NUMERIC NOT NULL DEFAULT 2500000.0,
    rule_88c_pct_threshold         NUMERIC NOT NULL DEFAULT 20.0,
    rule_88d_amount_threshold      NUMERIC NOT NULL DEFAULT 2500000.0,
    rule_88d_pct_threshold         NUMERIC NOT NULL DEFAULT 20.0,
    require_final_reconciliation    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by                      UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_filing_governance_policies_firm
    ON public.filing_governance_policies (firm_id);

COMMENT ON TABLE public.filing_governance_policies IS
    'Firm-configurable filing compliance policy (ADVISORY, PARTNER_OVERRIDE, STRICT_BLOCK).';


-- 2. Table: public.filing_overrides
CREATE TABLE IF NOT EXISTS public.filing_overrides (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id                 UUID REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    return_type                     VARCHAR(50) NOT NULL,
    figures_digest                  VARCHAR(64) NOT NULL,
    validation_digest               VARCHAR(64) NOT NULL DEFAULT '',
    justification                   TEXT NOT NULL,
    approved_by                     UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    approver_name                   VARCHAR(255) NOT NULL,
    approver_role                   VARCHAR(50) NOT NULL,
    violations_acknowledged         JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_consumed                     BOOLEAN NOT NULL DEFAULT FALSE,
    consumed_at                     TIMESTAMPTZ,
    consumed_run_id                 UUID,
    expires_at                      TIMESTAMPTZ NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_filing_overrides_lookup
    ON public.filing_overrides (firm_id, client_gstin_id, period, return_type, is_consumed, expires_at);

CREATE INDEX IF NOT EXISTS idx_filing_overrides_digest
    ON public.filing_overrides (figures_digest);

COMMENT ON TABLE public.filing_overrides IS
    'Single-use, partner-authorized overrides for filing return with critical statutory/reconciliation violations.';
