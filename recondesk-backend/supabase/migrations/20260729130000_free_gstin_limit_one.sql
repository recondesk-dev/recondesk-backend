-- Free tier: 1 lifetime GSTIN (removing a client does not free the slot).
-- Capacity enforcement lives in billing_gate; this keeps the DB default aligned.

ALTER TABLE public.user_profiles
  ALTER COLUMN gstin_limit SET DEFAULT 1;

COMMENT ON COLUMN public.user_profiles.gstin_limit IS
  'Max client GSTINs for the firm; free tier default 1 (lifetime for unpaid).';

-- Cap unpaid / free profiles that still carry the old default of 2.
UPDATE public.user_profiles
SET gstin_limit = 1
WHERE (plan IS NULL OR lower(trim(plan)) IN ('free', ''))
  AND (
    subscription_ends_at IS NULL
    OR subscription_ends_at <= now()
  )
  AND gstin_limit = 2;
