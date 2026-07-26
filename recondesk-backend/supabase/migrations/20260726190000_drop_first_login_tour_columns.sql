-- Remove first-login tour columns if the add migration was applied.

ALTER TABLE public.user_profiles
  DROP COLUMN IF EXISTS is_first_login;

ALTER TABLE public.client_gstins
  DROP COLUMN IF EXISTS is_demo;

DROP INDEX IF EXISTS public.idx_client_gstins_firm_owner_is_demo;
