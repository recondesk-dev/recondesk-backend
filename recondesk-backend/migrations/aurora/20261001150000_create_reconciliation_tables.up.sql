-- ============================================================================
-- Migration: 20261001150000_create_reconciliation_tables.up.sql
-- Description: Phase 4 - Reconciliation Data Layer for AWS Aurora PostgreSQL:
--              reconciliation_run, gstr_records, pr_records, reconciliation_results,
--              and transactional delete_reconciliation_run_cascade function.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.reconciliation_run
-- Represents the purchase-side reconciliation run header and execution lifecycle.
CREATE TABLE IF NOT EXISTS public.reconciliation_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID REFERENCES public.client_gstins(id),
    period TEXT NOT NULL,
    file_type TEXT,
    file_hash TEXT,
    r2_key TEXT,
    status TEXT DEFAULT 'queued',
    progress_percent NUMERIC DEFAULT 0,
    status_message TEXT,
    gstr_records_imported INTEGER DEFAULT 0,
    pr_records_imported INTEGER DEFAULT 0,
    failed_records INTEGER DEFAULT 0,
    total_records INTEGER DEFAULT 0,
    inserted_records INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    sanity_report JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    processing_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    run_summary JSONB,
    matched_count INTEGER,
    unmatched_count INTEGER,
    itc_at_risk BIGINT,
    wrongful_itc BIGINT,
    late_itc BIGINT,
    matching_version TEXT,
    rules_version TEXT,
    decision_version TEXT,
    gstr_period_end DATE,
    is_locked BOOLEAN DEFAULT FALSE,
    finalized_at TIMESTAMP WITHOUT TIME ZONE,
    finalized_by UUID,
    paid_at TIMESTAMPTZ,
    created_by VARCHAR(64),
    table4_summary_id UUID,
    CONSTRAINT uq_run_dedup UNIQUE (client_gstin_id, period, file_type, file_hash)
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_run_client_created_at
    ON public.reconciliation_run (client_gstin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reconciliation_run_created_by
    ON public.reconciliation_run (created_by);
CREATE INDEX IF NOT EXISTS idx_reconciliation_run_paid_at
    ON public.reconciliation_run (paid_at);
CREATE INDEX IF NOT EXISTS idx_reconciliation_run_status
    ON public.reconciliation_run (status);


-- 2. Table: public.gstr_records
-- Represents line items parsed and ingested from GSTR-2B / GSTR-2A supplier filings.
CREATE TABLE IF NOT EXISTS public.gstr_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    supplier_gstin_raw TEXT,
    supplier_gstin TEXT,
    invoice_number_raw TEXT,
    invoice_number TEXT,
    invoice_date_raw TEXT,
    invoice_date DATE,
    taxable_amount_raw TEXT,
    taxable_amount_paise BIGINT,
    igst_paise BIGINT,
    cgst_paise BIGINT,
    sgst_paise BIGINT,
    total_tax_paise BIGINT,
    hsn_code TEXT,
    document_type TEXT,
    is_amendment BOOLEAN DEFAULT FALSE NOT NULL,
    match_status TEXT,
    match_level INTEGER,
    match_confidence INTEGER,
    matched_pr_record_id UUID,
    match_reason TEXT,
    match_discrepancies JSONB,
    possible_blocked_credit BOOLEAN,
    decision_what TEXT,
    decision_why TEXT,
    decision_next TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    client_gstin_id TEXT,
    period VARCHAR(7),
    record_data JSONB,
    amount_difference_paise BIGINT,
    gstr2b_reflection_date DATE,
    ai_explanation TEXT
);

CREATE INDEX IF NOT EXISTS idx_gstr_records_run_id
    ON public.gstr_records (run_id);
CREATE INDEX IF NOT EXISTS idx_gstr_records_client_gstin_id
    ON public.gstr_records (client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_gstr_records_supplier_gstin
    ON public.gstr_records (supplier_gstin);
CREATE INDEX IF NOT EXISTS idx_gstr_records_invoice_number
    ON public.gstr_records (invoice_number);
CREATE INDEX IF NOT EXISTS idx_gstr_client_period
    ON public.gstr_records (client_gstin_id, period);
CREATE INDEX IF NOT EXISTS idx_gstr_run_gstin
    ON public.gstr_records (run_id, supplier_gstin);
CREATE INDEX IF NOT EXISTS idx_gstr_run_invoice
    ON public.gstr_records (run_id, invoice_number);
CREATE INDEX IF NOT EXISTS idx_gstr_run_status
    ON public.gstr_records (run_id, match_status);


-- 3. Table: public.pr_records
-- Represents line items ingested from taxpayer books (purchase registers).
CREATE TABLE IF NOT EXISTS public.pr_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    supplier_gstin_raw TEXT,
    supplier_gstin TEXT,
    invoice_number_raw TEXT,
    invoice_number TEXT,
    invoice_date_raw TEXT,
    invoice_date DATE,
    taxable_amount_raw TEXT,
    taxable_amount_paise BIGINT,
    igst_paise BIGINT,
    cgst_paise BIGINT,
    sgst_paise BIGINT,
    hsn_code TEXT,
    document_type TEXT,
    is_amendment BOOLEAN DEFAULT FALSE NOT NULL,
    match_status TEXT,
    match_level INTEGER,
    match_confidence INTEGER,
    matched_pr_record_id UUID,
    match_reason TEXT,
    possible_blocked_credit BOOLEAN,
    payment_date DATE,
    is_paid BOOLEAN,
    rule_37_status TEXT,
    rule_37_deadline DATE,
    source_software TEXT,
    decision_what TEXT,
    decision_why TEXT,
    decision_next TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    sanity_gstin_valid BOOLEAN DEFAULT TRUE,
    sanity_date_valid BOOLEAN DEFAULT TRUE,
    sanity_amount_valid BOOLEAN DEFAULT TRUE,
    sanity_duplicate_flag BOOLEAN DEFAULT FALSE,
    discrepancy_gstin TEXT,
    discrepancy_amount_diff_paise BIGINT DEFAULT 0,
    discrepancy_date_diff_days INTEGER DEFAULT 0,
    discrepancy_notes TEXT,
    client_gstin_id UUID,
    period TEXT,
    record_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_pr_records_run_id
    ON public.pr_records (run_id);
CREATE INDEX IF NOT EXISTS idx_pr_records_client_gstin_id
    ON public.pr_records (client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_pr_records_supplier_gstin
    ON public.pr_records (supplier_gstin);
CREATE INDEX IF NOT EXISTS idx_pr_records_invoice_number
    ON public.pr_records (invoice_number);
CREATE INDEX IF NOT EXISTS idx_pr_records_invoice_date
    ON public.pr_records (invoice_date);
CREATE INDEX IF NOT EXISTS idx_pr_records_match_status
    ON public.pr_records (match_status);
CREATE INDEX IF NOT EXISTS idx_pr_records_client_period_id
    ON public.pr_records (client_gstin_id, period, id);
CREATE INDEX IF NOT EXISTS idx_pr_matched_record
    ON public.pr_records (matched_pr_record_id);


-- 4. Table: public.reconciliation_results
-- Represents the compressed outcomes, matched pairs, compliance digests, and match confidence.
CREATE TABLE IF NOT EXISTS public.reconciliation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    record_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    payload JSONB,
    match_confidence REAL
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_results_run_id
    ON public.reconciliation_results (run_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_results_created
    ON public.reconciliation_results (created_at);

COMMENT ON COLUMN public.reconciliation_results.match_confidence IS
    'Invoice similarity score [0.0–1.0] for L5/fuzzy matches. NULL for exact matches.';


-- 5. Stored Function: public.delete_reconciliation_run_cascade(p_run_id uuid)
-- Transactional cascade deletion maintaining exact Step 1-7 invariant.
-- Uses to_regclass guards so it executes safely on a fresh Phase 4 Aurora database
-- where auxiliary tables (gstr3b, invoice_tracking, rule37) are not yet migrated.
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

GRANT EXECUTE ON FUNCTION public.delete_reconciliation_run_cascade(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.delete_reconciliation_run_cascade(uuid) TO authenticated;
