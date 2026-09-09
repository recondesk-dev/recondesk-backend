-- Enable RLS on gstr1_reconciliation_run and scope access to the same
-- client_gstins ownership chain used by app/services/firm_access.py:
--   admin/owner → client_gstins.firm_owner_id = auth.uid()
--   staff       → client_gstins.assigned_to   = auth.uid()
--
-- Purchase-side reconciliation_run has no DB RLS (access is enforced in the
-- API). Browser-facing tables that do use RLS (run_credits, import wizard,
-- audit_logs) key off firm_owner_id / auth.uid(); this table has no denormalized
-- firm column, so policies join via client_gstin_id → client_gstins.
--
-- service_role bypasses RLS in Supabase; GRANT ALL from the create migration
-- remains sufficient for FastAPI writes.

ALTER TABLE public.gstr1_reconciliation_run ENABLE ROW LEVEL SECURITY;

-- SELECT
DROP POLICY IF EXISTS gstr1_run_select_firm ON public.gstr1_reconciliation_run;
CREATE POLICY gstr1_run_select_firm
  ON public.gstr1_reconciliation_run
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.client_gstins cg
      WHERE cg.id = gstr1_reconciliation_run.client_gstin_id
        AND (
          cg.firm_owner_id = auth.uid()
          OR cg.assigned_to = auth.uid()
        )
    )
  );

-- INSERT
DROP POLICY IF EXISTS gstr1_run_insert_firm ON public.gstr1_reconciliation_run;
CREATE POLICY gstr1_run_insert_firm
  ON public.gstr1_reconciliation_run
  FOR INSERT
  TO authenticated
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.client_gstins cg
      WHERE cg.id = gstr1_reconciliation_run.client_gstin_id
        AND (
          cg.firm_owner_id = auth.uid()
          OR cg.assigned_to = auth.uid()
        )
    )
  );

-- UPDATE
DROP POLICY IF EXISTS gstr1_run_update_firm ON public.gstr1_reconciliation_run;
CREATE POLICY gstr1_run_update_firm
  ON public.gstr1_reconciliation_run
  FOR UPDATE
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.client_gstins cg
      WHERE cg.id = gstr1_reconciliation_run.client_gstin_id
        AND (
          cg.firm_owner_id = auth.uid()
          OR cg.assigned_to = auth.uid()
        )
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.client_gstins cg
      WHERE cg.id = gstr1_reconciliation_run.client_gstin_id
        AND (
          cg.firm_owner_id = auth.uid()
          OR cg.assigned_to = auth.uid()
        )
    )
  );

-- DELETE
DROP POLICY IF EXISTS gstr1_run_delete_firm ON public.gstr1_reconciliation_run;
CREATE POLICY gstr1_run_delete_firm
  ON public.gstr1_reconciliation_run
  FOR DELETE
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.client_gstins cg
      WHERE cg.id = gstr1_reconciliation_run.client_gstin_id
        AND (
          cg.firm_owner_id = auth.uid()
          OR cg.assigned_to = auth.uid()
        )
    )
  );

COMMENT ON TABLE public.gstr1_reconciliation_run IS
  'GSTR-1 sell-side runs. RLS: authenticated users may access rows only when '
  'client_gstins.firm_owner_id or assigned_to = auth.uid(). service_role bypasses RLS.';
