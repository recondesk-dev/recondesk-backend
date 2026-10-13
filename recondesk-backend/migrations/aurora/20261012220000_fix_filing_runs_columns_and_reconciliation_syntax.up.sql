-- ============================================================================
-- Migration: 20261012220000_fix_filing_runs_columns_and_reconciliation_syntax.up.sql
-- Description: Phase 5.4 - Forward-Only Corrective Migration:
--              1. Ensure public.filing_sessions and public.filing_runs exist idempotently.
--              2. Idempotently add missing operational columns to public.filing_runs:
--                 arn, filing_method, offset_payload, tx_pmt_snapshot, offset_completed_at, filed_at.
--              3. Correct PL/pgSQL format specifier in delete_reconciliation_run_cascade.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Ensure public.filing_sessions table exists idempotently
CREATE TABLE IF NOT EXISTS public.filing_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id     UUID REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    gstin               TEXT NOT NULL,
    username            TEXT NOT NULL DEFAULT '',
    session_token       TEXT NOT NULL,
    token_expires_at    TIMESTAMPTZ NOT NULL,
    session_expires_at  TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'logged_out')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    logged_out_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_filing_sessions_firm_gstin
    ON public.filing_sessions (firm_id, gstin);

-- 2. Ensure public.filing_runs table exists idempotently
CREATE TABLE IF NOT EXISTS public.filing_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id     UUID REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    filing_session_id   UUID REFERENCES public.filing_sessions (id) ON DELETE SET NULL,
    gstin               TEXT NOT NULL,
    return_type         TEXT NOT NULL,
    period              VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status              TEXT NOT NULL DEFAULT 'draft',
    reference_id        TEXT,
    ack_number          TEXT,
    arn                 TEXT,
    filing_method       TEXT,
    save_payload        JSONB,
    offset_payload      JSONB,
    tx_pmt_snapshot     JSONB,
    raw_response        JSONB,
    error_code          TEXT,
    error_message       TEXT,
    offset_completed_at TIMESTAMPTZ,
    filed_at            TIMESTAMPTZ,
    created_by          UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Idempotently add missing columns to public.filing_runs if table pre-existed
ALTER TABLE public.filing_runs
    ADD COLUMN IF NOT EXISTS arn TEXT,
    ADD COLUMN IF NOT EXISTS filing_method TEXT,
    ADD COLUMN IF NOT EXISTS offset_payload JSONB,
    ADD COLUMN IF NOT EXISTS tx_pmt_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS offset_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS filed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_filing_runs_firm_period
    ON public.filing_runs (firm_id, return_type, period);

-- 4. Correct PL/pgSQL format specifier in delete_reconciliation_run_cascade
CREATE OR REPLACE FUNCTION public.delete_reconciliation_run_cascade(p_run_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- 1. Disconnect circular FK on reconciliation_run(table4_summary_id)
  UPDATE public.reconciliation_run
  SET table4_summary_id = NULL
  WHERE id = p_run_id;

  -- 2. GSTR-3B Reclaim Events (dynamically executed only if table exists in Aurora)
  IF to_regclass('public.gstr3b_reclaim_events') IS NOT NULL AND to_regclass('public.gstr3b_reversal_ledger') IS NOT NULL THEN
    EXECUTE 'UPDATE public.gstr3b_reclaim_events SET compensates_event_id = NULL ' ||
            'WHERE reclaim_run_id = $1 OR ledger_id IN (' ||
            '  SELECT id FROM public.gstr3b_reversal_ledger WHERE source_run_id = $1' ||
            ')' USING p_run_id;

    EXECUTE 'DELETE FROM public.gstr3b_reclaim_events ' ||
            'WHERE reclaim_run_id = $1 OR ledger_id IN (' ||
            '  SELECT id FROM public.gstr3b_reversal_ledger WHERE source_run_id = $1' ||
            ')' USING p_run_id;
  END IF;

  -- 3. GSTR-3B Reversal Ledger records originated by this run
  IF to_regclass('public.gstr3b_reversal_ledger') IS NOT NULL THEN
    EXECUTE 'DELETE FROM public.gstr3b_reversal_ledger WHERE source_run_id = $1' USING p_run_id;
  END IF;

  -- 4. GSTR-3B Table 4 snapshots for this run
  IF to_regclass('public.gstr3b_table4_summaries') IS NOT NULL THEN
    EXECUTE 'DELETE FROM public.gstr3b_table4_summaries WHERE run_id = $1' USING p_run_id;
  END IF;

  -- 5. Cross-run invoice tracking (re-point last_seen or delete when first_seen is this run)
  IF to_regclass('public.invoice_tracking') IS NOT NULL THEN
    EXECUTE 'UPDATE public.invoice_tracking SET last_seen_run_id = first_seen_run_id, updated_at = now() ' ||
            'WHERE last_seen_run_id = $1 AND first_seen_run_id IS DISTINCT FROM $1' USING p_run_id;

    EXECUTE 'DELETE FROM public.invoice_tracking WHERE first_seen_run_id = $1 OR last_seen_run_id = $1' USING p_run_id;
  END IF;

  -- 6. Non-cascading rule 37 actions and import wizard records
  IF to_regclass('public.rule37_actions') IS NOT NULL THEN
    EXECUTE 'DELETE FROM public.rule37_actions WHERE run_id = $1' USING p_run_id;
  END IF;

  IF to_regclass('public.reconciliation_import_runs') IS NOT NULL THEN
    EXECUTE 'DELETE FROM public.reconciliation_import_runs WHERE id = $1' USING p_run_id;
  END IF;

  -- 7. Parent reconciliation run (remaining children cascade via ON DELETE CASCADE)
  DELETE FROM public.reconciliation_run WHERE id = p_run_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'run not found: %', p_run_id
      USING ERRCODE = 'P0002';
  END IF;
END;
$$;
