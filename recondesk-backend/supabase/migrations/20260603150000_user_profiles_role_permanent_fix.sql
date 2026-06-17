-- Permanent role assignment: direct signup → admin, invite → staff.
-- Safe to re-run (CREATE OR REPLACE + idempotent default).

-- ── FIX 2: column default ────────────────────────────────────────────────────
ALTER TABLE public.user_profiles
  ALTER COLUMN role SET DEFAULT 'admin';

-- ── Shared canonical role resolver ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.user_profile_role_for_auth_user(
  p_user_id uuid,
  p_email text,
  p_meta jsonb DEFAULT '{}'::jsonb
)
RETURNS text
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  IF NULLIF(btrim(p_meta->>'invited_by'), '') IS NOT NULL
     OR NULLIF(btrim(p_meta->>'invite_token'), '') IS NOT NULL
     OR NULLIF(btrim(p_meta->>'invited_via'), '') IS NOT NULL
  THEN
    RETURN 'staff';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.team_members tm
    WHERE tm.member_user_id = p_user_id
       OR (
         p_email IS NOT NULL
         AND lower(btrim(tm.invited_email)) = lower(btrim(p_email))
       )
  ) THEN
    RETURN 'staff';
  END IF;

  RETURN 'admin';
END;
$$;

-- ── FIX 1: auth.users signup trigger ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_meta jsonb := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb);
  v_role text;
BEGIN
  v_role := public.user_profile_role_for_auth_user(NEW.id, NEW.email, v_meta);

  INSERT INTO public.user_profiles (id, email, full_name, firm_name, phone, role)
  VALUES (
    NEW.id,
    NEW.email,
    NULLIF(btrim(COALESCE(v_meta->>'full_name', '')), ''),
    NULLIF(btrim(COALESCE(v_meta->>'firm_name', '')), ''),
    NULLIF(btrim(COALESCE(v_meta->>'phone', '')), ''),
    v_role
  )
  ON CONFLICT (id) DO NOTHING;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_user();

-- ── user_profiles safeguard on insert/update ───────────────────────────────────
CREATE OR REPLACE FUNCTION public.user_profiles_resolve_role()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_canonical text;
BEGIN
  v_canonical := public.user_profile_role_for_auth_user(
    NEW.id,
    NEW.email,
    '{}'::jsonb
  );

  IF TG_OP = 'INSERT' THEN
    NEW.role := v_canonical;
  ELSIF NEW.role IS NULL
        OR btrim(NEW.role) = ''
        OR lower(btrim(NEW.role)) NOT IN ('admin', 'staff') THEN
    NEW.role := v_canonical;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS user_profiles_resolve_role ON public.user_profiles;
CREATE TRIGGER user_profiles_resolve_role
  BEFORE INSERT OR UPDATE ON public.user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.user_profiles_resolve_role();

-- ── FIX 5: backfill ALL existing users with wrong roles ──────────────────────
UPDATE public.user_profiles up
SET role = public.user_profile_role_for_auth_user(up.id, up.email, '{}'::jsonb)
WHERE up.role IS DISTINCT FROM public.user_profile_role_for_auth_user(
  up.id,
  up.email,
  '{}'::jsonb
);
