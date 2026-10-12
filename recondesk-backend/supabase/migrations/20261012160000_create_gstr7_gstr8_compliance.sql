-- ============================================================================
-- Migration: 20261012160000_create_gstr7_gstr8_compliance.sql
-- Description: Phase 4.2 - GSTR-7 (TDS) and GSTR-8 (TCS) Compliance Intelligence
--              Tables for TDS/TCS batches, records, statutory checks,
--              reconciliation, and immutable audit trails.
-- Target: Supabase / PostgreSQL
-- ============================================================================

-- 1. Extend return_filing_approvals check constraint to include GSTR-7 and GSTR-8
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
            CHECK (return_type IN ('GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C', 'GSTR-1A', 'GSTR-7', 'GSTR-8'));
    END IF;
END $$;

-- 2. Extend client_filing_authorizations check constraint to include GSTR-7 and GSTR-8
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
            CHECK (return_type IN ('GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C', 'GSTR-1A', 'GSTR-7', 'GSTR-8'));
    END IF;
END $$;

-- 3. Table: public.gstr7_batches
CREATE TABLE IF NOT EXISTS public.gstr7_batches (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                   VARCHAR(15) NOT NULL,
    period                  VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status                  VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                            CHECK (status IN (
                                'DRAFT',
                                'PREPARED',
                                'UNDER_REVIEW',
                                'APPROVED',
                                'REJECTED',
                                'SAVED',
                                'FILED'
                            )),
    figures_digest          VARCHAR(64) NOT NULL DEFAULT '',
    total_records           INT NOT NULL DEFAULT 0,
    total_amendments        INT NOT NULL DEFAULT 0,
    total_amount_paid       NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tds_igst          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tds_cgst          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tds_sgst          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tds_deposited     NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id       VARCHAR(100),
    gstn_status             VARCHAR(20),
    arn                     VARCHAR(50),
    filing_run_id           UUID REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    created_by              UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr7_batch UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr7_batches_lookup
    ON public.gstr7_batches (firm_id, client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_gstr7_batches_status
    ON public.gstr7_batches (status);

-- 4. Table: public.gstr7_records
CREATE TABLE IF NOT EXISTS public.gstr7_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr7_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    period                  VARCHAR(7) NOT NULL,
    record_type             VARCHAR(20) NOT NULL DEFAULT 'ORIGINAL'
                            CHECK (record_type IN ('ORIGINAL', 'AMENDMENT')),
    deductee_gstin          VARCHAR(15) NOT NULL,
    contract_number         VARCHAR(100),
    contract_value          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    payment_reference       VARCHAR(100),
    payment_date            DATE,
    amount_paid             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    supplier_state          VARCHAR(2) NOT NULL DEFAULT '',
    pos                     VARCHAR(2) NOT NULL DEFAULT '',
    tds_rate                NUMERIC(5, 2) NOT NULL DEFAULT 2.00,
    tds_igst                NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    tds_cgst                NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    tds_sgst                NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    original_period         VARCHAR(7),
    original_deductee_gstin VARCHAR(15),
    tax_deposited           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    is_eligible_for_tds     BOOLEAN NOT NULL DEFAULT TRUE,
    ineligibility_reason    TEXT,
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                            CHECK (status IN ('ACTIVE', 'DELETED')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr7_records_batch
    ON public.gstr7_records (batch_id, status);

CREATE INDEX IF NOT EXISTS idx_gstr7_records_deductee
    ON public.gstr7_records (deductee_gstin);

-- 5. Table: public.gstr7_audit_trail
CREATE TABLE IF NOT EXISTS public.gstr7_audit_trail (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr7_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    action                  VARCHAR(50) NOT NULL,
    actor_id                UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name              VARCHAR(255) NOT NULL DEFAULT '',
    actor_role              VARCHAR(50) NOT NULL DEFAULT '',
    from_status             VARCHAR(30),
    to_status               VARCHAR(30),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr7_audit_batch
    ON public.gstr7_audit_trail (batch_id, created_at DESC);

-- 6. Table: public.gstr8_batches
CREATE TABLE IF NOT EXISTS public.gstr8_batches (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                   VARCHAR(15) NOT NULL,
    period                  VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status                  VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                            CHECK (status IN (
                                'DRAFT',
                                'PREPARED',
                                'UNDER_REVIEW',
                                'APPROVED',
                                'REJECTED',
                                'SAVED',
                                'FILED'
                            )),
    figures_digest          VARCHAR(64) NOT NULL DEFAULT '',
    total_b2b_records       INT NOT NULL DEFAULT 0,
    total_b2c_records       INT NOT NULL DEFAULT 0,
    total_amendments        INT NOT NULL DEFAULT 0,
    gross_supplies_value    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    returned_supplies_value NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_taxable_value       NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tcs_igst          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tcs_cgst          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tcs_sgst          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_tcs_deposited     NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id       VARCHAR(100),
    gstn_status             VARCHAR(20),
    arn                     VARCHAR(50),
    filing_run_id           UUID REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    created_by              UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr8_batch UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr8_batches_lookup
    ON public.gstr8_batches (firm_id, client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_gstr8_batches_status
    ON public.gstr8_batches (status);

-- 7. Table: public.gstr8_records
CREATE TABLE IF NOT EXISTS public.gstr8_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr8_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    period                  VARCHAR(7) NOT NULL,
    supply_type             VARCHAR(10) NOT NULL DEFAULT 'B2B'
                            CHECK (supply_type IN ('B2B', 'B2C')),
    record_type             VARCHAR(20) NOT NULL DEFAULT 'ORIGINAL'
                            CHECK (record_type IN ('ORIGINAL', 'AMENDMENT')),
    pos                     VARCHAR(2) NOT NULL,
    supplier_gstin          VARCHAR(15),
    gross_supplies          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    returned_supplies       NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_supplies            NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    tcs_rate                NUMERIC(5, 3) NOT NULL DEFAULT 0.500,
    tcs_igst                NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    tcs_cgst                NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    tcs_sgst                NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    original_period         VARCHAR(7),
    original_supplier_gstin VARCHAR(15),
    original_pos            VARCHAR(2),
    tax_deposited           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                            CHECK (status IN ('ACTIVE', 'DELETED')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr8_records_batch
    ON public.gstr8_records (batch_id, status);

CREATE INDEX IF NOT EXISTS idx_gstr8_records_supplier
    ON public.gstr8_records (supplier_gstin);

-- 8. Table: public.gstr8_audit_trail
CREATE TABLE IF NOT EXISTS public.gstr8_audit_trail (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr8_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    action                  VARCHAR(50) NOT NULL,
    actor_id                UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name              VARCHAR(255) NOT NULL DEFAULT '',
    actor_role              VARCHAR(50) NOT NULL DEFAULT '',
    from_status             VARCHAR(30),
    to_status               VARCHAR(30),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr8_audit_batch
    ON public.gstr8_audit_trail (batch_id, created_at DESC);

-- 9. Idempotent Restoration from Rollback Archives (if upgrading after rollback)
DO $$
BEGIN
    -- Restore GSTR-7 Batches
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr7_batches_rollback'
    ) THEN
        INSERT INTO public.gstr7_batches (
            id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_records, total_amendments, total_amount_paid, total_tds_igst,
            total_tds_cgst, total_tds_sgst, total_tds_deposited, gstn_reference_id,
            gstn_status, arn, filing_run_id, created_by, created_at, updated_at
        )
        SELECT
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_records, total_amendments, total_amount_paid, total_tds_igst,
            total_tds_cgst, total_tds_sgst, total_tds_deposited, gstn_reference_id,
            gstn_status, arn, filing_run_id, created_by, created_at, updated_at
        FROM public._archive_gstr7_batches_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-7 Records
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr7_records_rollback'
    ) THEN
        INSERT INTO public.gstr7_records (
            id, batch_id, firm_id, client_gstin_id, period, record_type,
            deductee_gstin, contract_number, contract_value, payment_reference,
            payment_date, amount_paid, supplier_state, pos, tds_rate,
            tds_igst, tds_cgst, tds_sgst, original_period, original_deductee_gstin,
            tax_deposited, is_eligible_for_tds, ineligibility_reason, status,
            created_at, updated_at
        )
        SELECT
            record_id, batch_id, firm_id, client_gstin_id, period, record_type,
            deductee_gstin, contract_number, contract_value, payment_reference,
            payment_date, amount_paid, supplier_state, pos, tds_rate,
            tds_igst, tds_cgst, tds_sgst, original_period, original_deductee_gstin,
            tax_deposited, is_eligible_for_tds, ineligibility_reason, status,
            created_at, updated_at
        FROM public._archive_gstr7_records_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-8 Batches
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr8_batches_rollback'
    ) THEN
        INSERT INTO public.gstr8_batches (
            id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_b2b_records, total_b2c_records, total_amendments, gross_supplies_value,
            returned_supplies_value, net_taxable_value, total_tcs_igst, total_tcs_cgst,
            total_tcs_sgst, total_tcs_deposited, gstn_reference_id, gstn_status, arn,
            filing_run_id, created_by, created_at, updated_at
        )
        SELECT
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_b2b_records, total_b2c_records, total_amendments, gross_supplies_value,
            returned_supplies_value, net_taxable_value, total_tcs_igst, total_tcs_cgst,
            total_tcs_sgst, total_tcs_deposited, gstn_reference_id, gstn_status, arn,
            filing_run_id, created_by, created_at, updated_at
        FROM public._archive_gstr8_batches_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-8 Records
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr8_records_rollback'
    ) THEN
        INSERT INTO public.gstr8_records (
            id, batch_id, firm_id, client_gstin_id, period, supply_type,
            record_type, pos, supplier_gstin, gross_supplies, returned_supplies,
            net_supplies, tcs_rate, tcs_igst, tcs_cgst, tcs_sgst, original_period,
            original_supplier_gstin, original_pos, tax_deposited, status,
            created_at, updated_at
        )
        SELECT
            record_id, batch_id, firm_id, client_gstin_id, period, supply_type,
            record_type, pos, supplier_gstin, gross_supplies, returned_supplies,
            net_supplies, tcs_rate, tcs_igst, tcs_cgst, tcs_sgst, original_period,
            original_supplier_gstin, original_pos, tax_deposited, status,
            created_at, updated_at
        FROM public._archive_gstr8_records_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;
END $$;
