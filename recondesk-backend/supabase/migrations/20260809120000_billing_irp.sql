-- Add e-Invoice IRP submission columns to billing_invoices
ALTER TABLE public.billing_invoices
  ADD COLUMN IF NOT EXISTS irn_ack_number TEXT,
  ADD COLUMN IF NOT EXISTS irn_ack_date TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS irn_qr_code TEXT,
  ADD COLUMN IF NOT EXISTS irn_signed_json JSONB,
  ADD COLUMN IF NOT EXISTS irp_status TEXT NOT NULL DEFAULT 'not_submitted',
  ADD COLUMN IF NOT EXISTS irp_error_detail TEXT,
  ADD COLUMN IF NOT EXISTS irp_environment TEXT NOT NULL DEFAULT 'test';

-- Indexes for fast IRP status and IRN lookup
CREATE INDEX IF NOT EXISTS idx_billing_invoices_irp_status ON public.billing_invoices(irp_status);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_irn ON public.billing_invoices(irn);

-- Create billing_irp_submission_log table
CREATE TABLE IF NOT EXISTS public.billing_irp_submission_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id       UUID NOT NULL REFERENCES public.billing_invoices(id) ON DELETE CASCADE,
    client_gstin_id  UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    attempted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    environment      TEXT NOT NULL DEFAULT 'test',
    request_payload  JSONB,
    response_status  TEXT NOT NULL,
    response_body    JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_irp_log_invoice ON public.billing_irp_submission_log(invoice_id);
CREATE INDEX IF NOT EXISTS idx_billing_irp_log_client ON public.billing_irp_submission_log(client_gstin_id);

ALTER TABLE IF EXISTS public.billing_irp_submission_log DISABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.billing_irp_submission_log TO anon, authenticated, service_role;
