-- Audit trail for supplier follow-up letters (ITC at risk).
-- Snapshots are written by the API from client payload at generation time.

CREATE TABLE IF NOT EXISTS public.supplier_followup_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    tax_period varchar(7) NOT NULL,
    supplier_gstin text NOT NULL,
    record_ids text[] NOT NULL,
    invoice_snapshot jsonb NOT NULL,
    template_type text NOT NULL,
    generated_by uuid NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL,
    supplier_name_display text,
    CONSTRAINT supplier_followup_audit_status_check
        CHECK (status IN ('generated', 'downloaded', 'copied')),
    CONSTRAINT supplier_followup_audit_template_check
        CHECK (template_type IN ('wrongful_itc_single', 'wrongful_itc_bulk'))
);

CREATE INDEX IF NOT EXISTS idx_supplier_followup_audit_run_id
    ON public.supplier_followup_audit (run_id);

CREATE INDEX IF NOT EXISTS idx_supplier_followup_audit_supplier
    ON public.supplier_followup_audit (run_id, supplier_gstin);

CREATE INDEX IF NOT EXISTS idx_supplier_followup_audit_period
    ON public.supplier_followup_audit (tax_period, generated_at DESC);
