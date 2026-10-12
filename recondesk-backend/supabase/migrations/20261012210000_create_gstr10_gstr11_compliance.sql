-- ============================================================================
-- Migration: 20261012210000_create_gstr10_gstr11_compliance.sql
-- Description: Phase 4.4 - GSTR-10 (Final Return) & GSTR-11 (UIN Return) Compliance Tables
-- Target: Supabase PostgreSQL
-- ============================================================================

-- 0. Extend return_filing_approvals and client_filing_authorizations check constraints
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'return_filing_approvals_return_type_check'
          AND table_name = 'return_filing_approvals'
    ) THEN
        ALTER TABLE public.return_filing_approvals
            DROP CONSTRAINT return_filing_approvals_return_type_check;
        ALTER TABLE public.return_filing_approvals
            ADD CONSTRAINT return_filing_approvals_return_type_check
            CHECK (return_type IN (
                'GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C', 'GSTR-1A', 'GSTR-7', 'GSTR-8',
                'GSTR-6', 'GSTR-5', 'GSTR-5A', 'GSTR-10', 'GSTR-11'
            ));
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'client_filing_authorizations_return_type_check'
          AND table_name = 'client_filing_authorizations'
    ) THEN
        ALTER TABLE public.client_filing_authorizations
            DROP CONSTRAINT client_filing_authorizations_return_type_check;
        ALTER TABLE public.client_filing_authorizations
            ADD CONSTRAINT client_filing_authorizations_return_type_check
            CHECK (return_type IN (
                'GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C', 'GSTR-1A', 'GSTR-7', 'GSTR-8',
                'GSTR-6', 'GSTR-5', 'GSTR-5A', 'GSTR-10', 'GSTR-11'
            ));
    END IF;
END $$;

-- 1. Create GSTR-10 Batches Table
CREATE TABLE IF NOT EXISTS public.gstr10_batches (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                     UUID NOT NULL,
    client_gstin_id             UUID NOT NULL,
    gstin                       VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL,
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    figures_digest              VARCHAR(64) NOT NULL,
    cancellation_order_number   VARCHAR(100),
    cancellation_order_date     DATE,
    effective_cancellation_date DATE,
    cancellation_arn            VARCHAR(50),
    cancellation_arn_date       DATE,
    statutory_due_date          DATE,
    total_taxable_value         NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_reversal_igst         NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_reversal_cgst         NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_reversal_sgst         NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_reversal_cess         NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_reversal_liability    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    tax_paid_cash               NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    tax_paid_credit             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    interest_payable            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    late_fee_payable            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id           VARCHAR(100),
    gstn_status                 VARCHAR(30),
    arn                         VARCHAR(50),
    filing_run_id               UUID,
    created_by                  UUID,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr10_batches_firm_gstin_period UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr10_batches_firm ON public.gstr10_batches(firm_id);
CREATE INDEX IF NOT EXISTS idx_gstr10_batches_client ON public.gstr10_batches(client_gstin_id);

-- 2. Create GSTR-10 Closing Stock Records Table (Table 8A, 8B, 8C, 8D)
CREATE TABLE IF NOT EXISTS public.gstr10_stock_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr10_batches(id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    item_type               VARCHAR(10) NOT NULL, -- 8A, 8B, 8C, 8D
    supplier_gstin          VARCHAR(15),
    invoice_number          VARCHAR(100),
    invoice_date            DATE,
    description             VARCHAR(255) NOT NULL,
    uqc                     VARCHAR(10) NOT NULL DEFAULT 'NOS',
    quantity                NUMERIC(15, 4) NOT NULL DEFAULT 1.0000,
    taxable_value           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    reverse_igst            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    reverse_cgst            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    reverse_sgst            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    reverse_cess            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    ca_name                 VARCHAR(255),
    ca_membership_number    VARCHAR(50),
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr10_stock_records_batch ON public.gstr10_stock_records(batch_id);
CREATE INDEX IF NOT EXISTS idx_gstr10_stock_records_firm ON public.gstr10_stock_records(firm_id);

-- 3. Create GSTR-10 Audit Trail Table
CREATE TABLE IF NOT EXISTS public.gstr10_audit_trail (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id    UUID NOT NULL,
    firm_id     UUID NOT NULL,
    action      VARCHAR(50) NOT NULL,
    actor_id    UUID,
    actor_name  VARCHAR(255) NOT NULL,
    actor_role  VARCHAR(50) NOT NULL,
    from_status VARCHAR(30),
    to_status   VARCHAR(30),
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr10_audit_batch ON public.gstr10_audit_trail(batch_id);
CREATE INDEX IF NOT EXISTS idx_gstr10_audit_firm ON public.gstr10_audit_trail(firm_id);

-- 4. Create GSTR-11 Batches Table (UIN Return)
CREATE TABLE IF NOT EXISTS public.gstr11_batches (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                     UUID NOT NULL,
    client_gstin_id             UUID NOT NULL,
    uin                         VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL,
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    figures_digest              VARCHAR(64) NOT NULL,
    statutory_due_date          DATE,
    total_inward_taxable        NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_gross_igst            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_gross_cgst            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_gross_sgst            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_gross_cess            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cdn_adjustment_igst   NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cdn_adjustment_cgst   NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cdn_adjustment_sgst   NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cdn_adjustment_cess   NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_eligible_refund_igst    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_eligible_refund_cgst    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_eligible_refund_sgst    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_eligible_refund_cess    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_net_refund_claimed    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id           VARCHAR(100),
    gstn_status                 VARCHAR(30),
    arn                         VARCHAR(50),
    filing_run_id               UUID,
    created_by                  UUID,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr11_batches_firm_uin_period UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr11_batches_firm ON public.gstr11_batches(firm_id);
CREATE INDEX IF NOT EXISTS idx_gstr11_batches_client ON public.gstr11_batches(client_gstin_id);

-- 5. Create GSTR-11 Inward Records Table (Table 3A Inward Invoices & Table 3B CDN)
CREATE TABLE IF NOT EXISTS public.gstr11_inward_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr11_batches(id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    supply_type             VARCHAR(10) NOT NULL, -- 3A, 3B
    supplier_gstin          VARCHAR(15) NOT NULL,
    supplier_name           VARCHAR(255),
    doc_number              VARCHAR(100) NOT NULL,
    doc_date                DATE NOT NULL,
    cdn_type                VARCHAR(5), -- 'C', 'D'
    original_invoice_number VARCHAR(100),
    original_invoice_date   DATE,
    taxable_value           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    igst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    sgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cess                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    is_eligible_for_refund  BOOLEAN NOT NULL DEFAULT TRUE,
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr11_inward_records_batch ON public.gstr11_inward_records(batch_id);
CREATE INDEX IF NOT EXISTS idx_gstr11_inward_records_firm ON public.gstr11_inward_records(firm_id);

-- 6. Create GSTR-11 Audit Trail Table
CREATE TABLE IF NOT EXISTS public.gstr11_audit_trail (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id    UUID NOT NULL,
    firm_id     UUID NOT NULL,
    action      VARCHAR(50) NOT NULL,
    actor_id    UUID,
    actor_name  VARCHAR(255) NOT NULL,
    actor_role  VARCHAR(50) NOT NULL,
    from_status VARCHAR(30),
    to_status   VARCHAR(30),
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr11_audit_batch ON public.gstr11_audit_trail(batch_id);
CREATE INDEX IF NOT EXISTS idx_gstr11_audit_firm ON public.gstr11_audit_trail(firm_id);
