-- Credit Notes & Debit Notes (CDNR) Schema & Grants (Phase 3)

-- 1. Add CDN Prefix and Sequence to Billing Company Profiles
ALTER TABLE public.billing_company_profiles
  ADD COLUMN IF NOT EXISTS cdn_number_prefix TEXT NOT NULL DEFAULT 'CRN/',
  ADD COLUMN IF NOT EXISTS cdn_number_next_seq BIGINT NOT NULL DEFAULT 1;

-- 2. Credit Notes / Debit Notes Header Table
CREATE TABLE IF NOT EXISTS public.billing_credit_debit_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    original_invoice_id UUID NOT NULL REFERENCES public.billing_invoices(id) ON DELETE RESTRICT,
    note_type TEXT NOT NULL DEFAULT 'credit' CHECK (note_type IN ('credit', 'debit')),
    note_number TEXT NOT NULL,
    note_date DATE NOT NULL DEFAULT CURRENT_DATE,
    reason TEXT NOT NULL DEFAULT '1-Sales Return' CHECK (reason IN (
        '1-Sales Return',
        '2-Post Sale Discount',
        '3-Deficiency in Service',
        '4-Correction in Invoice',
        '5-Change in POS',
        '6-Finalization of Provisional Assessment',
        '7-Others'
    )),
    reason_detail TEXT,
    subtotal_paise BIGINT NOT NULL DEFAULT 0,
    total_tax_paise BIGINT NOT NULL DEFAULT 0,
    total_paise BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized', 'cancelled')),
    irn TEXT,
    irn_ack_number TEXT,
    irn_ack_date TIMESTAMPTZ,
    irn_qr_code TEXT,
    irn_signed_json JSONB,
    irp_status TEXT NOT NULL DEFAULT 'not_submitted',
    irp_error_detail TEXT,
    irp_environment TEXT NOT NULL DEFAULT 'test',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_billing_cdn_client_num UNIQUE (client_gstin_id, note_number)
);

CREATE INDEX IF NOT EXISTS idx_billing_cdn_client ON public.billing_credit_debit_notes(client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_billing_cdn_orig_inv ON public.billing_credit_debit_notes(original_invoice_id);
CREATE INDEX IF NOT EXISTS idx_billing_cdn_irp_status ON public.billing_credit_debit_notes(irp_status);
CREATE INDEX IF NOT EXISTS idx_billing_cdn_irn ON public.billing_credit_debit_notes(irn);

ALTER TABLE IF EXISTS public.billing_credit_debit_notes DISABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.billing_credit_debit_notes TO anon, authenticated, service_role;

-- 3. Credit / Debit Note Line Items Table
CREATE TABLE IF NOT EXISTS public.billing_cdn_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cdn_id UUID NOT NULL REFERENCES public.billing_credit_debit_notes(id) ON DELETE CASCADE,
    item_id UUID REFERENCES public.billing_items(id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    hsn_or_sac_code TEXT NOT NULL,
    quantity NUMERIC(12,4) NOT NULL DEFAULT 1.0000,
    unit TEXT NOT NULL DEFAULT 'NOS',
    rate_paise BIGINT NOT NULL DEFAULT 0,
    discount_percent NUMERIC(5,2) DEFAULT 0.00,
    taxable_value_paise BIGINT NOT NULL DEFAULT 0,
    tax_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 18.00,
    cgst_paise BIGINT NOT NULL DEFAULT 0,
    sgst_paise BIGINT NOT NULL DEFAULT 0,
    igst_paise BIGINT NOT NULL DEFAULT 0,
    cess_paise BIGINT NOT NULL DEFAULT 0,
    line_total_paise BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_cdn_line_items_cdn ON public.billing_cdn_line_items(cdn_id);

ALTER TABLE IF EXISTS public.billing_cdn_line_items DISABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.billing_cdn_line_items TO anon, authenticated, service_role;
