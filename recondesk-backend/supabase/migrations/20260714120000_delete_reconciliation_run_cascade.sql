-- Transactional delete for reconciliation runs.
-- Root cause of delete 500s: invoice_tracking.first_seen_run_id /
-- last_seen_run_id reference reconciliation_run(id) without ON DELETE CASCADE.

CREATE OR REPLACE FUNCTION public.delete_reconciliation_run_cascade(p_run_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- Re-point last_seen away from this run when first_seen is a different run.
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

  -- Remaining children (results, gstr/pr records, notes, etc.) cascade.
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
  'Deletes a reconciliation_run and non-cascading dependents (invoice_tracking, rule37_actions, import wizard) in one transaction.';
