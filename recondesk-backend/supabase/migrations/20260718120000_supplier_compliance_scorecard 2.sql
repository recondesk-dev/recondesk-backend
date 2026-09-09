-- Vendor / supplier compliance scorecard (firm-scoped, precomputed).
--
-- by_client: per-client contribution counters (incremental refresh unit).
-- summary: firm-level rollup keyed by (firm_owner_id, supplier_gstin_normalized).
-- Checksum-valid GSTINs only; invalid/typo GSTINs are excluded in app code.

CREATE TABLE IF NOT EXISTS public.supplier_compliance_by_client (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_owner_id uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
  supplier_gstin_normalized char(15) NOT NULL,
  client_gstin_id uuid NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
  supplier_trade_name text NOT NULL DEFAULT '',
  total_invoices int NOT NULL DEFAULT 0,
  mismatch_invoice_count int NOT NULL DEFAULT 0,
  rule37_open_count int NOT NULL DEFAULT 0,
  rule37_at_risk_paise bigint NOT NULL DEFAULT 0,
  section_17_5_count int NOT NULL DEFAULT 0,
  late_filing_count int NOT NULL DEFAULT 0,
  pr_only_count int NOT NULL DEFAULT 0,
  quarterly_filer_flag boolean NOT NULL DEFAULT false,
  last_updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT supplier_compliance_by_client_unique
    UNIQUE (firm_owner_id, supplier_gstin_normalized, client_gstin_id),
  CONSTRAINT supplier_compliance_by_client_gstin_len
    CHECK (char_length(supplier_gstin_normalized) = 15)
);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_by_client_firm_supplier
  ON public.supplier_compliance_by_client (firm_owner_id, supplier_gstin_normalized);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_by_client_client
  ON public.supplier_compliance_by_client (client_gstin_id);

CREATE TABLE IF NOT EXISTS public.supplier_compliance_summary (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_owner_id uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
  supplier_gstin_normalized char(15) NOT NULL,
  supplier_trade_name text NOT NULL DEFAULT '',
  client_gstin_ids uuid[] NOT NULL DEFAULT '{}',
  clients_touched_count int NOT NULL DEFAULT 0,
  total_invoices int NOT NULL DEFAULT 0,
  mismatch_invoice_count int NOT NULL DEFAULT 0,
  mismatch_rate numeric(5, 4) NOT NULL DEFAULT 0,
  rule37_open_count int NOT NULL DEFAULT 0,
  rule37_at_risk_paise bigint NOT NULL DEFAULT 0,
  section_17_5_count int NOT NULL DEFAULT 0,
  late_filing_count int NOT NULL DEFAULT 0,
  late_filing_rate numeric(5, 4) NOT NULL DEFAULT 0,
  pr_only_count int NOT NULL DEFAULT 0,
  quarterly_filer_flag boolean NOT NULL DEFAULT false,
  risk_score int NOT NULL DEFAULT 0,
  last_updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT supplier_compliance_summary_unique
    UNIQUE (firm_owner_id, supplier_gstin_normalized),
  CONSTRAINT supplier_compliance_summary_gstin_len
    CHECK (char_length(supplier_gstin_normalized) = 15),
  CONSTRAINT supplier_compliance_summary_risk_score_range
    CHECK (risk_score >= 0 AND risk_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_firm_risk
  ON public.supplier_compliance_summary (firm_owner_id, risk_score DESC);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_firm_clients
  ON public.supplier_compliance_summary (firm_owner_id, clients_touched_count DESC);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_firm_updated
  ON public.supplier_compliance_summary (firm_owner_id, last_updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_client_ids
  ON public.supplier_compliance_summary USING gin (client_gstin_ids);

ALTER TABLE public.supplier_compliance_by_client ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.supplier_compliance_summary ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.supplier_compliance_by_client
  TO postgres, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.supplier_compliance_summary
  TO postgres, service_role;

COMMENT ON TABLE public.supplier_compliance_by_client IS
  'Per-client contribution counters for vendor compliance scorecard; refreshed on run complete.';

COMMENT ON TABLE public.supplier_compliance_summary IS
  'Firm-scoped vendor compliance scorecard rollup keyed by checksum-valid supplier GSTIN.';

COMMENT ON COLUMN public.supplier_compliance_summary.pr_only_count IS
  'Invoices in books but not in GSTR-2B (PR_ONLY). Not a non-filer determination.';

COMMENT ON COLUMN public.supplier_compliance_summary.quarterly_filer_flag IS
  'True when any contributing client saw QUARTERLY_FILER risk for this supplier.';

COMMENT ON COLUMN public.supplier_compliance_summary.late_filing_rate IS
  'Share of invoices flagged via supplier GSTR-1 filing date (supfildt) after due date.';
