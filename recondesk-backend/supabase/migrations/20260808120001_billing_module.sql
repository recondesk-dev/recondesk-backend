-- E-Invoicing / Billing Module Schema & RLS Policies (Phase 1)

-- 1. Company Profiles
CREATE TABLE IF NOT EXISTS public.billing_company_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id uuid NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    legal_name text NOT NULL,
    trade_name text,
    address_line1 text NOT NULL DEFAULT '',
    address_line2 text,
    city text NOT NULL DEFAULT '',
    state text NOT NULL DEFAULT '',
    state_code varchar(2) NOT NULL,
    pincode text NOT NULL DEFAULT '',
    gstin text NOT NULL,
    pan text,
    bank_account_number text,
    bank_ifsc text,
    bank_name text,
    invoice_number_prefix text NOT NULL DEFAULT '',
    invoice_number_next_seq bigint NOT NULL DEFAULT 1,
    financial_year_reset boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_company_profiles_client ON public.billing_company_profiles(client_gstin_id);

-- 2. Customers
CREATE TABLE IF NOT EXISTS public.billing_customers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id uuid NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    name text NOT NULL,
    gstin text,
    address_line1 text NOT NULL DEFAULT '',
    address_line2 text,
    city text NOT NULL DEFAULT '',
    state text NOT NULL DEFAULT '',
    state_code varchar(2) NOT NULL,
    pincode text NOT NULL DEFAULT '',
    is_b2b boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_customers_client ON public.billing_customers(client_gstin_id);

-- 3. Items Catalog
CREATE TABLE IF NOT EXISTS public.billing_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id uuid NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    name text NOT NULL,
    hsn_or_sac_code text NOT NULL,
    unit text NOT NULL DEFAULT 'NOS',
    default_rate bigint NOT NULL DEFAULT 0,
    default_tax_rate_percent numeric(5,2) NOT NULL DEFAULT 18.00,
    item_type text NOT NULL DEFAULT 'goods' CHECK (item_type IN ('goods', 'service')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_items_client ON public.billing_items(client_gstin_id);

-- 4. Invoices
CREATE TABLE IF NOT EXISTS public.billing_invoices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id uuid NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    company_profile_id uuid NOT NULL REFERENCES public.billing_company_profiles(id) ON DELETE RESTRICT,
    customer_id uuid NOT NULL REFERENCES public.billing_customers(id) ON DELETE RESTRICT,
    invoice_number text NOT NULL,
    invoice_date date NOT NULL DEFAULT CURRENT_DATE,
    due_date date,
    place_of_supply varchar(2) NOT NULL,
    is_interstate boolean NOT NULL DEFAULT false,
    subtotal_paise bigint NOT NULL DEFAULT 0,
    total_tax_paise bigint NOT NULL DEFAULT 0,
    total_paise bigint NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized', 'cancelled')),
    irn text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_billing_invoices_client_inv_num UNIQUE (client_gstin_id, invoice_number)
);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_client ON public.billing_invoices(client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_company ON public.billing_invoices(company_profile_id);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_customer ON public.billing_invoices(customer_id);

-- 5. Invoice Line Items
CREATE TABLE IF NOT EXISTS public.billing_invoice_line_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id uuid NOT NULL REFERENCES public.billing_invoices(id) ON DELETE CASCADE,
    item_id uuid REFERENCES public.billing_items(id) ON DELETE SET NULL,
    description text NOT NULL,
    hsn_or_sac_code text NOT NULL,
    quantity numeric(12,4) NOT NULL DEFAULT 1.0000,
    unit text NOT NULL DEFAULT 'NOS',
    rate_paise bigint NOT NULL DEFAULT 0,
    discount_percent numeric(5,2) DEFAULT 0.00,
    taxable_value_paise bigint NOT NULL DEFAULT 0,
    cgst_rate_percent numeric(5,2) DEFAULT 0.00,
    cgst_paise bigint DEFAULT 0,
    sgst_rate_percent numeric(5,2) DEFAULT 0.00,
    sgst_paise bigint DEFAULT 0,
    igst_rate_percent numeric(5,2) DEFAULT 0.00,
    igst_paise bigint DEFAULT 0,
    cess_paise bigint DEFAULT 0,
    line_total_paise bigint NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_billing_line_items_invoice ON public.billing_invoice_line_items(invoice_id);

-- Enable RLS
ALTER TABLE public.billing_company_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_invoice_line_items ENABLE ROW LEVEL SECURITY;

-- Macro macro policies for client_gstin_id tables
DO $$
DECLARE
    t text;
BEGIN
    FOR t IN SELECT unnest(ARRAY['billing_company_profiles', 'billing_customers', 'billing_items', 'billing_invoices']) LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I_select_firm ON public.%I', t, t);
        EXECUTE format('CREATE POLICY %I_select_firm ON public.%I FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.client_gstins cg WHERE cg.id = %I.client_gstin_id AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())))', t, t, t);

        EXECUTE format('DROP POLICY IF EXISTS %I_insert_firm ON public.%I', t, t);
        EXECUTE format('CREATE POLICY %I_insert_firm ON public.%I FOR INSERT TO authenticated WITH CHECK (EXISTS (SELECT 1 FROM public.client_gstins cg WHERE cg.id = %I.client_gstin_id AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())))', t, t, t);

        EXECUTE format('DROP POLICY IF EXISTS %I_update_firm ON public.%I', t, t);
        EXECUTE format('CREATE POLICY %I_update_firm ON public.%I FOR UPDATE TO authenticated USING (EXISTS (SELECT 1 FROM public.client_gstins cg WHERE cg.id = %I.client_gstin_id AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid()))) WITH CHECK (EXISTS (SELECT 1 FROM public.client_gstins cg WHERE cg.id = %I.client_gstin_id AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())))', t, t, t, t);

        EXECUTE format('DROP POLICY IF EXISTS %I_delete_firm ON public.%I', t, t);
        EXECUTE format('CREATE POLICY %I_delete_firm ON public.%I FOR DELETE TO authenticated USING (EXISTS (SELECT 1 FROM public.client_gstins cg WHERE cg.id = %I.client_gstin_id AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())))', t, t);

        EXECUTE format('GRANT ALL ON public.%I TO service_role', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END LOOP;
END $$;

-- Line items RLS policies
DROP POLICY IF EXISTS billing_invoice_line_items_select_firm ON public.billing_invoice_line_items;
CREATE POLICY billing_invoice_line_items_select_firm ON public.billing_invoice_line_items
    FOR SELECT TO authenticated USING (
        EXISTS (
            SELECT 1 FROM public.billing_invoices bi
            JOIN public.client_gstins cg ON cg.id = bi.client_gstin_id
            WHERE bi.id = billing_invoice_line_items.invoice_id
              AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())
        )
    );

DROP POLICY IF EXISTS billing_invoice_line_items_insert_firm ON public.billing_invoice_line_items;
CREATE POLICY billing_invoice_line_items_insert_firm ON public.billing_invoice_line_items
    FOR INSERT TO authenticated WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.billing_invoices bi
            JOIN public.client_gstins cg ON cg.id = bi.client_gstin_id
            WHERE bi.id = billing_invoice_line_items.invoice_id
              AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())
        )
    );

DROP POLICY IF EXISTS billing_invoice_line_items_update_firm ON public.billing_invoice_line_items;
CREATE POLICY billing_invoice_line_items_update_firm ON public.billing_invoice_line_items
    FOR UPDATE TO authenticated USING (
        EXISTS (
            SELECT 1 FROM public.billing_invoices bi
            JOIN public.client_gstins cg ON cg.id = bi.client_gstin_id
            WHERE bi.id = billing_invoice_line_items.invoice_id
              AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())
        )
    ) WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.billing_invoices bi
            JOIN public.client_gstins cg ON cg.id = bi.client_gstin_id
            WHERE bi.id = billing_invoice_line_items.invoice_id
              AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())
        )
    );

DROP POLICY IF EXISTS billing_invoice_line_items_delete_firm ON public.billing_invoice_line_items;
CREATE POLICY billing_invoice_line_items_delete_firm ON public.billing_invoice_line_items
    FOR DELETE TO authenticated USING (
        EXISTS (
            SELECT 1 FROM public.billing_invoices bi
            JOIN public.client_gstins cg ON cg.id = bi.client_gstin_id
            WHERE bi.id = billing_invoice_line_items.invoice_id
              AND (cg.firm_owner_id = auth.uid() OR cg.assigned_to = auth.uid())
        )
    );

GRANT ALL ON public.billing_invoice_line_items TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.billing_invoice_line_items TO authenticated;

-- RPC for atomic invoice sequence increment
CREATE OR REPLACE FUNCTION public.increment_invoice_number_seq(p_profile_id uuid)
RETURNS TABLE (prefix text, seq bigint)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.billing_company_profiles
    SET invoice_number_next_seq = invoice_number_next_seq + 1,
        updated_at = now()
    WHERE id = p_profile_id
    RETURNING invoice_number_prefix AS prefix, (invoice_number_next_seq - 1) AS seq;
END;
$$;
GRANT EXECUTE ON FUNCTION public.increment_invoice_number_seq(uuid) TO authenticated, service_role;

