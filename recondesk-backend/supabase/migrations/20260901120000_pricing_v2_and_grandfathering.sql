-- Migration: 20260901120000_pricing_v2_and_grandfathering.sql
-- Supports 4-tier pricing model (Starter, Growth, Pro, Firm) with monthly/yearly cycles,
-- dynamic GSTIN overage scaling, recurring Razorpay subscriptions, and legacy plan grandfathering.

-- 1. Extend user_profiles
ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS plan_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS billing_cycle text DEFAULT 'yearly',
  ADD COLUMN IF NOT EXISTS overage_gstin_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS razorpay_subscription_id text;

COMMENT ON COLUMN public.user_profiles.plan_version IS 
  '1 = Legacy grandfathered plans (₹999/mo, ₹5999/yr, ₹7999/yr, etc.); 2 = V2 pricing (Starter/Growth/Pro/Firm).';
COMMENT ON COLUMN public.user_profiles.billing_cycle IS 
  'monthly, yearly, or none';

-- Existing users remain on plan_version = 1 (Grandfathered automatically)

-- 2. Extend payments table to record tier metadata and cycle
ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS plan_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS billing_cycle text,
  ADD COLUMN IF NOT EXISTS gstin_limit integer,
  ADD COLUMN IF NOT EXISTS overage_gstins integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS overage_rate_paise integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS razorpay_subscription_id text;

-- 3. Relax or update the legacy check constraint on payments.plan
ALTER TABLE public.payments DROP CONSTRAINT IF EXISTS payments_plan_check;
ALTER TABLE public.payments ADD CONSTRAINT payments_plan_check CHECK (
  plan IS NULL OR plan IN ('starter', 'growth', 'pro', 'firm', 'monthly', 'custom', 'enterprise', 'free')
);
