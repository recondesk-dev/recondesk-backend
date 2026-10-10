-- Migration: 20261010160000_ewaybill_tables.sql
-- E-Way Bill Management Suite (Part A, Part B, Vehicle Updates, Cancellations)

CREATE TABLE IF NOT EXISTS public.eway_bills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    invoice_id UUID REFERENCES public.invoices(id) ON DELETE SET NULL,
    ewb_number TEXT NOT NULL UNIQUE,
    ewb_date TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    valid_until TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE', 'PART_A_ONLY', 'CANCELLED', 'EXPIRED'
    
    -- Document Metadata
    doc_type TEXT NOT NULL DEFAULT 'INV',
    doc_number TEXT NOT NULL,
    doc_date DATE NOT NULL,
    supply_type TEXT NOT NULL DEFAULT 'O',
    sub_supply_type TEXT NOT NULL DEFAULT '1',
    sub_supply_desc TEXT,
    
    -- Consignor / Consignee
    from_gstin TEXT NOT NULL,
    from_trade_name TEXT NOT NULL,
    from_addr1 TEXT NOT NULL,
    from_addr2 TEXT,
    from_place TEXT NOT NULL,
    from_pincode INT NOT NULL,
    from_state_code TEXT NOT NULL,
    
    to_gstin TEXT NOT NULL,
    to_trade_name TEXT NOT NULL,
    to_addr1 TEXT NOT NULL,
    to_addr2 TEXT,
    to_place TEXT NOT NULL,
    to_pincode INT NOT NULL,
    to_state_code TEXT NOT NULL,
    
    -- Financial Totals
    total_taxable_value NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cgst_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    sgst_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    igst_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cess_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_invoice_value NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    
    -- Part B Transport Details
    transporter_id TEXT,
    transporter_name TEXT,
    trans_mode TEXT NOT NULL DEFAULT '1',
    distance_km INT NOT NULL DEFAULT 10,
    trans_doc_no TEXT,
    trans_doc_date DATE,
    vehicle_no TEXT,
    vehicle_type TEXT NOT NULL DEFAULT 'R',
    
    -- Vehicle History & State
    vehicle_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    nic_payload JSONB,
    qr_code TEXT,
    
    -- Cancellation
    cancel_reason TEXT,
    cancel_remarks TEXT,
    cancelled_at TIMESTAMPTZ,
    
    created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_eway_bills_client_gstin ON public.eway_bills(client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_eway_bills_doc_no ON public.eway_bills(doc_number);
CREATE INDEX IF NOT EXISTS idx_eway_bills_ewb_no ON public.eway_bills(ewb_number);

ALTER TABLE public.eway_bills ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow all access to eway_bills for authenticated users" ON public.eway_bills;
CREATE POLICY "Allow all access to eway_bills"
ON public.eway_bills FOR ALL TO authenticated, service_role, anon USING (true) WITH CHECK (true);
