-- ============================================================================
-- Migration: 20261003100000_create_wizard_ingestion_tables.up.sql
-- Description: Phase 9B (Batch 1) - Ingestion & Wizard Pipeline:
--              client_import_mappings, reconciliation_import_runs,
--              reconciliation_import_run_audit_log, indexes, and updated_at triggers.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.client_import_mappings
-- Saved PR column -> standard-field mappings per client_gstin_id.
CREATE TABLE IF NOT EXISTS public.client_import_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    source_column_name TEXT NOT NULL,
    target_field TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT client_import_mappings_client_target_unique UNIQUE (client_gstin_id, target_field),
    CONSTRAINT client_import_mappings_target_field_check CHECK (target_field IN (
        'gstin', 'invoice_number', 'invoice_date', 'taxable_value',
        'cgst', 'sgst', 'igst', 'cess'
    ))
);

CREATE INDEX IF NOT EXISTS client_import_mappings_client_gstin_id_idx
    ON public.client_import_mappings (client_gstin_id);

CREATE OR REPLACE FUNCTION public.set_client_import_mappings_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_client_import_mappings_updated_at ON public.client_import_mappings;
CREATE TRIGGER trg_client_import_mappings_updated_at
    BEFORE UPDATE ON public.client_import_mappings
    FOR EACH ROW EXECUTE FUNCTION public.set_client_import_mappings_updated_at();

COMMENT ON TABLE public.client_import_mappings IS 'Saved PR column -> standard-field mappings per client_gstin_id';


-- 2. Table: public.reconciliation_import_runs
-- Multi-step GSTR-2B + PR import wizard state.
-- NOTE: created_by is a bare UUID without FK to user_profiles; historical rows
-- contain non-user UUIDs from test runs, exactly matching Supabase DDL.
CREATE TABLE IF NOT EXISTS public.reconciliation_import_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    firm_owner_id UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    period DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft', 'gstr_uploaded', 'pr_uploaded', 'pending', 'processing',
            'complete', 'error', 'cancelled'
        )),
    current_step INTEGER NOT NULL DEFAULT 1
        CHECK (current_step BETWEEN 1 AND 4),
    gstr2b_r2_key TEXT,
    gstr2b_file_name TEXT,
    gstr2b_file_size INTEGER,
    gstr2b_file_hash TEXT,
    gstr2b_uploaded_at TIMESTAMPTZ,
    gstr2b_record_count INTEGER DEFAULT 0,
    sanity_check_results JSONB,
    pr_r2_key TEXT,
    pr_file_name TEXT,
    pr_file_size INTEGER,
    pr_file_hash TEXT,
    pr_uploaded_at TIMESTAMPTZ,
    pr_record_count INTEGER DEFAULT 0,
    column_mapping JSONB,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    progress_pct INTEGER NOT NULL DEFAULT 0,
    status_message TEXT,
    error_detail TEXT,
    pr_column_headers JSONB,
    gstr2b_deleted_at TIMESTAMPTZ,
    pr_deleted_at TIMESTAMPTZ,
    itc_claimed_period DATE,
    run_summary JSONB
);

CREATE INDEX IF NOT EXISTS reconciliation_import_runs_client_id_idx
    ON public.reconciliation_import_runs (client_id);

CREATE UNIQUE INDEX IF NOT EXISTS reconciliation_import_runs_one_active_per_client_period
    ON public.reconciliation_import_runs (client_id, period)
    WHERE (status NOT IN ('complete', 'cancelled', 'error'));

CREATE OR REPLACE FUNCTION public.set_reconciliation_import_runs_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reconciliation_import_runs_updated_at ON public.reconciliation_import_runs;
CREATE TRIGGER trg_reconciliation_import_runs_updated_at
    BEFORE UPDATE ON public.reconciliation_import_runs
    FOR EACH ROW EXECUTE FUNCTION public.set_reconciliation_import_runs_updated_at();

COMMENT ON TABLE public.reconciliation_import_runs IS 'Multi-step GSTR-2B + PR import wizard state';
COMMENT ON COLUMN public.reconciliation_import_runs.itc_claimed_period IS 'Optional YYYY-MM (stored as first-of-month date): GSTR-3B period when ITC for this PR batch was claimed. Used as Rule 37(3) interest proxy via following-month 20th due date.';


-- 3. Table: public.reconciliation_import_run_audit_log
-- Audit trail for wizard actions and status transitions.
CREATE TABLE IF NOT EXISTS public.reconciliation_import_run_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_import_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    event TEXT NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS reconciliation_import_run_audit_log_run_id_idx
    ON public.reconciliation_import_run_audit_log (run_id);

COMMENT ON TABLE public.reconciliation_import_run_audit_log IS 'Audit trail for wizard actions and status transitions';


-- 4. Role Permissions
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.client_import_mappings TO service_role;
        GRANT ALL ON TABLE public.reconciliation_import_runs TO service_role;
        GRANT ALL ON TABLE public.reconciliation_import_run_audit_log TO service_role;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.client_import_mappings TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.reconciliation_import_runs TO authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.reconciliation_import_run_audit_log TO authenticated;
    END IF;
END;
$$;
