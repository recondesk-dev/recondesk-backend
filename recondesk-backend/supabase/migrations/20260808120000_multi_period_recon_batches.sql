-- Migration: 20260808120000_multi_period_recon_batches.sql
-- Multi-Period Reconciliation Wizard schema: multi_period_recon_batches and multi_period_recon_batch_items

CREATE TABLE IF NOT EXISTS public.multi_period_recon_batches (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id     uuid NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    financial_year      varchar(7) NOT NULL CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending',
                            'fetching',
                            'queued',
                            'running',
                            'partially_failed',
                            'completed',
                            'failed'
                        )),
    created_by          uuid REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_multi_period_recon_batches_client
    ON public.multi_period_recon_batches (client_gstin_id, financial_year, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_multi_period_recon_batches_status
    ON public.multi_period_recon_batches (status);

CREATE TABLE IF NOT EXISTS public.multi_period_recon_batch_items (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                uuid NOT NULL REFERENCES public.multi_period_recon_batches (id) ON DELETE CASCADE,
    period                  varchar(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    gstr2b_source           text CHECK (gstr2b_source IN ('auto_fetch', 'manual_upload')),
    gstr2b_file_path        text,
    pr_source               text CHECK (pr_source IN ('tally_bridge_existing', 'manual_upload', 'already_uploaded', 'missing')),
    pr_file_path            text,
    reconciliation_run_id   uuid REFERENCES public.reconciliation_run (id) ON DELETE SET NULL,
    status                  text NOT NULL DEFAULT 'pending'
                            CHECK (status IN (
                                'pending',
                                'fetching',
                                'uploaded',
                                'queued',
                                'running',
                                'failed',
                                'completed'
                            )),
    error_message           text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_multi_period_batch_period UNIQUE (batch_id, period)
);

CREATE INDEX IF NOT EXISTS idx_multi_period_recon_batch_items_batch
    ON public.multi_period_recon_batch_items (batch_id, period);

-- RLS Security Policies
ALTER TABLE public.multi_period_recon_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.multi_period_recon_batch_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY multi_period_batches_service_role ON public.multi_period_recon_batches
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY multi_period_batch_items_service_role ON public.multi_period_recon_batch_items
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Authenticated Users Policies (Scoped via client_gstins firm ownership)
CREATE POLICY multi_period_batches_user ON public.multi_period_recon_batches
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.client_gstins c
            WHERE c.id = multi_period_recon_batches.client_gstin_id
            AND c.firm_owner_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.client_gstins c
            WHERE c.id = multi_period_recon_batches.client_gstin_id
            AND c.firm_owner_id = auth.uid()
        )
    );

CREATE POLICY multi_period_batch_items_user ON public.multi_period_recon_batch_items
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.multi_period_recon_batches b
            JOIN public.client_gstins c ON c.id = b.client_gstin_id
            WHERE b.id = multi_period_recon_batch_items.batch_id
            AND c.firm_owner_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.multi_period_recon_batches b
            JOIN public.client_gstins c ON c.id = b.client_gstin_id
            WHERE b.id = multi_period_recon_batch_items.batch_id
            AND c.firm_owner_id = auth.uid()
        )
    );
