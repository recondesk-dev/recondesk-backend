-- Migration: 20260802120000_sales_register_run.sql
-- New table to track Tally Bridge Sales Register auto-sync runs.
-- Modeled on reconciliation_run (purchase-side) but uses uuid FK to
-- client_gstins(id), matching gstr1_reconciliation_run's newer pattern.

CREATE TABLE IF NOT EXISTS public.sales_register_run (
    id                  uuid             PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id     uuid             NOT NULL
                            REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    period              varchar(7)       NOT NULL,
    file_type           varchar(50)      NOT NULL DEFAULT 'sales_register',
    r2_key              text,
    status              varchar(50)      NOT NULL DEFAULT 'queued',
    file_hash           varchar(64)      NOT NULL DEFAULT '',
    retry_count         integer          NOT NULL DEFAULT 0,
    total_records       integer          NOT NULL DEFAULT 0,
    inserted_records    integer          NOT NULL DEFAULT 0,
    failed_records      integer          NOT NULL DEFAULT 0,
    sr_records_imported integer          NOT NULL DEFAULT 0,
    progress_percent    double precision NOT NULL DEFAULT 0.0,
    sanity_report       jsonb,
    status_message      text,
    created_at          timestamptz      DEFAULT now(),
    updated_at          timestamptz      DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_register_run_client_gstin_id
    ON public.sales_register_run(client_gstin_id);

CREATE INDEX IF NOT EXISTS idx_sales_register_run_period
    ON public.sales_register_run(client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_sales_register_run_status
    ON public.sales_register_run(status);

COMMENT ON TABLE public.sales_register_run IS
    'Tracks Tally Bridge Sales Register auto-sync import runs (one row per push). '
    'Mirrors reconciliation_run for the sales side. '
    'sr_records rows are children of this table via run_id FK.';
