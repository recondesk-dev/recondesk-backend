-- Migration: 20261014100000_add_gstr8_transaction_date_fields.sql
-- Add transaction_date, rate_basis, needs_review, review_reason to gstr8_records

ALTER TABLE public.gstr8_records
    ADD COLUMN IF NOT EXISTS transaction_date DATE,
    ADD COLUMN IF NOT EXISTS rate_basis VARCHAR(30),
    ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS review_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_gstr8_records_tx_date
    ON public.gstr8_records (transaction_date);

CREATE INDEX IF NOT EXISTS idx_gstr8_records_supp_tx_date
    ON public.gstr8_records (batch_id, supplier_gstin, transaction_date)
    WHERE status = 'ACTIVE';

UPDATE public.gstr8_records
SET needs_review = TRUE,
    review_reason = 'July 2024 transition record requires transaction_date or verifiable rate basis (1.0% pre-10-Jul vs 0.5% post-10-Jul).'
WHERE period = '2024-07'
  AND transaction_date IS NULL
  AND rate_basis IS NULL;
