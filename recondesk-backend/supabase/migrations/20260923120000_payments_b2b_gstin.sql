-- ── Extend payments table with B2B GSTIN and tax breakup columns ──────────
ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS customer_gstin text,
  ADD COLUMN IF NOT EXISTS customer_trade_name text,
  ADD COLUMN IF NOT EXISTS customer_city text,
  ADD COLUMN IF NOT EXISTS customer_state_code text,
  ADD COLUMN IF NOT EXISTS tax_type text DEFAULT 'intra',
  ADD COLUMN IF NOT EXISTS cgst_paise integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS sgst_paise integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS igst_paise integer DEFAULT 0;

COMMENT ON COLUMN public.payments.customer_gstin IS 'Recipient GSTIN for B2B tax invoice and GSTR-1 B2B filing.';
COMMENT ON COLUMN public.payments.customer_trade_name IS 'Recipient legal trade name or firm name.';
COMMENT ON COLUMN public.payments.customer_state_code IS '2-digit state code of Place of Supply (POS), e.g. 27 for Maharashtra.';
COMMENT ON COLUMN public.payments.tax_type IS 'intra (CGST+SGST) or inter (IGST).';
