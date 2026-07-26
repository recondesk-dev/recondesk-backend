-- First-login product tour + demo client flag.
-- is_first_login gates the driver.js tour (separate from form onboarding_completed).
-- is_demo marks the seeded sample client so it can be filtered from capacity/exports.

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS is_first_login boolean NOT NULL DEFAULT true;

-- Users who already finished form onboarding should not see the product tour.
UPDATE public.user_profiles
SET is_first_login = false
WHERE onboarding_completed IS TRUE
  AND is_first_login IS TRUE;

ALTER TABLE public.client_gstins
  ADD COLUMN IF NOT EXISTS is_demo boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_client_gstins_firm_owner_is_demo
  ON public.client_gstins (firm_owner_id, is_demo)
  WHERE is_active = true;

COMMENT ON COLUMN public.user_profiles.is_first_login IS
  'True until the user completes or skips the dashboard product tour (driver.js).';

COMMENT ON COLUMN public.client_gstins.is_demo IS
  'True for auto-seeded sample clients used by the first-login tour. Exclude from GSTIN capacity and real exports.';
