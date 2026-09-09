-- Migration: 20260802120001_sr_records.sql
-- Per-row sales register records imported by the Tally Bridge sync.
-- Mirrors pr_records exactly (same columns, same index pattern),
-- with FK to sales_register_run instead of reconciliation_run.
-- Depends on: 20260802120000_sales_register_run.sql

CREATE TABLE IF NOT EXISTS public.sr_records (
    id              bigserial    PRIMARY KEY,
    run_id          uuid         NOT NULL
                        REFERENCES public.sales_register_run(id) ON DELETE CASCADE,
    client_gstin_id text         NOT NULL,
    period          varchar(7)   NOT NULL,
    record_data     jsonb        NOT NULL,
    created_at      timestamptz  DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sr_records_run_id
    ON public.sr_records(run_id);

CREATE INDEX IF NOT EXISTS idx_sr_records_client_gstin_id
    ON public.sr_records(client_gstin_id);

CREATE INDEX IF NOT EXISTS idx_sr_records_period
    ON public.sr_records(client_gstin_id, period);

COMMENT ON TABLE public.sr_records IS
    'Individual sales register rows imported per sync run. '
    'Each row holds one parsed voucher as record_data JSONB. '
    'Mirrors pr_records for the sales side.';
