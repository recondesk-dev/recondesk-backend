-- Migration: 20261011100000_create_batch4b_billing_ledger.up.sql
-- Batch 4B: E-Invoicing & B2B Billing Ledger
-- Tables:
-- 1. billing_company_profiles
-- 2. billing_customers
-- 3. billing_items
-- 4. billing_invoices
-- 5. billing_invoice_line_items
-- 6. billing_credit_debit_notes
-- 7. billing_cdn_line_items
-- 8. billing_irp_submission_log
-- RPC:
-- public.increment_invoice_number_seq(p_profile_id uuid)

-- 1. billing_company_profiles
CREATE TABLE IF NOT EXISTS public.billing_company_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    legal_name TEXT NOT NULL,
    trade_name TEXT,
    address_line1 TEXT NOT NULL DEFAULT '',
    address_line2 TEXT,
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    state_code VARCHAR(2) NOT NULL,
    pincode TEXT NOT NULL DEFAULT '',
    gstin TEXT NOT NULL,
    pan TEXT,
    bank_account_number TEXT,
    bank_ifsc TEXT,
    bank_name TEXT,
    invoice_number_prefix TEXT NOT NULL DEFAULT '',
    invoice_number_next_seq BIGINT NOT NULL DEFAULT 1,
    financial_year_reset BOOLEAN NOT NULL DEFAULT true,
    cdn_number_prefix TEXT NOT NULL DEFAULT 'CRN/',
    cdn_number_next_seq BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_company_profiles_client
    ON public.billing_company_profiles (client_gstin_id);

COMMENT ON TABLE public.billing_company_profiles IS
    'Seller company profile for billing, GST details, bank coordinates, and invoice sequence counters.';

-- 2. billing_customers
CREATE TABLE IF NOT EXISTS public.billing_customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    gstin TEXT,
    address_line1 TEXT NOT NULL DEFAULT '',
    address_line2 TEXT,
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    state_code VARCHAR(2) NOT NULL,
    pincode TEXT NOT NULL DEFAULT '',
    is_b2b BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_customers_client
    ON public.billing_customers (client_gstin_id);

COMMENT ON TABLE public.billing_customers IS
    'Customer master records for B2B/B2C invoicing under client GSTIN.';

-- 3. billing_items
CREATE TABLE IF NOT EXISTS public.billing_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    hsn_or_sac_code TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'NOS',
    default_rate BIGINT NOT NULL DEFAULT 0,
    default_tax_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 18.00,
    item_type TEXT NOT NULL DEFAULT 'goods' CHECK (item_type IN ('goods', 'service')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_items_client
    ON public.billing_items (client_gstin_id);

COMMENT ON TABLE public.billing_items IS
    'Catalog of goods and services with HSN/SAC codes, rates, and default tax percentages.';

-- 4. billing_invoices
CREATE TABLE IF NOT EXISTS public.billing_invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    company_profile_id UUID NOT NULL REFERENCES public.billing_company_profiles(id) ON DELETE RESTRICT,
    customer_id UUID NOT NULL REFERENCES public.billing_customers(id) ON DELETE RESTRICT,
    invoice_number TEXT NOT NULL,
    invoice_date DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date DATE,
    place_of_supply VARCHAR(2) NOT NULL,
    is_interstate BOOLEAN NOT NULL DEFAULT false,
    subtotal_paise BIGINT NOT NULL DEFAULT 0,
    total_tax_paise BIGINT NOT NULL DEFAULT 0,
    total_paise BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized', 'cancelled')),
    irn TEXT,
    notes TEXT,
    irn_ack_number TEXT,
    irn_ack_date TIMESTAMPTZ,
    irn_qr_code TEXT,
    irn_signed_json JSONB,
    irp_status TEXT NOT NULL DEFAULT 'not_submitted',
    irp_error_detail TEXT,
    irp_environment TEXT NOT NULL DEFAULT 'test',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_billing_invoices_client_inv_num UNIQUE (client_gstin_id, invoice_number)
);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_client
    ON public.billing_invoices (client_gstin_id);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_company
    ON public.billing_invoices (company_profile_id);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_customer
    ON public.billing_invoices (customer_id);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_irp_status
    ON public.billing_invoices (irp_status);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_irn
    ON public.billing_invoices (irn);

COMMENT ON TABLE public.billing_invoices IS
    'Sales invoices, tax breakdowns, and Government IRP registration details.';

-- 5. billing_invoice_line_items
CREATE TABLE IF NOT EXISTS public.billing_invoice_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES public.billing_invoices(id) ON DELETE CASCADE,
    item_id UUID REFERENCES public.billing_items(id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    hsn_or_sac_code TEXT NOT NULL,
    quantity NUMERIC(12,4) NOT NULL DEFAULT 1.0000,
    unit TEXT NOT NULL DEFAULT 'NOS',
    rate_paise BIGINT NOT NULL DEFAULT 0,
    discount_percent NUMERIC(5,2) DEFAULT 0.00,
    taxable_value_paise BIGINT NOT NULL DEFAULT 0,
    cgst_rate_percent NUMERIC(5,2) DEFAULT 0.00,
    cgst_paise BIGINT DEFAULT 0,
    sgst_rate_percent NUMERIC(5,2) DEFAULT 0.00,
    sgst_paise BIGINT DEFAULT 0,
    igst_rate_percent NUMERIC(5,2) DEFAULT 0.00,
    igst_paise BIGINT DEFAULT 0,
    cess_paise BIGINT DEFAULT 0,
    line_total_paise BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_billing_line_items_invoice
    ON public.billing_invoice_line_items (invoice_id);

COMMENT ON TABLE public.billing_invoice_line_items IS
    'Itemized line entries for invoices with quantity, rates, and granular GST tax values.';

-- 6. billing_credit_debit_notes
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_billing_cdn_client_num UNIQUE (client_gstin_id, note_number)
);

CREATE INDEX IF NOT EXISTS idx_billing_cdn_client
    ON public.billing_credit_debit_notes (client_gstin_id);

CREATE INDEX IF NOT EXISTS idx_billing_cdn_orig_inv
    ON public.billing_credit_debit_notes (original_invoice_id);

CREATE INDEX IF NOT EXISTS idx_billing_cdn_irp_status
    ON public.billing_credit_debit_notes (irp_status);

CREATE INDEX IF NOT EXISTS idx_billing_cdn_irn
    ON public.billing_credit_debit_notes (irn);

COMMENT ON TABLE public.billing_credit_debit_notes IS
    'Credit and debit notes linked to original e-invoices with statutory reasons and IRP registration.';

-- 7. billing_cdn_line_items
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_cdn_line_items_cdn
    ON public.billing_cdn_line_items (cdn_id);

COMMENT ON TABLE public.billing_cdn_line_items IS
    'Itemized line entries for credit and debit notes with taxes and line totals.';

-- 8. billing_irp_submission_log
CREATE TABLE IF NOT EXISTS public.billing_irp_submission_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES public.billing_invoices(id) ON DELETE CASCADE,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    environment TEXT NOT NULL DEFAULT 'test',
    request_payload JSONB,
    response_status TEXT NOT NULL,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_irp_log_invoice
    ON public.billing_irp_submission_log (invoice_id);

CREATE INDEX IF NOT EXISTS idx_billing_irp_log_client
    ON public.billing_irp_submission_log (client_gstin_id);

COMMENT ON TABLE public.billing_irp_submission_log IS
    'Immutable audit log of all IRP submission requests, responses, and network payloads.';

-- 9. RPC function for atomic sequential invoice numbering
CREATE OR REPLACE FUNCTION public.increment_invoice_number_seq(p_profile_id uuid)
RETURNS TABLE (prefix text, seq bigint)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.billing_company_profiles
    SET invoice_number_next_seq = invoice_number_next_seq + 1,
        updated_at = clock_timestamp()
    WHERE id = p_profile_id
    RETURNING invoice_number_prefix AS prefix, (invoice_number_next_seq - 1) AS seq;
END;
$$;
