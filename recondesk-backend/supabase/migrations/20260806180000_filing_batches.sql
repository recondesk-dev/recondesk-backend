-- Migration: 20260806180000_filing_batches.sql
-- Bulk Return Processing schema: filing_batches and filing_batch_items

CREATE TABLE IF NOT EXISTS public.filing_batches (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    created_by          uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    return_type         text NOT NULL DEFAULT 'gstr-1' CHECK (return_type IN ('gstr-1')),
    period              varchar(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending',
                            'in_progress',
                            'completed',
                            'partially_completed',
                            'failed',
                            'cancelled'
                        )),
    total_count         integer NOT NULL DEFAULT 0,
    saved_count         integer NOT NULL DEFAULT 0,
    evc_pending_count   integer NOT NULL DEFAULT 0,
    filed_count         integer NOT NULL DEFAULT 0,
    failed_count        integer NOT NULL DEFAULT 0,
    needs_review_count  integer NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filing_batches_firm_period
    ON public.filing_batches (firm_id, return_type, period, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_filing_batches_status
    ON public.filing_batches (status);

CREATE TABLE IF NOT EXISTS public.filing_batch_items (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id            uuid NOT NULL REFERENCES public.filing_batches (id) ON DELETE CASCADE,
    client_gstin_id     uuid NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin               text NOT NULL,
    filing_run_id       uuid REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    status              text NOT NULL DEFAULT 'pending'
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
    error_code          text,
    error_detail        text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filing_batch_items_batch
    ON public.filing_batch_items (batch_id, status);

CREATE INDEX IF NOT EXISTS idx_filing_batch_items_client_gstin
    ON public.filing_batch_items (client_gstin_id);

ALTER TABLE public.filing_batches DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.filing_batch_items DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.filing_batches TO service_role;
GRANT ALL ON public.filing_batch_items TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.filing_batches TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.filing_batch_items TO authenticated;
