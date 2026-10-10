-- Filing Governance Policies and Single-Use Partner Overrides
-- Enforces server-side pre-filing compliance, auditability, and tamper-resistance.

CREATE TABLE IF NOT EXISTS public.filing_governance_policies (
    id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                         uuid NOT NULL UNIQUE REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    mode                            text NOT NULL DEFAULT 'ADVISORY'
                                    CHECK (mode IN ('ADVISORY', 'PARTNER_OVERRIDE', 'STRICT_BLOCK')),
    rule_88c_amount_threshold      numeric NOT NULL DEFAULT 2500000.0,
    rule_88c_pct_threshold         numeric NOT NULL DEFAULT 20.0,
    rule_88d_amount_threshold      numeric NOT NULL DEFAULT 2500000.0,
    rule_88d_pct_threshold         numeric NOT NULL DEFAULT 20.0,
    require_final_reconciliation    boolean NOT NULL DEFAULT true,
    created_at                      timestamptz NOT NULL DEFAULT now(),
    updated_at                      timestamptz NOT NULL DEFAULT now(),
    updated_by                      uuid REFERENCES public.user_profiles (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_filing_governance_policies_firm
    ON public.filing_governance_policies (firm_id);

COMMENT ON TABLE public.filing_governance_policies IS
    'Firm-configurable filing compliance policy (ADVISORY, PARTNER_OVERRIDE, STRICT_BLOCK).';


CREATE TABLE IF NOT EXISTS public.filing_overrides (
    id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                         uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id                 uuid REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    gstin                           text NOT NULL,
    period                          varchar(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    return_type                     text NOT NULL,
    figures_digest                  text NOT NULL,
    validation_digest               text NOT NULL DEFAULT '',
    justification                   text NOT NULL,
    approved_by                     uuid REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    approver_name                   text NOT NULL,
    approver_role                   text NOT NULL,
    violations_acknowledged         jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_consumed                     boolean NOT NULL DEFAULT false,
    consumed_at                     timestamptz,
    consumed_run_id                 uuid REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    expires_at                      timestamptz NOT NULL,
    created_at                      timestamptz NOT NULL DEFAULT now(),
    updated_at                      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filing_overrides_lookup
    ON public.filing_overrides (firm_id, client_gstin_id, period, return_type, is_consumed, expires_at);

CREATE INDEX IF NOT EXISTS idx_filing_overrides_digest
    ON public.filing_overrides (figures_digest);

ALTER TABLE public.filing_governance_policies DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.filing_overrides DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.filing_governance_policies TO service_role;
GRANT ALL ON public.filing_overrides TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.filing_governance_policies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.filing_overrides TO authenticated;
