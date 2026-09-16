-- Migration: 20260917120000_delete_reconciliation_run_cascade_table4.sql
-- Description: Transactional delete for reconciliation runs including GSTR-3B Table 4, reversal ledger, and reclaim events.

CREATE OR REPLACE FUNCTION public.delete_reconciliation_run_cascade(p_run_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- 1. Disconnect circular FK on reconciliation_run(table4_summary_id)
  BEGIN
    UPDATE public.reconciliation_run
    SET table4_summary_id = NULL
    WHERE id = p_run_id;
  EXCEPTION
    WHEN undefined_table OR undefined_column THEN
      NULL;
  END;

  -- 2. GSTR-3B Reclaim Events referencing this run directly or via this run's reversal ledger
  BEGIN
    UPDATE public.gstr3b_reclaim_events
    SET compensates_event_id = NULL
    WHERE reclaim_run_id = p_run_id
       OR ledger_id IN (
         SELECT id FROM public.gstr3b_reversal_ledger WHERE source_run_id = p_run_id
       );

    DELETE FROM public.gstr3b_reclaim_events
    WHERE reclaim_run_id = p_run_id
       OR ledger_id IN (
         SELECT id FROM public.gstr3b_reversal_ledger WHERE source_run_id = p_run_id
       );
  EXCEPTION
    WHEN undefined_table THEN
      NULL;
  END;

  -- 3. GSTR-3B Reversal Ledger records originated by this run
  BEGIN
    DELETE FROM public.gstr3b_reversal_ledger
    WHERE source_run_id = p_run_id;
  EXCEPTION
    WHEN undefined_table THEN
      NULL;
  END;

  -- 4. GSTR-3B Table 4 snapshots for this run
  BEGIN
    DELETE FROM public.gstr3b_table4_summaries
    WHERE run_id = p_run_id;
  EXCEPTION
    WHEN undefined_table THEN
      NULL;
  END;

  -- 5. Cross-run invoice tracking (re-point last_seen or delete when first_seen is this run)
  BEGIN
    UPDATE public.invoice_tracking
    SET last_seen_run_id = first_seen_run_id,
        updated_at = now()
    WHERE last_seen_run_id = p_run_id
      AND first_seen_run_id IS DISTINCT FROM p_run_id;

    DELETE FROM public.invoice_tracking
    WHERE first_seen_run_id = p_run_id
       OR last_seen_run_id = p_run_id;
  EXCEPTION
    WHEN undefined_table THEN
      NULL;
  END;

  -- 6. Non-cascading rule 37 actions and import wizard records
  BEGIN
    DELETE FROM public.rule37_actions WHERE run_id = p_run_id;
  EXCEPTION
    WHEN undefined_table THEN
      NULL;
  END;

  BEGIN
    DELETE FROM public.reconciliation_import_runs WHERE id = p_run_id;
  EXCEPTION
    WHEN undefined_table THEN
      NULL;
  END;

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

COMMENT ON FUNCTION public.delete_reconciliation_run_cascade(uuid) IS
  'Deletes a reconciliation_run and non-cascading dependents (table 4 summaries, reversal ledger, reclaim events, invoice_tracking, rule37_actions, import wizard) in one transaction.';
