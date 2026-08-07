-- Books-to-E-Invoice reconciliation results table & RLS policies.

CREATE TABLE IF NOT EXISTS public.einvoice_recon_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid,
    client_gstin_id uuid NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    period varchar(7) NOT NULL,
    invoice_number text NOT NULL,
    irn text,
    irn_status text,
    category text NOT NULL,
    book_value numeric DEFAULT 0,
    einvoice_value numeric DEFAULT 0,
    details jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_einvoice_recon_results_client_period
    ON public.einvoice_recon_results (client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_einvoice_recon_results_run_id
    ON public.einvoice_recon_results (run_id);

ALTER TABLE public.einvoice_recon_results ENABLE ROW LEVEL SECURITY;

-- SELECT policy
DROP POLICY IF EXISTS einvoice_recon_results_select_firm ON public.einvoice_recon_results;
CREATE POLICY einvoice_recon_results_select_firm
    ON public.einvoice_recon_results
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = einvoice_recon_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- INSERT policy
DROP POLICY IF EXISTS einvoice_recon_results_insert_firm ON public.einvoice_recon_results;
CREATE POLICY einvoice_recon_results_insert_firm
    ON public.einvoice_recon_results
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = einvoice_recon_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- UPDATE policy
DROP POLICY IF EXISTS einvoice_recon_results_update_firm ON public.einvoice_recon_results;
CREATE POLICY einvoice_recon_results_update_firm
    ON public.einvoice_recon_results
    FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = einvoice_recon_results.client_gstin_id
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
            WHERE cg.id = einvoice_recon_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- DELETE policy
DROP POLICY IF EXISTS einvoice_recon_results_delete_firm ON public.einvoice_recon_results;
CREATE POLICY einvoice_recon_results_delete_firm
    ON public.einvoice_recon_results
    FOR DELETE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = einvoice_recon_results.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

GRANT ALL ON public.einvoice_recon_results TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.einvoice_recon_results TO authenticated;
