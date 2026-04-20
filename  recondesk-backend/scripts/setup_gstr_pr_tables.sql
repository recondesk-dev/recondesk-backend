-- One-shot setup for import pipeline tables (Supabase SQL Editor).
-- Run AFTER `reconciliation_run` exists. Safe to re-run: IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS public.gstr_records (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    client_gstin_id TEXT NOT NULL,
    period VARCHAR(7) NOT NULL,
    record_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr_records_run_id ON public.gstr_records(run_id);

CREATE TABLE IF NOT EXISTS public.pr_records (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    client_gstin_id TEXT NOT NULL,
    period VARCHAR(7) NOT NULL,
    record_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pr_records_run_id ON public.pr_records(run_id);

-- If tables already existed with VARCHAR(15) on client_gstin_id, also run scripts/fix_client_gstin_id.sql
-- (or ALTER those columns to TEXT) on reconciliation_run and these tables.
