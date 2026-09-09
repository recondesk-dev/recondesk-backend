-- Migration: client_einvoice_credentials table & verification_source columns on einvoice_recon_results

CREATE TABLE IF NOT EXISTS public.client_einvoice_credentials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id uuid NOT NULL UNIQUE REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    einvoice_username text NOT NULL,
    einvoice_password text NOT NULL,
    session_token text,
    session_token_expiry timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_client_einvoice_credentials_client_gstin_id
    ON public.client_einvoice_credentials (client_gstin_id);

ALTER TABLE public.client_einvoice_credentials ENABLE ROW LEVEL SECURITY;

-- SELECT policy
DROP POLICY IF EXISTS client_einvoice_credentials_select_firm ON public.client_einvoice_credentials;
CREATE POLICY client_einvoice_credentials_select_firm
    ON public.client_einvoice_credentials
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = client_einvoice_credentials.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- INSERT policy
DROP POLICY IF EXISTS client_einvoice_credentials_insert_firm ON public.client_einvoice_credentials;
CREATE POLICY client_einvoice_credentials_insert_firm
    ON public.client_einvoice_credentials
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = client_einvoice_credentials.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- UPDATE policy
DROP POLICY IF EXISTS client_einvoice_credentials_update_firm ON public.client_einvoice_credentials;
CREATE POLICY client_einvoice_credentials_update_firm
    ON public.client_einvoice_credentials
    FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = client_einvoice_credentials.client_gstin_id
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
            WHERE cg.id = client_einvoice_credentials.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- DELETE policy
DROP POLICY IF EXISTS client_einvoice_credentials_delete_firm ON public.client_einvoice_credentials;
CREATE POLICY client_einvoice_credentials_delete_firm
    ON public.client_einvoice_credentials
    FOR DELETE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.client_gstins cg
            WHERE cg.id = client_einvoice_credentials.client_gstin_id
              AND (
                cg.firm_owner_id = auth.uid()
                OR cg.assigned_to = auth.uid()
              )
        )
    );

-- Add verification tracking columns to einvoice_recon_results
ALTER TABLE public.einvoice_recon_results
    ADD COLUMN IF NOT EXISTS verification_source text,
    ADD COLUMN IF NOT EXISTS verified_at timestamptz;
