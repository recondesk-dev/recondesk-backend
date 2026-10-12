-- ============================================================================
-- Migration: 20261012160000_create_gstr7_gstr8_compliance.down.sql
-- Description: Phase 4.2 - Safe Non-Destructive Rollback of GSTR-7 & GSTR-8
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration. Schema downgrades on live databases risk breaking
-- statutory audit records.
--
-- This script implements a NON-DESTRUCTIVE archival rollback pattern:
-- 1. Archives audit trail history into `_archive_gstr7_audit_trail_rollback` & `_archive_gstr8_audit_trail_rollback`.
-- 2. Archives active records into `_archive_gstr7_records_rollback` & `_archive_gstr8_records_rollback`.
-- 3. Archives active batches into `_archive_gstr7_batches_rollback` & `_archive_gstr8_batches_rollback`.
-- 4. Safely drops active tables only after records are durably archived.
-- ============================================================================

-- 1. Archive gstr7_audit_trail
CREATE TABLE IF NOT EXISTS public._archive_gstr7_audit_trail_rollback (
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
        WHERE table_schema = 'public' AND table_name = 'gstr7_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr7_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr7_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 2. Archive gstr7_records
CREATE TABLE IF NOT EXISTS public._archive_gstr7_records_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    period                  VARCHAR(7) NOT NULL,
    record_type             VARCHAR(20) NOT NULL,
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
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr7_records'
    ) THEN
        INSERT INTO public._archive_gstr7_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, period, record_type,
            deductee_gstin, contract_number, contract_value, payment_reference,
            payment_date, amount_paid, supplier_state, pos, tds_rate,
            tds_igst, tds_cgst, tds_sgst, original_period, original_deductee_gstin,
            tax_deposited, is_eligible_for_tds, ineligibility_reason, status,
            created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, period, record_type,
               deductee_gstin, contract_number, contract_value, payment_reference,
               payment_date, amount_paid, supplier_state, pos, tds_rate,
               tds_igst, tds_cgst, tds_sgst, original_period, original_deductee_gstin,
               tax_deposited, is_eligible_for_tds, ineligibility_reason, status,
               created_at, updated_at
        FROM public.gstr7_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 3. Archive gstr7_batches
CREATE TABLE IF NOT EXISTS public._archive_gstr7_batches_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    gstin                   VARCHAR(15) NOT NULL,
    period                  VARCHAR(7) NOT NULL,
    status                  VARCHAR(30) NOT NULL,
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
    filing_run_id           UUID,
    created_by              UUID,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr7_batches'
    ) THEN
        INSERT INTO public._archive_gstr7_batches_rollback (
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_records, total_amendments, total_amount_paid, total_tds_igst,
            total_tds_cgst, total_tds_sgst, total_tds_deposited, gstn_reference_id,
            gstn_status, arn, filing_run_id, created_by, created_at, updated_at
        )
        SELECT id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
               total_records, total_amendments, total_amount_paid, total_tds_igst,
               total_tds_cgst, total_tds_sgst, total_tds_deposited, gstn_reference_id,
               gstn_status, arn, filing_run_id, created_by, created_at, updated_at
        FROM public.gstr7_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 4. Archive gstr8_audit_trail
CREATE TABLE IF NOT EXISTS public._archive_gstr8_audit_trail_rollback (
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
        WHERE table_schema = 'public' AND table_name = 'gstr8_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr8_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr8_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 5. Archive gstr8_records
CREATE TABLE IF NOT EXISTS public._archive_gstr8_records_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    period                  VARCHAR(7) NOT NULL,
    supply_type             VARCHAR(10) NOT NULL,
    record_type             VARCHAR(20) NOT NULL,
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
    status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr8_records'
    ) THEN
        INSERT INTO public._archive_gstr8_records_rollback (
            record_id, batch_id, firm_id, client_gstin_id, period, supply_type,
            record_type, pos, supplier_gstin, gross_supplies, returned_supplies,
            net_supplies, tcs_rate, tcs_igst, tcs_cgst, tcs_sgst, original_period,
            original_supplier_gstin, original_pos, tax_deposited, status,
            created_at, updated_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, period, supply_type,
               record_type, pos, supplier_gstin, gross_supplies, returned_supplies,
               net_supplies, tcs_rate, tcs_igst, tcs_cgst, tcs_sgst, original_period,
               original_supplier_gstin, original_pos, tax_deposited, status,
               created_at, updated_at
        FROM public.gstr8_records
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 6. Archive gstr8_batches
CREATE TABLE IF NOT EXISTS public._archive_gstr8_batches_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    gstin                   VARCHAR(15) NOT NULL,
    period                  VARCHAR(7) NOT NULL,
    status                  VARCHAR(30) NOT NULL,
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
    filing_run_id           UUID,
    created_by              UUID,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr8_batches'
    ) THEN
        INSERT INTO public._archive_gstr8_batches_rollback (
            batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
            total_b2b_records, total_b2c_records, total_amendments, gross_supplies_value,
            returned_supplies_value, net_taxable_value, total_tcs_igst, total_tcs_cgst,
            total_tcs_sgst, total_tcs_deposited, gstn_reference_id, gstn_status, arn,
            filing_run_id, created_by, created_at, updated_at
        )
        SELECT id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
               total_b2b_records, total_b2c_records, total_amendments, gross_supplies_value,
               returned_supplies_value, net_taxable_value, total_tcs_igst, total_tcs_cgst,
               total_tcs_sgst, total_tcs_deposited, gstn_reference_id, gstn_status, arn,
               filing_run_id, created_by, created_at, updated_at
        FROM public.gstr8_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 7. Safely drop active tables only after archiving
DROP TABLE IF EXISTS public.gstr7_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr7_records CASCADE;
DROP TABLE IF EXISTS public.gstr7_batches CASCADE;

DROP TABLE IF EXISTS public.gstr8_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr8_records CASCADE;
DROP TABLE IF EXISTS public.gstr8_batches CASCADE;
