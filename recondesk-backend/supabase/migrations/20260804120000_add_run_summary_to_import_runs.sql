-- Add run_summary JSONB column to reconciliation_import_runs.
-- Required by the import wizard sanity-check endpoint which writes
-- ISD/IMPG detection data into this column after parsing the GSTR-2B file.
-- Column is nullable with no default — existing rows will have NULL.
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent.

ALTER TABLE public.reconciliation_import_runs
  ADD COLUMN IF NOT EXISTS run_summary JSONB;
