-- Migration: 20261009100000_create_batch3c_filing_automation.up.sql
-- Description: Create Batch 3C Government Portal Filing Automation & Bulk Return Processing Tables
-- Target: AWS Aurora PostgreSQL

-- ============================================================================
-- 1. filing_sessions
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.filing_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    client_gstin_id UUID REFERENCES public.client_gstins(id) ON DELETE SET NULL,
    gstin TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    session_token TEXT NOT NULL,
    token_expires_at TIMESTAMPTZ NOT NULL,
    session_expires_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active'
        CONSTRAINT filing_sessions_status_chk
        CHECK (status IN ('active', 'expired', 'logged_out')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    logged_out_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_filing_sessions_firm_gstin
    ON public.filing_sessions(firm_id, gstin);

CREATE INDEX IF NOT EXISTS idx_filing_sessions_firm_active
    ON public.filing_sessions(firm_id, status, token_expires_at DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_filing_sessions_client_gstin
    ON public.filing_sessions(client_gstin_id)
    WHERE client_gstin_id IS NOT NULL;

COMMENT ON TABLE public.filing_sessions IS
    'Sandbox taxpayer OTP session (~6hr access token). Shared by GSTR filing and IMS actions.';

-- ============================================================================
-- 2. filing_runs
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.filing_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    client_gstin_id UUID REFERENCES public.client_gstins(id) ON DELETE SET NULL,
    filing_session_id UUID REFERENCES public.filing_sessions(id) ON DELETE SET NULL,
    gstin TEXT NOT NULL,
    return_type TEXT NOT NULL
        CONSTRAINT filing_runs_return_type_chk
        CHECK (return_type IN ('gstr-1', 'gstr-1a', 'gstr-3b', 'gstr-9', 'other')),
    period VARCHAR(7) NOT NULL
        CONSTRAINT filing_runs_period_chk
        CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status TEXT NOT NULL DEFAULT 'draft'
        CONSTRAINT filing_runs_status_chk
        CHECK (status IN (
            'draft',
            'save_pending',
            'saved',
            'save_failed',
            'offset_pending',
            'offset_complete',
            'offset_failed',
            'proceeded',
            'evc_pending',
            'filed',
            'failed'
        )),
    reference_id TEXT,
    ack_number TEXT,
    arn TEXT,
    filing_method TEXT,
    filed_at TIMESTAMPTZ,
    save_payload JSONB,
    raw_response JSONB,
    error_code TEXT,
    error_message TEXT,
    offset_payload JSONB,
    offset_completed_at TIMESTAMPTZ,
    tx_pmt_snapshot JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_filing_runs_firm_period
    ON public.filing_runs(firm_id, return_type, period, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_filing_runs_gstin_period
    ON public.filing_runs(gstin, return_type, period, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_filing_runs_session
    ON public.filing_runs(filing_session_id)
    WHERE filing_session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_filing_runs_gstr3b_offset_gate
    ON public.filing_runs(gstin, period, status)
    WHERE return_type = 'gstr-3b'
      AND status IN ('offset_complete', 'evc_pending', 'filed');

COMMENT ON TABLE public.filing_runs IS
    'One Save/Offset/File attempt for a return type and period; stores raw GSTN envelopes and lock proofs.';

-- ============================================================================
-- 3. filing_batches
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.filing_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    return_type TEXT NOT NULL DEFAULT 'gstr-1'
        CONSTRAINT filing_batches_return_type_chk
        CHECK (return_type IN ('gstr-1')),
    period VARCHAR(7) NOT NULL
        CONSTRAINT filing_batches_period_chk
        CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status TEXT NOT NULL DEFAULT 'pending'
        CONSTRAINT filing_batches_status_chk
        CHECK (status IN (
            'pending',
            'in_progress',
            'completed',
            'partially_completed',
            'failed',
            'cancelled'
        )),
    total_count INTEGER NOT NULL DEFAULT 0,
    saved_count INTEGER NOT NULL DEFAULT 0,
    evc_pending_count INTEGER NOT NULL DEFAULT 0,
    filed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_filing_batches_firm_period
    ON public.filing_batches(firm_id, return_type, period, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_filing_batches_status
    ON public.filing_batches(status);

COMMENT ON TABLE public.filing_batches IS
    'Header record for multi-GSTIN bulk return preparation and filing jobs.';

-- ============================================================================
-- 4. filing_batch_items
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.filing_batch_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES public.filing_batches(id) ON DELETE CASCADE,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    gstin TEXT NOT NULL,
    filing_run_id UUID REFERENCES public.filing_runs(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CONSTRAINT filing_batch_items_status_chk
        CHECK (status IN (
            'pending',
            'in_progress',
            'saved',
            'proceeded',
            'needs_review',
            'evc_pending',
            'failed',
            'filed',
            'skipped'
        )),
    error_code TEXT,
    error_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_filing_batch_items_batch
    ON public.filing_batch_items(batch_id, status);

CREATE INDEX IF NOT EXISTS idx_filing_batch_items_client_gstin
    ON public.filing_batch_items(client_gstin_id);

COMMENT ON TABLE public.filing_batch_items IS
    'Individual client GSTIN status and run reference within a bulk filing batch.';

-- ============================================================================
-- 5. sales_register_run
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.sales_register_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    period VARCHAR(7) NOT NULL,
    file_type VARCHAR(50) NOT NULL DEFAULT 'sales_register',
    r2_key TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    file_hash VARCHAR(64) NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    total_records INTEGER NOT NULL DEFAULT 0,
    inserted_records INTEGER NOT NULL DEFAULT 0,
    failed_records INTEGER NOT NULL DEFAULT 0,
    sr_records_imported INTEGER NOT NULL DEFAULT 0,
    progress_percent DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    sanity_report JSONB,
    status_message TEXT,
    created_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_sales_register_run_client_gstin_id
    ON public.sales_register_run(client_gstin_id);

CREATE INDEX IF NOT EXISTS idx_sales_register_run_period
    ON public.sales_register_run(client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_sales_register_run_status
    ON public.sales_register_run(status);

COMMENT ON TABLE public.sales_register_run IS
    'Tracks Tally Bridge Sales Register auto-sync import runs. Mirrors reconciliation_run for sales side.';

-- ============================================================================
-- 6. sr_records
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.sr_records (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES public.sales_register_run(id) ON DELETE CASCADE,
    client_gstin_id TEXT NOT NULL,
    period VARCHAR(7) NOT NULL,
    record_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_sr_records_run_id
    ON public.sr_records(run_id);

CREATE INDEX IF NOT EXISTS idx_sr_records_client_gstin_id
    ON public.sr_records(client_gstin_id);

CREATE INDEX IF NOT EXISTS idx_sr_records_period
    ON public.sr_records(client_gstin_id, period);

COMMENT ON TABLE public.sr_records IS
    'Individual sales register rows imported per sync run holding parsed voucher JSONB.';

-- ============================================================================
-- Permissions & Security
-- ============================================================================
ALTER TABLE public.filing_sessions DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.filing_runs DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.filing_batches DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.filing_batch_items DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_register_run DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sr_records DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.filing_sessions TO CURRENT_USER;
GRANT ALL ON public.filing_runs TO CURRENT_USER;
GRANT ALL ON public.filing_batches TO CURRENT_USER;
GRANT ALL ON public.filing_batch_items TO CURRENT_USER;
GRANT ALL ON public.sales_register_run TO CURRENT_USER;
GRANT ALL ON public.sr_records TO CURRENT_USER;
