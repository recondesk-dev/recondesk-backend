-- GSTR-1 (sell-side) reconciliation runs — durable results for banners / revisit.
-- Separate from purchase-side reconciliation_run (ITC-centric schema).

CREATE TABLE IF NOT EXISTS public.gstr1_reconciliation_run (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_gstin_id   uuid NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
  period            varchar(7),
  status            text NOT NULL DEFAULT 'COMPLETED',
  run_summary       jsonb,
  result_payload    jsonb NOT NULL,
  created_by        uuid,
  created_at        timestamptz NOT NULL DEFAULT now(),
  completed_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gstr1_run_client_created
  ON public.gstr1_reconciliation_run (client_gstin_id, created_at DESC);

ALTER TABLE public.gstr1_reconciliation_run DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.gstr1_reconciliation_run TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr1_reconciliation_run TO authenticated;
