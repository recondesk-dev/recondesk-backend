-- Create gst_notices table for GST Department Notice Defense & Reconciliation Engine
CREATE TABLE IF NOT EXISTS public.gst_notices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    notice_reference VARCHAR(100) NOT NULL, -- DIN or Notice Ref No
    notice_type VARCHAR(50) NOT NULL, -- 'DRC-01C', 'ASMT-10', 'DRC-01B', 'DRC-01A', 'DRC-01', 'OTHER'
    tax_period VARCHAR(20) NOT NULL, -- e.g. '032024' or '2023-24'
    financial_year VARCHAR(20), -- e.g. '2023-24'
    issue_date DATE,
    reply_due_date DATE,
    issuing_authority VARCHAR(255), -- e.g. 'Office of the Assistant Commissioner, Ward 12'
    alleged_tax_demand NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    alleged_igst NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    alleged_cgst NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    alleged_sgst NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    alleged_cess NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    discrepancy_category VARCHAR(100) NOT NULL DEFAULT 'ITC_EXCESS_3B_VS_2B',
    reconciliation_run_id UUID REFERENCES public.reconciliation_run(id) ON DELETE SET NULL,
    defense_summary JSONB, -- Mathematical reconciliation & summary metrics
    invoices_schedule JSONB, -- Itemized defense rows / Annexure A
    formal_reply_text TEXT, -- Generated statutory reply draft
    status VARCHAR(50) NOT NULL DEFAULT 'DEFENSE_READY', -- 'DRAFT', 'DEFENSE_READY', 'REPLY_SUBMITTED', 'CLOSED'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gst_notices_client ON public.gst_notices(client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_gst_notices_firm ON public.gst_notices(firm_owner_id);
CREATE INDEX IF NOT EXISTS idx_gst_notices_period ON public.gst_notices(tax_period);
CREATE INDEX IF NOT EXISTS idx_gst_notices_run ON public.gst_notices(reconciliation_run_id);

-- RLS policies for gst_notices
ALTER TABLE public.gst_notices ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'gst_notices' AND policyname = 'gst_notices_firm_owner_all'
    ) THEN
        CREATE POLICY gst_notices_firm_owner_all ON public.gst_notices
            FOR ALL
            USING (firm_owner_id = auth.uid())
            WITH CHECK (firm_owner_id = auth.uid());
    END IF;
END $$;
