-- Optional batch-level ITC claimed period for Rule 37(3) interest proxy.
-- Distinct from reconciliation_import_runs.period (GSTR-2B / recon period).

ALTER TABLE public.reconciliation_import_runs
  ADD COLUMN IF NOT EXISTS itc_claimed_period date NULL;

COMMENT ON COLUMN public.reconciliation_import_runs.itc_claimed_period IS
  'Optional YYYY-MM (stored as first-of-month date): GSTR-3B period when ITC for this PR batch was claimed. Used as Rule 37(3) interest proxy via following-month 20th due date.';
