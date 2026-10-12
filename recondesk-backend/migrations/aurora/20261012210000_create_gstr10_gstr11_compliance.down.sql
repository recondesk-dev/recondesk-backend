-- ============================================================================
-- Migration: 20261012210000_create_gstr10_gstr11_compliance.down.sql
-- Description: Phase 4.4 - Safe Non-Destructive Rollback of GSTR-10 & GSTR-11
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration. Schema downgrades on live databases risk breaking
-- statutory audit records.
--
-- This script implements a NON-DESTRUCTIVE archival rollback pattern:
-- 1. Archives audit trail history into `_archive_gstr10_audit_trail_rollback` & `_archive_gstr11_...`.
-- 2. Archives active stock & inward records into `_archive_gstr10_stock_records_rollback`, etc.
-- 3. Archives active batches into `_archive_gstr10_batches_rollback`, etc.
-- 4. Safely drops active tables only after records are durably archived.
-- ============================================================================

-- 1. Archive GSTR-10 Audit Trail
CREATE TABLE IF NOT EXISTS public._archive_gstr10_audit_trail_rollback (
    archive_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id        UUID NOT NULL,
    batch_id        UUID NOT NULL,
    firm_id         UUID NOT NULL,
    action          VARCHAR(50) NOT NULL,
    actor_id        UUID,
    actor_name      VARCHAR(255) NOT NULL,
    actor_role      VARCHAR(50) NOT NULL,
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr10_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr10_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr10_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 2. Archive GSTR-10 Stock Records
CREATE TABLE IF NOT EXISTS public._archive_gstr10_stock_records_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    item_type               VARCHAR(10) NOT NULL,
    supplier_gstin          VARCHAR(15),
    invoice_number          VARCHAR(100),
    invoice_date            DATE,
    description             VARCHAR(255) NOT NULL,
    uqc                     VARCHAR(10) NOT NULL,
    quantity                NUMERIC(15, 4) NOT NULL,
    taxable_value           NUMERIC(15, 2) NOT NULL,
    reverse_igst            NUMERIC(15, 2) NOT NULL,
    reverse_cgst            NUMERIC(15, 2) NOT NULL,
    reverse_sgst            NUMERIC(15, 2) NOT NULL,
    reverse_cess            NUMERIC(15, 2) NOT NULL,
    ca_name                 VARCHAR(255),
    ca_membership_number    VARCHAR(50),
    status                  VARCHAR(20) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr10_stock_records'
    ) THEN
        INSERT INTO public._archive_gstr10_stock_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, item_type, supplier_gstin,
            invoice_number, invoice_date, description, uqc, quantity, taxable_value,
            reverse_igst, reverse_cgst, reverse_sgst, reverse_cess, ca_name,
            ca_membership_number, status, created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, item_type, supplier_gstin,
               invoice_number, invoice_date, description, uqc, quantity, taxable_value,
               reverse_igst, reverse_cgst, reverse_sgst, reverse_cess, ca_name,
               ca_membership_number, status, created_at, updated_at
        FROM public.gstr10_stock_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 3. Archive GSTR-10 Batches
CREATE TABLE IF NOT EXISTS public._archive_gstr10_batches_rollback (
    archive_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                    UUID NOT NULL,
    firm_id                     UUID NOT NULL,
    client_gstin_id             UUID NOT NULL,
    gstin                       VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL,
    status                      VARCHAR(30) NOT NULL,
    figures_digest              VARCHAR(64) NOT NULL,
    cancellation_order_number   VARCHAR(100),
    cancellation_order_date     DATE,
    effective_cancellation_date DATE,
    cancellation_arn            VARCHAR(50),
    cancellation_arn_date       DATE,
    statutory_due_date          DATE,
    total_taxable_value         NUMERIC(15, 2) NOT NULL,
    total_reversal_igst         NUMERIC(15, 2) NOT NULL,
    total_reversal_cgst         NUMERIC(15, 2) NOT NULL,
    total_reversal_sgst         NUMERIC(15, 2) NOT NULL,
    total_reversal_cess         NUMERIC(15, 2) NOT NULL,
    total_reversal_liability    NUMERIC(15, 2) NOT NULL,
    tax_paid_cash               NUMERIC(15, 2) NOT NULL,
    tax_paid_credit             NUMERIC(15, 2) NOT NULL,
    interest_payable            NUMERIC(15, 2) NOT NULL,
    late_fee_payable            NUMERIC(15, 2) NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL,
    updated_at                  TIMESTAMPTZ NOT NULL,
    archived_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr10_batches'
    ) THEN
        INSERT INTO public._archive_gstr10_batches_rollback (
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            cancellation_order_number, cancellation_order_date, effective_cancellation_date,
            cancellation_arn, cancellation_arn_date, statutory_due_date, total_taxable_value,
            total_reversal_igst, total_reversal_cgst, total_reversal_sgst, total_reversal_cess,
            total_reversal_liability, tax_paid_cash, tax_paid_credit, interest_payable,
            late_fee_payable, created_at, updated_at
        )
        SELECT id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
               cancellation_order_number, cancellation_order_date, effective_cancellation_date,
               cancellation_arn, cancellation_arn_date, statutory_due_date, total_taxable_value,
               total_reversal_igst, total_reversal_cgst, total_reversal_sgst, total_reversal_cess,
               total_reversal_liability, tax_paid_cash, tax_paid_credit, interest_payable,
               late_fee_payable, created_at, updated_at
        FROM public.gstr10_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 4. Archive GSTR-11 Audit Trail
CREATE TABLE IF NOT EXISTS public._archive_gstr11_audit_trail_rollback (
    archive_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id        UUID NOT NULL,
    batch_id        UUID NOT NULL,
    firm_id         UUID NOT NULL,
    action          VARCHAR(50) NOT NULL,
    actor_id        UUID,
    actor_name      VARCHAR(255) NOT NULL,
    actor_role      VARCHAR(50) NOT NULL,
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr11_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr11_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr11_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 5. Archive GSTR-11 Inward Records
CREATE TABLE IF NOT EXISTS public._archive_gstr11_inward_records_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    supply_type             VARCHAR(10) NOT NULL,
    supplier_gstin          VARCHAR(15) NOT NULL,
    supplier_name           VARCHAR(255),
    doc_number              VARCHAR(100) NOT NULL,
    doc_date                DATE NOT NULL,
    cdn_type                VARCHAR(5),
    original_invoice_number VARCHAR(100),
    original_invoice_date   DATE,
    taxable_value           NUMERIC(15, 2) NOT NULL,
    igst                    NUMERIC(15, 2) NOT NULL,
    cgst                    NUMERIC(15, 2) NOT NULL,
    sgst                    NUMERIC(15, 2) NOT NULL,
    cess                    NUMERIC(15, 2) NOT NULL,
    is_eligible_for_refund  BOOLEAN NOT NULL,
    status                  VARCHAR(20) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr11_inward_records'
    ) THEN
        INSERT INTO public._archive_gstr11_inward_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, supply_type, supplier_gstin,
            supplier_name, doc_number, doc_date, cdn_type, original_invoice_number,
            original_invoice_date, taxable_value, igst, cgst, sgst, cess,
            is_eligible_for_refund, status, created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, supply_type, supplier_gstin,
               supplier_name, doc_number, doc_date, cdn_type, original_invoice_number,
               original_invoice_date, taxable_value, igst, cgst, sgst, cess,
               is_eligible_for_refund, status, created_at, updated_at
        FROM public.gstr11_inward_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 6. Archive GSTR-11 Batches
CREATE TABLE IF NOT EXISTS public._archive_gstr11_batches_rollback (
    archive_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                    UUID NOT NULL,
    firm_id                     UUID NOT NULL,
    client_gstin_id             UUID NOT NULL,
    uin                         VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL,
    status                      VARCHAR(30) NOT NULL,
    figures_digest              VARCHAR(64) NOT NULL,
    statutory_due_date          DATE,
    total_inward_taxable        NUMERIC(15, 2) NOT NULL,
    total_gross_igst            NUMERIC(15, 2) NOT NULL,
    total_gross_cgst            NUMERIC(15, 2) NOT NULL,
    total_gross_sgst            NUMERIC(15, 2) NOT NULL,
    total_gross_cess            NUMERIC(15, 2) NOT NULL,
    total_cdn_adjustment_igst   NUMERIC(15, 2) NOT NULL,
    total_cdn_adjustment_cgst   NUMERIC(15, 2) NOT NULL,
    total_cdn_adjustment_sgst   NUMERIC(15, 2) NOT NULL,
    total_cdn_adjustment_cess   NUMERIC(15, 2) NOT NULL,
    net_eligible_refund_igst    NUMERIC(15, 2) NOT NULL,
    net_eligible_refund_cgst    NUMERIC(15, 2) NOT NULL,
    net_eligible_refund_sgst    NUMERIC(15, 2) NOT NULL,
    net_eligible_refund_cess    NUMERIC(15, 2) NOT NULL,
    total_net_refund_claimed    NUMERIC(15, 2) NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL,
    updated_at                  TIMESTAMPTZ NOT NULL,
    archived_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr11_batches'
    ) THEN
        INSERT INTO public._archive_gstr11_batches_rollback (
            batch_id, firm_id, client_gstin_id, uin, period, status, figures_digest,
            statutory_due_date, total_inward_taxable, total_gross_igst, total_gross_cgst,
            total_gross_sgst, total_gross_cess, total_cdn_adjustment_igst, total_cdn_adjustment_cgst,
            total_cdn_adjustment_sgst, total_cdn_adjustment_cess, net_eligible_refund_igst,
            net_eligible_refund_cgst, net_eligible_refund_sgst, net_eligible_refund_cess,
            total_net_refund_claimed, created_at, updated_at
        )
        SELECT id, firm_id, client_gstin_id, uin, period, status, figures_digest,
               statutory_due_date, total_inward_taxable, total_gross_igst, total_gross_cgst,
               total_gross_sgst, total_gross_cess, total_cdn_adjustment_igst, total_cdn_adjustment_cgst,
               total_cdn_adjustment_sgst, total_cdn_adjustment_cess, net_eligible_refund_igst,
               net_eligible_refund_cgst, net_eligible_refund_sgst, net_eligible_refund_cess,
               total_net_refund_claimed, created_at, updated_at
        FROM public.gstr11_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 7. Safely Drop Active Tables (Dependent tables first)
DROP TABLE IF EXISTS public.gstr10_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr10_stock_records CASCADE;
DROP TABLE IF EXISTS public.gstr10_batches CASCADE;

DROP TABLE IF EXISTS public.gstr11_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr11_inward_records CASCADE;
DROP TABLE IF EXISTS public.gstr11_batches CASCADE;

-- 8. Revert check constraints to Phase 4.3 return types
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
                'GSTR-6', 'GSTR-5', 'GSTR-5A'
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
                'GSTR-6', 'GSTR-5', 'GSTR-5A'
            ));
    END IF;
END $$;
