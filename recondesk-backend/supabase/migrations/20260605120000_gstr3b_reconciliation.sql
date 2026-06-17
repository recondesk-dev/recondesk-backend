-- GSTR-3B Reconciliation table
-- Stores per-run comparison of ITC available in GSTR-2B vs claimed in GSTR-3B.

CREATE TABLE IF NOT EXISTS public.gstr3b_reconciliation (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                  uuid NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
  client_gstin            text NOT NULL,
  tax_period              varchar(7) NOT NULL,
  -- GSTR-3B claimed (net ITC after reversals)
  gstr3b_igst_claimed     numeric(15,2) DEFAULT 0,
  gstr3b_cgst_claimed     numeric(15,2) DEFAULT 0,
  gstr3b_sgst_claimed     numeric(15,2) DEFAULT 0,
  -- GSTR-2B available (derived from reconciliation run)
  gstr2b_igst_available   numeric(15,2) DEFAULT 0,
  gstr2b_cgst_available   numeric(15,2) DEFAULT 0,
  gstr2b_sgst_available   numeric(15,2) DEFAULT 0,
  -- Differences (positive = overclaimed, negative = underclaimed)
  igst_difference         numeric(15,2) DEFAULT 0,
  cgst_difference         numeric(15,2) DEFAULT 0,
  sgst_difference         numeric(15,2) DEFAULT 0,
  -- Per-head statuses: MATCHED | OVERCLAIMED | UNDERCLAIMED
  igst_status             text,
  cgst_status             text,
  sgst_status             text,
  overall_status          text,
  outward_supply_total    numeric(15,2) DEFAULT 0,
  raw_gstr3b              jsonb,
  uploaded_by             uuid NOT NULL,
  uploaded_at             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gstr3b_run_id ON public.gstr3b_reconciliation (run_id);

ALTER TABLE public.gstr3b_reconciliation DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.gstr3b_reconciliation TO service_role;
