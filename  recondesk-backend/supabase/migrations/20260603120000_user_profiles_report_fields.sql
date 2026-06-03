-- Profile fields used on exported reconciliation reports.
ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS icai_membership_number text,
  ADD COLUMN IF NOT EXISTS firm_gstin text;
