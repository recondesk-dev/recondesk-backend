-- Create gstr9_audit_overrides table for CA audit adjustments
CREATE TABLE IF NOT EXISTS public.gstr9_audit_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    financial_year TEXT NOT NULL,
    table_key TEXT NOT NULL,
    cell_key TEXT NOT NULL,
    system_value NUMERIC(15, 2) DEFAULT 0.00,
    override_value NUMERIC(15, 2) NOT NULL,
    notes TEXT,
    updated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_gstr9_override_cell UNIQUE (client_gstin_id, financial_year, table_key, cell_key)
);

CREATE INDEX IF NOT EXISTS idx_gstr9_audit_overrides_client_fy 
ON public.gstr9_audit_overrides (client_gstin_id, financial_year);

ALTER TABLE public.gstr9_audit_overrides ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all access to gstr9_audit_overrides for authenticated users" 
ON public.gstr9_audit_overrides FOR ALL TO authenticated USING (true);
