-- ============================================================================
-- Migration: 20261014100000_add_gstr8_transaction_date_fields.up.sql
-- Description: Add statutory transaction date and verifiable rate basis fields
--              to Form GSTR-8 compliance records for TCS Section 52.
--              Statutory Reference: Notification No. 15/2024-Central Tax (10 July 2024).
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Add statutory columns to public.gstr8_records
ALTER TABLE public.gstr8_records
    ADD COLUMN IF NOT EXISTS transaction_date DATE,
    ADD COLUMN IF NOT EXISTS rate_basis VARCHAR(30),
    ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS review_reason TEXT;

-- 2. Add performance index on transaction_date for date-boundary range queries
CREATE INDEX IF NOT EXISTS idx_gstr8_records_tx_date
    ON public.gstr8_records (transaction_date);

-- 3. Add composite index for efficient supplier/date duplicate checking
CREATE INDEX IF NOT EXISTS idx_gstr8_records_supp_tx_date
    ON public.gstr8_records (batch_id, supplier_gstin, transaction_date)
    WHERE status = 'ACTIVE';

-- 4. Safe statutory handling for existing July 2024 records:
-- If an existing July 2024 record lacks both transaction_date and rate_basis,
-- flag it with needs_review = TRUE and an authoritative review reason.
-- This ensures unverified July 2024 records are NEVER silently treated as verified.
UPDATE public.gstr8_records
SET needs_review = TRUE,
    review_reason = 'July 2024 transition record requires transaction_date or verifiable rate basis (1.0% pre-10-Jul vs 0.5% post-10-Jul).'
WHERE period = '2024-07'
  AND transaction_date IS NULL
  AND rate_basis IS NULL;
