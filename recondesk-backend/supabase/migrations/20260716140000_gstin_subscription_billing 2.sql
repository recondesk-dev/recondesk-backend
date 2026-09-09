-- GSTIN-based subscription entitlement on user_profiles.
-- Free/unpaid firms default to 2 GSTINs; paid plans raise the limit.

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS gstin_limit integer NOT NULL DEFAULT 2;

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS subscription_ends_at timestamptz;

COMMENT ON COLUMN public.user_profiles.gstin_limit IS
  'Max active client GSTINs for the firm; free tier default 2.';
COMMENT ON COLUMN public.user_profiles.subscription_ends_at IS
  'End of paid GSTIN subscription period; null when no active paid plan.';

-- Ensure free/null plan profiles keep the free GSTIN cap unless already set higher.
UPDATE public.user_profiles
SET gstin_limit = 2
WHERE (plan IS NULL OR lower(trim(plan)) IN ('free', ''))
  AND (gstin_limit IS NULL OR gstin_limit < 2);
