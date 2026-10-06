-- Migration: Enforce unique phone number digits in AWS Aurora user_profiles
-- Prevents duplicate accounts with the same mobile number.

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_profiles_phone_digits
  ON public.user_profiles (regexp_replace(phone, '[^0-9]', '', 'g'))
  WHERE phone IS NOT NULL AND phone <> '';
