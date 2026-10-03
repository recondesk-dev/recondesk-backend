-- Migration: 20261008100000_create_batch3b_integrations.up.sql
-- Description: Create Canonical Batch 3B External Integration & Connector Tables and IMS RPC
-- Target: AWS Aurora PostgreSQL

-- 1. tally_bridge_keys
CREATE TABLE IF NOT EXISTS public.tally_bridge_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key TEXT NOT NULL UNIQUE,
    account_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL DEFAULT '',
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tbk_account_id ON public.tally_bridge_keys(account_id);
CREATE INDEX IF NOT EXISTS idx_tbk_api_key ON public.tally_bridge_keys(api_key);

-- 2. tally_ledger_masters
CREATE TABLE IF NOT EXISTS public.tally_ledger_masters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    parent_group TEXT NOT NULL DEFAULT '',
    gstin TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    opening_balance NUMERIC,
    closing_balance NUMERIC,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    CONSTRAINT uq_tally_ledger_masters UNIQUE (account_id, company_name, name)
);

CREATE INDEX IF NOT EXISTS idx_tlm_account_id ON public.tally_ledger_masters(account_id);
CREATE INDEX IF NOT EXISTS idx_tlm_gstin ON public.tally_ledger_masters(account_id, gstin);

-- 3. client_einvoice_credentials
CREATE TABLE IF NOT EXISTS public.client_einvoice_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL UNIQUE REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    einvoice_username TEXT NOT NULL,
    einvoice_password TEXT NOT NULL,
    session_token TEXT,
    session_token_expiry TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_cec_client_gstin_id ON public.client_einvoice_credentials(client_gstin_id);

-- 4. einvoice_recon_results
CREATE TABLE IF NOT EXISTS public.einvoice_recon_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES public.reconciliation_run(id) ON DELETE SET NULL,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    period VARCHAR(7) NOT NULL,
    invoice_number TEXT NOT NULL,
    irn TEXT,
    irn_status TEXT,
    category TEXT NOT NULL,
    book_value NUMERIC DEFAULT 0,
    einvoice_value NUMERIC DEFAULT 0,
    details JSONB,
    verification_source TEXT,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_err_client_period ON public.einvoice_recon_results(client_gstin_id, period);
CREATE INDEX IF NOT EXISTS idx_err_run_id ON public.einvoice_recon_results(run_id);

-- 5. gst_fetch_log
CREATE TABLE IF NOT EXISTS public.gst_fetch_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    gstin TEXT NOT NULL,
    return_type TEXT NOT NULL,
    period TEXT NOT NULL,
    section TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_gfl_client_period ON public.gst_fetch_log(client_id, return_type, period, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_gfl_gstin_period ON public.gst_fetch_log(gstin, return_type, period, fetched_at DESC);

-- 6. ims_action_submissions
CREATE TABLE IF NOT EXISTS public.ims_action_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id TEXT NOT NULL,
    gstin TEXT NOT NULL,
    period VARCHAR(7) NOT NULL,
    chosen_action TEXT NOT NULL,
    recommended_action TEXT,
    submit_mode TEXT NOT NULL DEFAULT 'confirm_recommendation',
    status TEXT NOT NULL DEFAULT 'pending',
    reference_id TEXT,
    transaction_id TEXT,
    status_cd TEXT,
    error_code TEXT,
    error_message TEXT,
    raw_poll JSONB,
    run_id UUID REFERENCES public.reconciliation_run(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    CONSTRAINT uq_ias_key UNIQUE (invoice_id, period, gstin),
    CONSTRAINT chk_ias_action CHECK (chosen_action IN ('accept', 'reject', 'hold', 'pending')),
    CONSTRAINT chk_ias_period CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT chk_ias_status CHECK (status IN ('claiming', 'pending', 'confirmed', 'failed', 'unclear')),
    CONSTRAINT chk_ias_mode CHECK (submit_mode IN ('confirm_recommendation', 'override'))
);

CREATE INDEX IF NOT EXISTS idx_ias_gstin_period ON public.ims_action_submissions(gstin, period, status);
CREATE INDEX IF NOT EXISTS idx_ias_reference ON public.ims_action_submissions(reference_id) WHERE (reference_id IS NOT NULL);

-- 7. RPC: fn_claim_ims_action_submission
CREATE OR REPLACE FUNCTION public.fn_claim_ims_action_submission(
    p_invoice_id text,
    p_gstin text,
    p_period character varying,
    p_chosen_action text,
    p_recommended_action text DEFAULT NULL::text,
    p_submit_mode text DEFAULT 'confirm_recommendation'::text,
    p_run_id uuid DEFAULT NULL::uuid
) RETURNS SETOF public.ims_action_submissions
LANGUAGE plpgsql
AS $$
DECLARE
    claimed public.ims_action_submissions%ROWTYPE;
    g text := upper(btrim(p_gstin));
    p character varying := left(btrim(p_period), 7);
BEGIN
    -- 1) First writer wins: atomic insert, conflict does nothing
    INSERT INTO public.ims_action_submissions (
        invoice_id,
        gstin,
        period,
        chosen_action,
        recommended_action,
        submit_mode,
        status,
        run_id
    ) VALUES (
        p_invoice_id,
        g,
        p,
        p_chosen_action,
        p_recommended_action,
        COALESCE(NULLIF(btrim(p_submit_mode), ''), 'confirm_recommendation'),
        'claiming',
        p_run_id
    )
    ON CONFLICT (invoice_id, period, gstin) DO NOTHING
    RETURNING * INTO claimed;

    IF FOUND THEN
        RETURN NEXT claimed;
        RETURN;
    END IF;

    -- 2) Only failed rows may be reclaimed for retry (still atomic)
    UPDATE public.ims_action_submissions AS s
    SET
        status = 'claiming',
        chosen_action = p_chosen_action,
        recommended_action = p_recommended_action,
        submit_mode = COALESCE(NULLIF(btrim(p_submit_mode), ''), 'confirm_recommendation'),
        run_id = COALESCE(p_run_id, s.run_id),
        reference_id = NULL,
        transaction_id = NULL,
        status_cd = NULL,
        error_code = NULL,
        error_message = NULL,
        raw_poll = NULL,
        updated_at = timezone('utc', now())
    WHERE s.invoice_id = p_invoice_id
      AND s.period = p
      AND s.gstin = g
      AND s.status = 'failed'
    RETURNING * INTO claimed;

    IF FOUND THEN
        RETURN NEXT claimed;
    END IF;
    RETURN;
END;
$$;

-- Alias wrapper for claim_ims_action_submission
CREATE OR REPLACE FUNCTION public.claim_ims_action_submission(
    p_invoice_id text,
    p_gstin text,
    p_period character varying,
    p_chosen_action text,
    p_recommended_action text DEFAULT NULL::text,
    p_submit_mode text DEFAULT 'confirm_recommendation'::text,
    p_run_id uuid DEFAULT NULL::uuid
) RETURNS SETOF public.ims_action_submissions
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY SELECT * FROM public.fn_claim_ims_action_submission(
        p_invoice_id,
        p_gstin,
        p_period,
        p_chosen_action,
        p_recommended_action,
        p_submit_mode,
        p_run_id
    );
END;
$$;
