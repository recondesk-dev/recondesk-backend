-- ============================================================================
-- Migration: 20261012180000_create_gstr6_gstr5_gstr5a_compliance.up.sql
-- Description: Phase 4.3 - GSTR-6 (ISD), GSTR-5 (NRTP), and GSTR-5A (OIDAR) Compliance Intelligence
--              Tables for ISD, NRTP, and OIDAR batches, records, distribution,
--              reconciliation, and immutable audit trails.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Extend return_filing_approvals check constraint to include GSTR-6, GSTR-5, and GSTR-5A
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

-- 2. Extend client_filing_authorizations check constraint to include GSTR-6, GSTR-5, and GSTR-5A
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

-- 3. GSTR-6 (ISD) TABLES
-- 3a. Table: public.gstr6_batches
CREATE TABLE IF NOT EXISTS public.gstr6_batches (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                     UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id             UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                       VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                                CHECK (status IN (
                                    'DRAFT',
                                    'PREPARED',
                                    'UNDER_REVIEW',
                                    'APPROVED',
                                    'REJECTED',
                                    'SAVED',
                                    'FILED'
                                )),
    figures_digest              VARCHAR(64) NOT NULL DEFAULT '',
    total_inward_records        INT NOT NULL DEFAULT 0,
    total_distribution_records  INT NOT NULL DEFAULT 0,
    total_pool_igst             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_pool_cgst             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_pool_sgst             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_pool_cess             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_distributed_igst      NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_distributed_cgst      NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_distributed_sgst      NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_distributed_cess      NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id           VARCHAR(100),
    gstn_status                 VARCHAR(20),
    arn                         VARCHAR(50),
    filing_run_id               UUID REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    created_by                  UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr6_batch UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr6_batches_lookup
    ON public.gstr6_batches (firm_id, client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_gstr6_batches_status
    ON public.gstr6_batches (status);

-- 3b. Table: public.gstr6_inward_records
CREATE TABLE IF NOT EXISTS public.gstr6_inward_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr6_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    record_type             VARCHAR(20) NOT NULL DEFAULT 'ORIGINAL'
                            CHECK (record_type IN ('ORIGINAL', 'AMENDMENT')),
    supplier_gstin          VARCHAR(15) NOT NULL,
    invoice_number          VARCHAR(100) NOT NULL,
    invoice_date            DATE NOT NULL,
    taxable_value           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    igst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    sgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cess                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    itc_eligible            VARCHAR(20) NOT NULL DEFAULT 'ELIGIBLE'
                            CHECK (itc_eligible IN ('ELIGIBLE', 'INELIGIBLE')),
    original_invoice_number VARCHAR(100),
    original_period         VARCHAR(7),
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr6_inward_batch
    ON public.gstr6_inward_records (batch_id);

-- 3c. Table: public.gstr6_distribution_records
CREATE TABLE IF NOT EXISTS public.gstr6_distribution_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr6_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    record_type             VARCHAR(20) NOT NULL DEFAULT 'ORIGINAL'
                            CHECK (record_type IN ('ORIGINAL', 'AMENDMENT')),
    recipient_gstin          VARCHAR(15) NOT NULL,
    recipient_state         VARCHAR(2) NOT NULL,
    is_turnover_based       BOOLEAN NOT NULL DEFAULT TRUE,
    turnover_ratio          NUMERIC(10, 6) NOT NULL DEFAULT 1.000000,
    distributed_igst        NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    distributed_cgst        NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    distributed_sgst        NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    distributed_cess        NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    itc_category            VARCHAR(20) NOT NULL DEFAULT 'ELIGIBLE'
                            CHECK (itc_category IN ('ELIGIBLE', 'INELIGIBLE')),
    document_number         VARCHAR(100),
    document_date           DATE,
    original_document_number VARCHAR(100),
    original_period         VARCHAR(7),
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr6_dist_batch
    ON public.gstr6_distribution_records (batch_id);

-- 3d. Table: public.gstr6_audit_trail
CREATE TABLE IF NOT EXISTS public.gstr6_audit_trail (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES public.gstr6_batches (id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    action          VARCHAR(50) NOT NULL,
    actor_id        UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name      VARCHAR(255) NOT NULL DEFAULT 'System',
    actor_role      VARCHAR(50) NOT NULL DEFAULT 'SYSTEM',
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr6_audit_batch
    ON public.gstr6_audit_trail (batch_id, created_at);


-- 4. GSTR-5 (NRTP) TABLES
-- 4a. Table: public.gstr5_batches
CREATE TABLE IF NOT EXISTS public.gstr5_batches (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                     UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id             UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                       VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    registration_start_date     DATE,
    registration_expiry_date    DATE,
    advance_tax_deposited       NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                                CHECK (status IN (
                                    'DRAFT',
                                    'PREPARED',
                                    'UNDER_REVIEW',
                                    'APPROVED',
                                    'REJECTED',
                                    'SAVED',
                                    'FILED'
                                )),
    figures_digest              VARCHAR(64) NOT NULL DEFAULT '',
    total_import_records        INT NOT NULL DEFAULT 0,
    total_outward_records       INT NOT NULL DEFAULT 0,
    total_amendments            INT NOT NULL DEFAULT 0,
    total_taxable_value         NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_igst                  NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cgst                  NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_sgst                  NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cess                  NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_import_igst           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_import_cess           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_tax_payable             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id           VARCHAR(100),
    gstn_status                 VARCHAR(20),
    arn                         VARCHAR(50),
    filing_run_id               UUID REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    created_by                  UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr5_batch UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr5_batches_lookup
    ON public.gstr5_batches (firm_id, client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_gstr5_batches_status
    ON public.gstr5_batches (status);

-- 4b. Table: public.gstr5_import_records
CREATE TABLE IF NOT EXISTS public.gstr5_import_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES public.gstr5_batches (id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    boe_number      VARCHAR(100) NOT NULL,
    boe_date        DATE NOT NULL,
    port_code       VARCHAR(10) NOT NULL,
    taxable_value   NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    igst_paid       NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cess_paid       NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr5_import_batch
    ON public.gstr5_import_records (batch_id);

-- 4c. Table: public.gstr5_outward_records
CREATE TABLE IF NOT EXISTS public.gstr5_outward_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr5_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    record_type             VARCHAR(20) NOT NULL DEFAULT 'ORIGINAL'
                            CHECK (record_type IN ('ORIGINAL', 'AMENDMENT')),
    recipient_gstin          VARCHAR(15),
    pos                     VARCHAR(2) NOT NULL,
    invoice_number          VARCHAR(100) NOT NULL,
    invoice_date            DATE NOT NULL,
    taxable_value           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    rate_pct                NUMERIC(5, 2) NOT NULL DEFAULT 18.00,
    igst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    sgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cess                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    original_period         VARCHAR(7),
    original_invoice_number VARCHAR(100),
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr5_outward_batch
    ON public.gstr5_outward_records (batch_id);

-- 4d. Table: public.gstr5_audit_trail
CREATE TABLE IF NOT EXISTS public.gstr5_audit_trail (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES public.gstr5_batches (id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    action          VARCHAR(50) NOT NULL,
    actor_id        UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name      VARCHAR(255) NOT NULL DEFAULT 'System',
    actor_role      VARCHAR(50) NOT NULL DEFAULT 'SYSTEM',
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr5_audit_batch
    ON public.gstr5_audit_trail (batch_id, created_at);


-- 5. GSTR-5A (OIDAR) TABLES
-- 5a. Table: public.gstr5a_batches
CREATE TABLE IF NOT EXISTS public.gstr5a_batches (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                     UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id             UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                       VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status                      VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                                CHECK (status IN (
                                    'DRAFT',
                                    'PREPARED',
                                    'UNDER_REVIEW',
                                    'APPROVED',
                                    'REJECTED',
                                    'SAVED',
                                    'FILED'
                                )),
    figures_digest              VARCHAR(64) NOT NULL DEFAULT '',
    total_records               INT NOT NULL DEFAULT 0,
    total_amendments            INT NOT NULL DEFAULT 0,
    total_taxable_value         NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_igst                  NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    total_cess                  NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    net_tax_payable             NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id           VARCHAR(100),
    gstn_status                 VARCHAR(20),
    arn                         VARCHAR(50),
    filing_run_id               UUID REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    created_by                  UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr5a_batch UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr5a_batches_lookup
    ON public.gstr5a_batches (firm_id, client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_gstr5a_batches_status
    ON public.gstr5a_batches (status);

-- 5b. Table: public.gstr5a_records
CREATE TABLE IF NOT EXISTS public.gstr5a_records (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr5a_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    record_type             VARCHAR(20) NOT NULL DEFAULT 'ORIGINAL'
                            CHECK (record_type IN ('ORIGINAL', 'AMENDMENT')),
    pos                     VARCHAR(2) NOT NULL,
    taxable_value           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    rate_pct                NUMERIC(5, 2) NOT NULL DEFAULT 18.00,
    igst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cess                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    original_period         VARCHAR(7),
    original_pos            VARCHAR(2),
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr5a_records_batch
    ON public.gstr5a_records (batch_id);

-- 5c. Table: public.gstr5a_audit_trail
CREATE TABLE IF NOT EXISTS public.gstr5a_audit_trail (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES public.gstr5a_batches (id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    action          VARCHAR(50) NOT NULL,
    actor_id        UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name      VARCHAR(255) NOT NULL DEFAULT 'System',
    actor_role      VARCHAR(50) NOT NULL DEFAULT 'SYSTEM',
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr5a_audit_batch
    ON public.gstr5a_audit_trail (batch_id, created_at);


-- 6. IDEMPOTENT RESTORATION OF HISTORICAL RECORDS POST-ROLLBACK
DO $$
BEGIN
    -- Restore GSTR-6 Batches
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr6_batches_rollback'
    ) THEN
        INSERT INTO public.gstr6_batches (
            id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_inward_records, total_distribution_records, total_pool_igst, total_pool_cgst,
            total_pool_sgst, total_pool_cess, total_distributed_igst, total_distributed_cgst,
            total_distributed_sgst, total_distributed_cess, gstn_reference_id, gstn_status, arn,
            filing_run_id, created_by, created_at, updated_at
        )
        SELECT
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_inward_records, total_distribution_records, total_pool_igst, total_pool_cgst,
            total_pool_sgst, total_pool_cess, total_distributed_igst, total_distributed_cgst,
            total_distributed_sgst, total_distributed_cess, gstn_reference_id, gstn_status, arn,
            filing_run_id, created_by, created_at, updated_at
        FROM public._archive_gstr6_batches_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-6 Inward Records
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr6_inward_records_rollback'
    ) THEN
        INSERT INTO public.gstr6_inward_records (
            id, batch_id, firm_id, client_gstin_id, record_type, supplier_gstin,
            invoice_number, invoice_date, taxable_value, igst, cgst, sgst, cess,
            itc_eligible, original_invoice_number, original_period, status, created_at, updated_at
        )
        SELECT
            record_id, batch_id, firm_id, client_gstin_id, record_type, supplier_gstin,
            invoice_number, invoice_date, taxable_value, igst, cgst, sgst, cess,
            itc_eligible, original_invoice_number, original_period, status, created_at, updated_at
        FROM public._archive_gstr6_inward_records_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-6 Distribution Records
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr6_distribution_records_rollback'
    ) THEN
        INSERT INTO public.gstr6_distribution_records (
            id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
            recipient_state, is_turnover_based, turnover_ratio, distributed_igst,
            distributed_cgst, distributed_sgst, distributed_cess, itc_category,
            document_number, document_date, original_document_number, original_period,
            status, created_at, updated_at
        )
        SELECT
            record_id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
            recipient_state, is_turnover_based, turnover_ratio, distributed_igst,
            distributed_cgst, distributed_sgst, distributed_cess, itc_category,
            document_number, document_date, original_document_number, original_period,
            status, created_at, updated_at
        FROM public._archive_gstr6_distribution_records_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-5 Batches
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr5_batches_rollback'
    ) THEN
        INSERT INTO public.gstr5_batches (
            id, firm_id, client_gstin_id, gstin, period, registration_start_date,
            registration_expiry_date, advance_tax_deposited, status, figures_digest,
            total_import_records, total_outward_records, total_amendments, total_taxable_value,
            total_igst, total_cgst, total_sgst, total_cess, total_import_igst, total_import_cess,
            net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
            created_by, created_at, updated_at
        )
        SELECT
            batch_id, firm_id, client_gstin_id, gstin, period, registration_start_date,
            registration_expiry_date, advance_tax_deposited, status, figures_digest,
            total_import_records, total_outward_records, total_amendments, total_taxable_value,
            total_igst, total_cgst, total_sgst, total_cess, total_import_igst, total_import_cess,
            net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
            created_by, created_at, updated_at
        FROM public._archive_gstr5_batches_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-5 Import Records
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr5_import_records_rollback'
    ) THEN
        INSERT INTO public.gstr5_import_records (
            id, batch_id, firm_id, client_gstin_id, boe_number, boe_date, port_code,
            taxable_value, igst_paid, cess_paid, status, created_at, updated_at
        )
        SELECT
            record_id, batch_id, firm_id, client_gstin_id, boe_number, boe_date, port_code,
            taxable_value, igst_paid, cess_paid, status, created_at, updated_at
        FROM public._archive_gstr5_import_records_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-5 Outward Records
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr5_outward_records_rollback'
    ) THEN
        INSERT INTO public.gstr5_outward_records (
            id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
            pos, invoice_number, invoice_date, taxable_value, rate_pct, igst, cgst,
            sgst, cess, original_period, original_invoice_number, status, created_at, updated_at
        )
        SELECT
            record_id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
            pos, invoice_number, invoice_date, taxable_value, rate_pct, igst, cgst,
            sgst, cess, original_period, original_invoice_number, status, created_at, updated_at
        FROM public._archive_gstr5_outward_records_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-5A Batches
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr5a_batches_rollback'
    ) THEN
        INSERT INTO public.gstr5a_batches (
            id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_records, total_amendments, total_taxable_value, total_igst, total_cess,
            net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
            created_by, created_at, updated_at
        )
        SELECT
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_records, total_amendments, total_taxable_value, total_igst, total_cess,
            net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
            created_by, created_at, updated_at
        FROM public._archive_gstr5a_batches_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- Restore GSTR-5A Records
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr5a_records_rollback'
    ) THEN
        INSERT INTO public.gstr5a_records (
            id, batch_id, firm_id, client_gstin_id, record_type, pos, taxable_value,
            rate_pct, igst, cess, original_period, original_pos, status, created_at, updated_at
        )
        SELECT
            record_id, batch_id, firm_id, client_gstin_id, record_type, pos, taxable_value,
            rate_pct, igst, cess, original_period, original_pos, status, created_at, updated_at
        FROM public._archive_gstr5a_records_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;
END $$;
