-- Migration for Demo Onboarding & Guided Spotlight Tour

ALTER TABLE public.client_gstins
  ADD COLUMN IF NOT EXISTS is_demo boolean NOT NULL DEFAULT false;

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS demo_tour_seen boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_client_gstins_firm_owner_is_demo
  ON public.client_gstins (firm_owner_id, is_demo);
