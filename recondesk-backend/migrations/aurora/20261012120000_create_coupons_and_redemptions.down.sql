-- ============================================================================
-- Migration: 20261012120000_create_coupons_and_redemptions.down.sql
-- Description: Revert coupons and redemptions tables
-- Target: AWS Aurora PostgreSQL / Supabase
-- ============================================================================

DROP INDEX IF EXISTS public.idx_payments_refund_id;

ALTER TABLE public.payments
    DROP COLUMN IF EXISTS refund_error,
    DROP COLUMN IF EXISTS refund_status,
    DROP COLUMN IF EXISTS refund_id,
    DROP COLUMN IF EXISTS discount_amount_paise,
    DROP COLUMN IF EXISTS discount_percentage,
    DROP COLUMN IF EXISTS coupon_code,
    DROP COLUMN IF EXISTS coupon_id;

DROP TABLE IF EXISTS public.coupon_redemptions CASCADE;
DROP TABLE IF EXISTS public.coupons CASCADE;
