-- ============================================================================
-- Migration: 20261012180000_create_gstr6_gstr5_gstr5a_compliance.down.sql
-- Description: Phase 4.3 - Safe Non-Destructive Rollback of GSTR-6, GSTR-5 & GSTR-5A
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration. Schema downgrades on live databases risk breaking
-- statutory audit records.
--
-- This script implements a NON-DESTRUCTIVE archival rollback pattern:
-- 1. Archives audit trail history into `_archive_gstr6_audit_trail_rollback`, `_archive_gstr5_...`, `_archive_gstr5a_...`.
-- 2. Archives active records into `_archive_gstr6_inward_records_rollback`, etc.
-- 3. Archives active batches into `_archive_gstr6_batches_rollback`, etc.
-- 4. Safely drops active tables only after records are durably archived.
-- ============================================================================

-- 1. Archive GSTR-6 (ISD)
CREATE TABLE IF NOT EXISTS public._archive_gstr6_audit_trail_rollback (
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
        WHERE table_schema = 'public' AND table_name = 'gstr6_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr6_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr6_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr6_inward_records_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    record_type             VARCHAR(20) NOT NULL,
    supplier_gstin          VARCHAR(15) NOT NULL,
    invoice_number          VARCHAR(100) NOT NULL,
    invoice_date            DATE NOT NULL,
    taxable_value           NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    igst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    sgst                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    cess                    NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    itc_eligible            VARCHAR(20) NOT NULL,
    original_invoice_number VARCHAR(100),
    original_period         VARCHAR(7),
    status                  VARCHAR(20) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr6_inward_records'
    ) THEN
        INSERT INTO public._archive_gstr6_inward_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, record_type, supplier_gstin,
            invoice_number, invoice_date, taxable_value, igst, cgst, sgst, cess,
            itc_eligible, original_invoice_number, original_period, status, created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, record_type, supplier_gstin,
               invoice_number, invoice_date, taxable_value, igst, cgst, sgst, cess,
               itc_eligible, original_invoice_number, original_period, status, created_at, updated_at
        FROM public.gstr6_inward_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr6_distribution_records_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    record_type             VARCHAR(20) NOT NULL,
    recipient_gstin          VARCHAR(15) NOT NULL,
    recipient_state         VARCHAR(2) NOT NULL,
    is_turnover_based       BOOLEAN NOT NULL,
    turnover_ratio          NUMERIC(10, 6) NOT NULL,
    distributed_igst        NUMERIC(15, 2) NOT NULL,
    distributed_cgst        NUMERIC(15, 2) NOT NULL,
    distributed_sgst        NUMERIC(15, 2) NOT NULL,
    distributed_cess        NUMERIC(15, 2) NOT NULL,
    itc_category            VARCHAR(20) NOT NULL,
    document_number         VARCHAR(100),
    document_date           DATE,
    original_document_number VARCHAR(100),
    original_period         VARCHAR(7),
    status                  VARCHAR(20) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr6_distribution_records'
    ) THEN
        INSERT INTO public._archive_gstr6_distribution_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
            recipient_state, is_turnover_based, turnover_ratio, distributed_igst,
            distributed_cgst, distributed_sgst, distributed_cess, itc_category,
            document_number, document_date, original_document_number, original_period,
            status, created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
               recipient_state, is_turnover_based, turnover_ratio, distributed_igst,
               distributed_cgst, distributed_sgst, distributed_cess, itc_category,
               document_number, document_date, original_document_number, original_period,
               status, created_at, updated_at
        FROM public.gstr6_distribution_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr6_batches_rollback (
    archive_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                    UUID NOT NULL,
    firm_id                     UUID NOT NULL,
    client_gstin_id             UUID NOT NULL,
    gstin                       VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL,
    status                      VARCHAR(30) NOT NULL,
    figures_digest              VARCHAR(64) NOT NULL,
    total_inward_records        INT NOT NULL,
    total_distribution_records  INT NOT NULL,
    total_pool_igst             NUMERIC(15, 2) NOT NULL,
    total_pool_cgst             NUMERIC(15, 2) NOT NULL,
    total_pool_sgst             NUMERIC(15, 2) NOT NULL,
    total_pool_cess             NUMERIC(15, 2) NOT NULL,
    total_distributed_igst      NUMERIC(15, 2) NOT NULL,
    total_distributed_cgst      NUMERIC(15, 2) NOT NULL,
    total_distributed_sgst      NUMERIC(15, 2) NOT NULL,
    total_distributed_cess      NUMERIC(15, 2) NOT NULL,
    gstn_reference_id           VARCHAR(100),
    gstn_status                 VARCHAR(20),
    arn                         VARCHAR(50),
    filing_run_id               UUID,
    created_by                  UUID,
    created_at                  TIMESTAMPTZ NOT NULL,
    updated_at                  TIMESTAMPTZ NOT NULL,
    archived_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr6_batches'
    ) THEN
        INSERT INTO public._archive_gstr6_batches_rollback (
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_inward_records, total_distribution_records, total_pool_igst, total_pool_cgst,
            total_pool_sgst, total_pool_cess, total_distributed_igst, total_distributed_cgst,
            total_distributed_sgst, total_distributed_cess, gstn_reference_id, gstn_status, arn,
            filing_run_id, created_by, created_at, updated_at
        )
        SELECT id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
               total_inward_records, total_distribution_records, total_pool_igst, total_pool_cgst,
               total_pool_sgst, total_pool_cess, total_distributed_igst, total_distributed_cgst,
               total_distributed_sgst, total_distributed_cess, gstn_reference_id, gstn_status, arn,
               filing_run_id, created_by, created_at, updated_at
        FROM public.gstr6_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;


-- 2. Archive GSTR-5 (NRTP)
CREATE TABLE IF NOT EXISTS public._archive_gstr5_audit_trail_rollback (
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
        WHERE table_schema = 'public' AND table_name = 'gstr5_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr5_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr5_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr5_import_records_rollback (
    archive_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id       UUID NOT NULL,
    batch_id        UUID NOT NULL,
    firm_id         UUID NOT NULL,
    client_gstin_id UUID NOT NULL,
    boe_number      VARCHAR(100) NOT NULL,
    boe_date        DATE NOT NULL,
    port_code       VARCHAR(10) NOT NULL,
    taxable_value   NUMERIC(15, 2) NOT NULL,
    igst_paid       NUMERIC(15, 2) NOT NULL,
    cess_paid       NUMERIC(15, 2) NOT NULL,
    status          VARCHAR(20) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr5_import_records'
    ) THEN
        INSERT INTO public._archive_gstr5_import_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, boe_number, boe_date, port_code,
            taxable_value, igst_paid, cess_paid, status, created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, boe_number, boe_date, port_code,
               taxable_value, igst_paid, cess_paid, status, created_at, updated_at
        FROM public.gstr5_import_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr5_outward_records_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    record_type             VARCHAR(20) NOT NULL,
    recipient_gstin          VARCHAR(15),
    pos                     VARCHAR(2) NOT NULL,
    invoice_number          VARCHAR(100) NOT NULL,
    invoice_date            DATE NOT NULL,
    taxable_value           NUMERIC(15, 2) NOT NULL,
    rate_pct                NUMERIC(5, 2) NOT NULL,
    igst                    NUMERIC(15, 2) NOT NULL,
    cgst                    NUMERIC(15, 2) NOT NULL,
    sgst                    NUMERIC(15, 2) NOT NULL,
    cess                    NUMERIC(15, 2) NOT NULL,
    original_period         VARCHAR(7),
    original_invoice_number VARCHAR(100),
    status                  VARCHAR(20) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr5_outward_records'
    ) THEN
        INSERT INTO public._archive_gstr5_outward_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
            pos, invoice_number, invoice_date, taxable_value, rate_pct, igst, cgst,
            sgst, cess, original_period, original_invoice_number, status, created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, record_type, recipient_gstin,
               pos, invoice_number, invoice_date, taxable_value, rate_pct, igst, cgst,
               sgst, cess, original_period, original_invoice_number, status, created_at, updated_at
        FROM public.gstr5_outward_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr5_batches_rollback (
    archive_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                    UUID NOT NULL,
    firm_id                     UUID NOT NULL,
    client_gstin_id             UUID NOT NULL,
    gstin                       VARCHAR(15) NOT NULL,
    period                      VARCHAR(7) NOT NULL,
    registration_start_date     DATE,
    registration_expiry_date    DATE,
    advance_tax_deposited       NUMERIC(15, 2) NOT NULL,
    status                      VARCHAR(30) NOT NULL,
    figures_digest              VARCHAR(64) NOT NULL,
    total_import_records        INT NOT NULL,
    total_outward_records       INT NOT NULL,
    total_amendments            INT NOT NULL,
    total_taxable_value         NUMERIC(15, 2) NOT NULL,
    total_igst                  NUMERIC(15, 2) NOT NULL,
    total_cgst                  NUMERIC(15, 2) NOT NULL,
    total_sgst                  NUMERIC(15, 2) NOT NULL,
    total_cess                  NUMERIC(15, 2) NOT NULL,
    total_import_igst           NUMERIC(15, 2) NOT NULL,
    total_import_cess           NUMERIC(15, 2) NOT NULL,
    net_tax_payable             NUMERIC(15, 2) NOT NULL,
    gstn_reference_id           VARCHAR(100),
    gstn_status                 VARCHAR(20),
    arn                         VARCHAR(50),
    filing_run_id               UUID,
    created_by                  UUID,
    created_at                  TIMESTAMPTZ NOT NULL,
    updated_at                  TIMESTAMPTZ NOT NULL,
    archived_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr5_batches'
    ) THEN
        INSERT INTO public._archive_gstr5_batches_rollback (
            batch_id, firm_id, client_gstin_id, gstin, period, registration_start_date,
            registration_expiry_date, advance_tax_deposited, status, figures_digest,
            total_import_records, total_outward_records, total_amendments, total_taxable_value,
            total_igst, total_cgst, total_sgst, total_cess, total_import_igst, total_import_cess,
            net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
            created_by, created_at, updated_at
        )
        SELECT id, firm_id, client_gstin_id, gstin, period, registration_start_date,
               registration_expiry_date, advance_tax_deposited, status, figures_digest,
               total_import_records, total_outward_records, total_amendments, total_taxable_value,
               total_igst, total_cgst, total_sgst, total_cess, total_import_igst, total_import_cess,
               net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
               created_by, created_at, updated_at
        FROM public.gstr5_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;


-- 3. Archive GSTR-5A (OIDAR)
CREATE TABLE IF NOT EXISTS public._archive_gstr5a_audit_trail_rollback (
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
        WHERE table_schema = 'public' AND table_name = 'gstr5a_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr5a_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr5a_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr5a_records_rollback (
    archive_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id       UUID NOT NULL,
    batch_id        UUID NOT NULL,
    firm_id         UUID NOT NULL,
    client_gstin_id UUID NOT NULL,
    record_type     VARCHAR(20) NOT NULL,
    pos             VARCHAR(2) NOT NULL,
    taxable_value   NUMERIC(15, 2) NOT NULL,
    rate_pct        NUMERIC(5, 2) NOT NULL,
    igst            NUMERIC(15, 2) NOT NULL,
    cess            NUMERIC(15, 2) NOT NULL,
    original_period VARCHAR(7),
    original_pos    VARCHAR(2),
    status          VARCHAR(20) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr5a_records'
    ) THEN
        INSERT INTO public._archive_gstr5a_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, record_type, pos,
            taxable_value, rate_pct, igst, cess, original_period, original_pos,
            status, created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, record_type, pos,
               taxable_value, rate_pct, igst, cess, original_period, original_pos,
               status, created_at, updated_at
        FROM public.gstr5a_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public._archive_gstr5a_batches_rollback (
    archive_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id            UUID NOT NULL,
    firm_id             UUID NOT NULL,
    client_gstin_id     UUID NOT NULL,
    gstin               VARCHAR(15) NOT NULL,
    period              VARCHAR(7) NOT NULL,
    status              VARCHAR(30) NOT NULL,
    figures_digest      VARCHAR(64) NOT NULL,
    total_records       INT NOT NULL,
    total_amendments    INT NOT NULL,
    total_taxable_value NUMERIC(15, 2) NOT NULL,
    total_igst          NUMERIC(15, 2) NOT NULL,
    total_cess          NUMERIC(15, 2) NOT NULL,
    net_tax_payable     NUMERIC(15, 2) NOT NULL,
    gstn_reference_id   VARCHAR(100),
    gstn_status         VARCHAR(20),
    arn                 VARCHAR(50),
    filing_run_id       UUID,
    created_by          UUID,
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr5a_batches'
    ) THEN
        INSERT INTO public._archive_gstr5a_batches_rollback (
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_records, total_amendments, total_taxable_value, total_igst, total_cess,
            net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
            created_by, created_at, updated_at
        )
        SELECT id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
               total_records, total_amendments, total_taxable_value, total_igst, total_cess,
               net_tax_payable, gstn_reference_id, gstn_status, arn, filing_run_id,
               created_by, created_at, updated_at
        FROM public.gstr5a_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;


-- 4. Safely drop active tables in reverse dependency order
DROP TABLE IF EXISTS public.gstr6_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr6_distribution_records CASCADE;
DROP TABLE IF EXISTS public.gstr6_inward_records CASCADE;
DROP TABLE IF EXISTS public.gstr6_batches CASCADE;

DROP TABLE IF EXISTS public.gstr5_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr5_outward_records CASCADE;
DROP TABLE IF EXISTS public.gstr5_import_records CASCADE;
DROP TABLE IF EXISTS public.gstr5_batches CASCADE;

DROP TABLE IF EXISTS public.gstr5a_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr5a_records CASCADE;
DROP TABLE IF EXISTS public.gstr5a_batches CASCADE;

-- 5. Restore check constraints to previous phase supported set
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
