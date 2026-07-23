-- Per-section fetch log for GSTR-1 / GSTR-2A / GSTR-3B auto-fetch (Sandbox GSP).
-- Additive; does not touch GSTR-2B tables or client_gstins token columns.
-- Apply via Supabase SQL editor or: supabase db push

CREATE TABLE IF NOT EXISTS public.gst_fetch_log (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin           text NOT NULL,
    return_type     text NOT NULL,
    period          text NOT NULL,
    section         text NOT NULL,
    status          text NOT NULL,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    error_message   text
);

CREATE INDEX IF NOT EXISTS idx_gst_fetch_log_client_period
    ON public.gst_fetch_log (client_id, return_type, period, fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_gst_fetch_log_gstin_period
    ON public.gst_fetch_log (gstin, return_type, period, fetched_at DESC);

COMMENT ON TABLE public.gst_fetch_log IS
    'Per-section outcomes for Sandbox GSTR-1/2A/3B fetches (success or GSTN/HTTP error).';

COMMENT ON COLUMN public.gst_fetch_log.client_id IS
    'client_gstins.id of the taxpayer whose GSTN session was used.';

COMMENT ON COLUMN public.gst_fetch_log.period IS
    'Return period as YYYY-MM (zero-padded month).';

COMMENT ON COLUMN public.gst_fetch_log.section IS
    'Sub-endpoint key (e.g. b2b, summary, cdna, gstr3b).';

COMMENT ON COLUMN public.gst_fetch_log.status IS
    'success | error';

ALTER TABLE public.gst_fetch_log DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.gst_fetch_log TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gst_fetch_log TO authenticated;
