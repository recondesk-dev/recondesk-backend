-- GSTR-2A vs GSTR-2B Delta Reconciliation Results table & RLS policies

CREATE TABLE IF NOT EXISTS public.gstr2a_delta_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id uuid NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    period text NOT NULL,
    cutoff_date date,
    reconciled_at timestamptz NOT NULL DEFAULT now(),
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    results jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_gstr2a_delta_results_client_period UNIQUE (client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr2a_delta_results_client_period
    ON public.gstr2a_delta_results (client_gstin_id, period);

ALTER TABLE public.gstr2a_delta_results ENABLE ROW LEVEL SECURITY;

-- SELECT policy
DROP POLICY IF EXISTS gstr2a_delta_results_select_firm ON public.gstr2a_delta_results;
CREATE POLICY gstr2a_delta_results_select_firm
    ON public.gstr2a_delta_results
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = gstr2a_delta_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- INSERT policy
DROP POLICY IF EXISTS gstr2a_delta_results_insert_firm ON public.gstr2a_delta_results;
CREATE POLICY gstr2a_delta_results_insert_firm
    ON public.gstr2a_delta_results
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = gstr2a_delta_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- UPDATE policy
DROP POLICY IF EXISTS gstr2a_delta_results_update_firm ON public.gstr2a_delta_results;
CREATE POLICY gstr2a_delta_results_update_firm
    ON public.gstr2a_delta_results
    FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = gstr2a_delta_results.client_gstin_id
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
            WHERE cg.id = gstr2a_delta_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- DELETE policy
DROP POLICY IF EXISTS gstr2a_delta_results_delete_firm ON public.gstr2a_delta_results;
CREATE POLICY gstr2a_delta_results_delete_firm
    ON public.gstr2a_delta_results
    FOR DELETE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = gstr2a_delta_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

GRANT ALL ON public.gstr2a_delta_results TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr2a_delta_results TO authenticated;
