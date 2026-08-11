-- Supabase Migration: 20260811130000_gstr4_tables.sql
-- Form GSTR-4 Composition Annual Return CMP-08 tracking & CA audit overrides

CREATE TABLE IF NOT EXISTS public.gstr4_cmp08_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    financial_year TEXT NOT NULL,
    quarter TEXT NOT NULL, -- 'Q1', 'Q2', 'Q3', 'Q4'
    outward_taxable NUMERIC(15, 2) DEFAULT 0.00,
    outward_tax NUMERIC(15, 2) DEFAULT 0.00,
    rcm_taxable NUMERIC(15, 2) DEFAULT 0.00,
    rcm_tax NUMERIC(15, 2) DEFAULT 0.00,
    igst NUMERIC(15, 2) DEFAULT 0.00,
    cgst NUMERIC(15, 2) DEFAULT 0.00,
    sgst NUMERIC(15, 2) DEFAULT 0.00,
    cess NUMERIC(15, 2) DEFAULT 0.00,
    interest NUMERIC(15, 2) DEFAULT 0.00,
    late_fee NUMERIC(15, 2) DEFAULT 0.00,
    updated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_gstr4_cmp08_quarter UNIQUE (client_gstin_id, financial_year, quarter)
);

CREATE INDEX IF NOT EXISTS idx_gstr4_cmp08_client_fy
ON public.gstr4_cmp08_records (client_gstin_id, financial_year);

ALTER TABLE public.gstr4_cmp08_records ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all access to gstr4_cmp08_records for authenticated users"
ON public.gstr4_cmp08_records FOR ALL TO authenticated USING (true);


CREATE TABLE IF NOT EXISTS public.gstr4_audit_overrides (
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
    CONSTRAINT uq_gstr4_override_cell UNIQUE (client_gstin_id, financial_year, table_key, cell_key)
);

CREATE INDEX IF NOT EXISTS idx_gstr4_audit_overrides_client_fy
ON public.gstr4_audit_overrides (client_gstin_id, financial_year);

ALTER TABLE public.gstr4_audit_overrides ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all access to gstr4_audit_overrides for authenticated users"
ON public.gstr4_audit_overrides FOR ALL TO authenticated USING (true);
