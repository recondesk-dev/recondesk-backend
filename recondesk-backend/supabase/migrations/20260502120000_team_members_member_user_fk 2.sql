-- This migration should be applied in Supabase (Dashboard → SQL Editor, or `supabase db push` / CI).
--
-- Add cascade cleanup: when an auth.users row is deleted, clear member_user_id on team_members
-- (ON DELETE SET NULL).
--
-- ALTER TABLE team_members ADD CONSTRAINT fk_member_user
--   FOREIGN KEY (member_user_id) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.team_members
  DROP CONSTRAINT IF EXISTS team_members_member_user_id_fkey;

ALTER TABLE public.team_members
  DROP CONSTRAINT IF EXISTS fk_member_user;

ALTER TABLE public.team_members
  ADD CONSTRAINT fk_member_user
  FOREIGN KEY (member_user_id) REFERENCES auth.users(id) ON DELETE SET NULL;
