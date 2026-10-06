-- Revert: Drop unique phone number digits index from user_profiles

DROP INDEX IF EXISTS public.uq_user_profiles_phone_digits;
