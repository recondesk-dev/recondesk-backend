-- ============================================================================
-- Migration: 20261003150000_create_batch2a_compliance_tables.up.sql
-- Description: Phase 9D-1 (Batch 2A) - Compliance & Resolution Tracking:
--              mismatch_notes, reconciliation_exception_dispositions,
--              invoice_tracking, rule37_actions, rule37_resolutions,
--              rule37_alert_dedup, indexes, triggers, and permissions.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.mismatch_notes
-- User notes and resolution comments on discrepancy records.
CREATE TABLE IF NOT EXISTS public.mismatch_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id UUID NOT NULL,
    record_type TEXT NOT NULL,
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    note TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT DEFAULT 'pending',
    CONSTRAINT mismatch_notes_record_type_check CHECK (record_type IN ('gstr', 'pr'))
);

CREATE INDEX IF NOT EXISTS idx_mismatch_notes_record_id
    ON public.mismatch_notes (record_id);

CREATE INDEX IF NOT EXISTS idx_mismatch_notes_run_id
    ON public.mismatch_notes (run_id);

COMMENT ON TABLE public.mismatch_notes IS 'Notes and manual disposition comments on mismatch items';


-- 2. Table: public.reconciliation_exception_dispositions
-- Statutory dispositions applied to reconciliation discrepancies impacting Table 4 calculations.
CREATE TABLE IF NOT EXISTS public.reconciliation_exception_dispositions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    record_id TEXT NOT NULL,
    exception_type VARCHAR(50) NOT NULL,
    disposition VARCHAR(50) NOT NULL,
    eligibility_effect VARCHAR(30) NOT NULL,
    table4_effect VARCHAR(30) NOT NULL,
    reason TEXT NOT NULL,
    reference_doc VARCHAR(100),
    statutory_reference VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    CONSTRAINT uq_exception_disposition UNIQUE (run_id, record_id, exception_type)
);

CREATE INDEX IF NOT EXISTS idx_exception_disp_run_id
    ON public.reconciliation_exception_dispositions (run_id);

COMMENT ON TABLE public.reconciliation_exception_dispositions IS 'Statutory exception dispositions affecting Table 4 outcomes';


-- 3. Table: public.invoice_tracking
-- Multi-period cross-run tracking of unmatched invoices to detect chronic non-compliance.
CREATE TABLE IF NOT EXISTS public.invoice_tracking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL,
    supplier_gstin TEXT NOT NULL,
    taxable_amount BIGINT NOT NULL,
    first_seen_run_id UUID NOT NULL REFERENCES public.reconciliation_run(id),
    last_seen_run_id UUID NOT NULL REFERENCES public.reconciliation_run(id),
    consecutive_unmatched_runs INTEGER NOT NULL DEFAULT 1,
    last_match_status TEXT NOT NULL,
    is_resolved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_invoice_tracking_unique
    ON public.invoice_tracking (client_gstin_id, invoice_number, supplier_gstin);

CREATE INDEX IF NOT EXISTS idx_invoice_tracking_client
    ON public.invoice_tracking (client_gstin_id);

CREATE INDEX IF NOT EXISTS idx_invoice_tracking_unresolved
    ON public.invoice_tracking (client_gstin_id, is_resolved)
    WHERE (is_resolved = false);

CREATE OR REPLACE FUNCTION public.set_invoice_tracking_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_invoice_tracking_updated_at ON public.invoice_tracking;
CREATE TRIGGER trg_invoice_tracking_updated_at
    BEFORE UPDATE ON public.invoice_tracking
    FOR EACH ROW EXECUTE FUNCTION public.set_invoice_tracking_updated_at();

COMMENT ON TABLE public.invoice_tracking IS 'Cross-run invoice tracking for multi-period unmatched ageing and carry-forward';


-- 4. Table: public.rule37_actions
-- 180-day non-payment dispositions, TDS deductions, payment settlements.
-- Note: run_id holds reconciliation_run or reconciliation_import_run identifiers; user_id is bare UUID.
CREATE TABLE IF NOT EXISTS public.rule37_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    record_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_id UUID,
    tds_deducted NUMERIC(15,2) NOT NULL DEFAULT 0,
    tds_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    total_settled NUMERIC(15,2),
    amount_paid NUMERIC(15,2),
    remaining_unpaid_amount NUMERIC(15,2),
    payment_coverage TEXT,
    source TEXT,
    settled_date DATE,
    CONSTRAINT rule37_actions_run_id_record_hash_key UNIQUE (run_id, record_hash)
);

CREATE INDEX IF NOT EXISTS idx_rule37_actions_run_id
    ON public.rule37_actions (run_id);

COMMENT ON TABLE public.rule37_actions IS 'Rule 37 180-day action dispositions and settlement tracking';


-- 5. Table: public.rule37_resolutions
-- Resolution records for resolved Rule 37 action items.
-- Note: resolved_by holds auth user UUID without strict foreign key to user_profiles.
CREATE TABLE IF NOT EXISTS public.rule37_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    invoice_result_id TEXT NOT NULL,
    resolved_by UUID NOT NULL,
    resolved_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_rule37_resolutions_run_id
    ON public.rule37_resolutions (run_id);

COMMENT ON TABLE public.rule37_resolutions IS 'Resolution records for Rule 37 invoice items';


-- 6. Table: public.rule37_alert_dedup
-- Alert tier deduplication preventing repeated 180-day warning alerts.
CREATE TABLE IF NOT EXISTS public.rule37_alert_dedup (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    invoice_key TEXT NOT NULL,
    last_alert_tier TEXT NOT NULL,
    last_sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT rule37_alert_dedup_client_invoice_unique UNIQUE (client_gstin_id, invoice_key),
    CONSTRAINT rule37_alert_dedup_tier_check CHECK (last_alert_tier IN (
        'WARNING_60_DAYS', 'WARNING_30_DAYS', 'OVERDUE_UNPAID'
    ))
);

CREATE INDEX IF NOT EXISTS idx_rule37_alert_dedup_firm_owner
    ON public.rule37_alert_dedup (firm_owner_id);

CREATE INDEX IF NOT EXISTS idx_rule37_alert_dedup_last_sent
    ON public.rule37_alert_dedup (last_sent_at);

COMMENT ON TABLE public.rule37_alert_dedup IS 'Alert tier deduplication for Rule 37 180-day vendor payment notifications';


-- 7. Role Permissions
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.mismatch_notes TO service_role;
        GRANT ALL ON TABLE public.reconciliation_exception_dispositions TO service_role;
        GRANT ALL ON TABLE public.invoice_tracking TO service_role;
        GRANT ALL ON TABLE public.rule37_actions TO service_role;
        GRANT ALL ON TABLE public.rule37_resolutions TO service_role;
        GRANT ALL ON TABLE public.rule37_alert_dedup TO service_role;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.mismatch_notes TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.reconciliation_exception_dispositions TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.invoice_tracking TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.rule37_actions TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.rule37_resolutions TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.rule37_alert_dedup TO authenticated;
    END IF;
END;
$$;
