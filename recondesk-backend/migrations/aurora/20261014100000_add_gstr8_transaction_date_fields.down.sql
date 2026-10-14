-- ============================================================================
-- Migration: 20261014100000_add_gstr8_transaction_date_fields.down.sql
-- Description: Rollback script for GSTR-8 transaction date fields.
-- CAUTION: DATA-DESTRUCTIVE DOWNGRADE WARNING
--          Dropping transaction_date and rate_basis columns causes IRREVERSIBLE
--          loss of statutory audit trails and TCS rate determination history.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- Step 1: Drop indexes
DROP INDEX IF EXISTS public.idx_gstr8_records_supp_tx_date;
DROP INDEX IF EXISTS public.idx_gstr8_records_tx_date;

-- Step 2: Non-destructive policy
-- Columns are intentionally preserved during non-destructive down-migration
-- to avoid irreversible data loss. For explicit teardown in isolated testing:
ALTER TABLE public.gstr8_records
    DROP COLUMN IF EXISTS transaction_date,
    DROP COLUMN IF EXISTS rate_basis,
    DROP COLUMN IF EXISTS needs_review,
    DROP COLUMN IF EXISTS review_reason;
