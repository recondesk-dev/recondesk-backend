-- ============================================================================
-- Migration: 20261005100000_create_batch2c_compliance_and_work_items.up.sql
-- Description: Phase 9D-11 (Batch 2C) - Vendor Compliance Scorecard, Audit, 
--              Work Items & Vendor Follow-up Logs:
--              1. supplier_compliance_summary
--              2. supplier_compliance_by_client
--              3. supplier_followup_audit
--              4. itc_work_items
--              5. itc_work_item_events
--              6. vendor_followup_logs
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.supplier_compliance_summary
-- Firm-level rollup of supplier compliance metrics keyed by (firm_owner_id, supplier_gstin_normalized)
CREATE TABLE IF NOT EXISTS public.supplier_compliance_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    supplier_gstin_normalized CHAR(15) NOT NULL,
    supplier_trade_name TEXT NOT NULL DEFAULT '',
    client_gstin_ids UUID[] NOT NULL DEFAULT '{}',
    clients_touched_count INTEGER NOT NULL DEFAULT 0,
    total_invoices INTEGER NOT NULL DEFAULT 0,
    mismatch_invoice_count INTEGER NOT NULL DEFAULT 0,
    mismatch_rate NUMERIC(5, 4) NOT NULL DEFAULT 0,
    rule37_open_count INTEGER NOT NULL DEFAULT 0,
    rule37_at_risk_paise BIGINT NOT NULL DEFAULT 0,
    section_17_5_count INTEGER NOT NULL DEFAULT 0,
    late_filing_count INTEGER NOT NULL DEFAULT 0,
    late_filing_rate NUMERIC(5, 4) NOT NULL DEFAULT 0,
    pr_only_count INTEGER NOT NULL DEFAULT 0,
    quarterly_filer_flag BOOLEAN NOT NULL DEFAULT FALSE,
    risk_score INTEGER NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT supplier_compliance_summary_unique
        UNIQUE (firm_owner_id, supplier_gstin_normalized),
    CONSTRAINT supplier_compliance_summary_gstin_len
        CHECK (char_length(supplier_gstin_normalized) = 15),
    CONSTRAINT supplier_compliance_summary_risk_score_range
        CHECK (risk_score >= 0 AND risk_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_firm_risk
    ON public.supplier_compliance_summary (firm_owner_id, risk_score DESC);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_firm_clients
    ON public.supplier_compliance_summary (firm_owner_id, clients_touched_count DESC);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_firm_updated
    ON public.supplier_compliance_summary (firm_owner_id, last_updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_summary_client_ids
    ON public.supplier_compliance_summary USING GIN (client_gstin_ids);


-- 2. Table: public.supplier_compliance_by_client
-- Per-client contribution counters for vendor compliance scorecard (refreshed on run complete)
CREATE TABLE IF NOT EXISTS public.supplier_compliance_by_client (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    supplier_gstin_normalized CHAR(15) NOT NULL,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    supplier_trade_name TEXT NOT NULL DEFAULT '',
    total_invoices INTEGER NOT NULL DEFAULT 0,
    mismatch_invoice_count INTEGER NOT NULL DEFAULT 0,
    rule37_open_count INTEGER NOT NULL DEFAULT 0,
    rule37_at_risk_paise BIGINT NOT NULL DEFAULT 0,
    section_17_5_count INTEGER NOT NULL DEFAULT 0,
    late_filing_count INTEGER NOT NULL DEFAULT 0,
    pr_only_count INTEGER NOT NULL DEFAULT 0,
    quarterly_filer_flag BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT supplier_compliance_by_client_unique
        UNIQUE (firm_owner_id, supplier_gstin_normalized, client_gstin_id),
    CONSTRAINT supplier_compliance_by_client_gstin_len
        CHECK (char_length(supplier_gstin_normalized) = 15)
);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_by_client_firm_supplier
    ON public.supplier_compliance_by_client (firm_owner_id, supplier_gstin_normalized);

CREATE INDEX IF NOT EXISTS idx_supplier_compliance_by_client_client
    ON public.supplier_compliance_by_client (client_gstin_id);


-- 3. Table: public.supplier_followup_audit
-- Audit trail for supplier follow-up letters and communication snapshots
CREATE TABLE IF NOT EXISTS public.supplier_followup_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    tax_period VARCHAR(7) NOT NULL,
    supplier_gstin TEXT NOT NULL,
    record_ids TEXT[] NOT NULL DEFAULT '{}',
    invoice_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    template_type TEXT NOT NULL,
    generated_by UUID NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL,
    supplier_name_display TEXT,
    letter_body TEXT,

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


-- 4. Table: public.itc_work_items
-- Exception Work Item Lifecycle Engine for CA operational exception handling
CREATE TABLE IF NOT EXISTS public.itc_work_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    record_id TEXT NOT NULL,
    exception_type VARCHAR(50) NOT NULL,

    -- Operational Lifecycle Status
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN',

    -- Priority with Manual Override Tracking
    priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    system_priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    manual_priority VARCHAR(20),
    priority_override_reason TEXT,
    priority_changed_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    priority_changed_at TIMESTAMPTZ,

    -- Categorization and CA Guidance
    category VARCHAR(50) NOT NULL DEFAULT 'OTHER',
    title TEXT,
    what TEXT NOT NULL DEFAULT '',
    why TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',

    -- Ownership Assignment
    assigned_to UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ,
    assigned_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Due Dates and SLA Status
    due_at TIMESTAMPTZ,
    sla_status VARCHAR(20) NOT NULL DEFAULT 'NO_DUE_DATE',

    -- Structured Resolution
    resolution_code VARCHAR(50),
    resolution_note TEXT,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Dismissal and Reopen
    dismissal_reason TEXT,
    dismissed_at TIMESTAMPTZ,
    dismissed_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    reopen_reason TEXT,
    reopened_at TIMESTAMPTZ,
    reopened_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Revalidation Hook
    revalidation_status VARCHAR(30) NOT NULL DEFAULT 'NONE',
    revalidation_requested_at TIMESTAMPTZ,
    revalidation_completed_at TIMESTAMPTZ,
    revalidation_result VARCHAR(30),

    -- Lineage and Source Versioning
    source_version INTEGER NOT NULL DEFAULT 1,
    carried_forward_from_id UUID REFERENCES public.itc_work_items(id) ON DELETE SET NULL,

    -- Contextual Invoice & Tax Snapshots
    vendor_gstin VARCHAR(15),
    vendor_name TEXT,
    invoice_number VARCHAR(100),
    invoice_date DATE,
    taxable_value NUMERIC(15,2) NOT NULL DEFAULT 0,
    igst NUMERIC(15,2) NOT NULL DEFAULT 0,
    cgst NUMERIC(15,2) NOT NULL DEFAULT 0,
    sgst NUMERIC(15,2) NOT NULL DEFAULT 0,
    cess NUMERIC(15,2) NOT NULL DEFAULT 0,
    total_tax NUMERIC(15,2) NOT NULL DEFAULT 0,
    itc_amount_at_stake NUMERIC(15,2) NOT NULL DEFAULT 0,
    itc_amount_at_stake_paise BIGINT NOT NULL DEFAULT 0,
    is_blocking BOOLEAN NOT NULL DEFAULT FALSE,

    -- System Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, NOW()),
    created_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, NOW()),
    updated_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Authoritative Canonical Uniqueness Constraint
    CONSTRAINT uq_itc_work_item UNIQUE (run_id, record_id, exception_type)
);

CREATE INDEX IF NOT EXISTS idx_itc_work_items_firm ON public.itc_work_items (firm_owner_id);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_client ON public.itc_work_items (client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_run ON public.itc_work_items (run_id);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_assigned ON public.itc_work_items (assigned_to);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_status ON public.itc_work_items (status);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_priority ON public.itc_work_items (priority);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_due ON public.itc_work_items (due_at);


-- 5. Table: public.itc_work_item_events
-- Audit and activity timeline for ITC work item state transitions
CREATE TABLE IF NOT EXISTS public.itc_work_item_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_item_id UUID NOT NULL REFERENCES public.itc_work_items(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    from_status VARCHAR(30),
    to_status VARCHAR(30),
    actor_id UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    actor_role VARCHAR(20),
    actor_name VARCHAR(150),
    note TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, NOW())
);

CREATE INDEX IF NOT EXISTS idx_itc_wi_events_wi_id 
    ON public.itc_work_item_events (work_item_id, created_at ASC);


-- 6. Table: public.vendor_followup_logs
-- Vendor communication dispatch log with portal response and work item integration
CREATE TABLE IF NOT EXISTS public.vendor_followup_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    supplier_gstin TEXT NOT NULL,
    supplier_name TEXT,
    vendor_phone TEXT,
    vendor_email TEXT,
    channel TEXT NOT NULL DEFAULT 'WHATSAPP',
    template_type TEXT NOT NULL DEFAULT 'POLITE_REMINDER',
    invoices_count INTEGER NOT NULL DEFAULT 1,
    at_risk_itc_rupees NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    status TEXT NOT NULL DEFAULT 'SENT',
    notes TEXT,
    dispatched_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    dispatched_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, NOW()),
    work_item_id UUID REFERENCES public.itc_work_items(id) ON DELETE SET NULL,
    message_body TEXT,
    token TEXT UNIQUE,
    viewed_at TIMESTAMPTZ,
    arn_number TEXT,
    promised_period TEXT,
    dispute_reason TEXT,
    attachment_key TEXT,
    expires_at TIMESTAMPTZ,
    invoices_snapshot JSONB,
    response_action TEXT,
    responded_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_vendor_followup_client_supplier
    ON public.vendor_followup_logs (client_gstin_id, supplier_gstin);

CREATE INDEX IF NOT EXISTS idx_vendor_followup_work_item
    ON public.vendor_followup_logs (work_item_id);

CREATE INDEX IF NOT EXISTS idx_vendor_followup_token
    ON public.vendor_followup_logs (token);
