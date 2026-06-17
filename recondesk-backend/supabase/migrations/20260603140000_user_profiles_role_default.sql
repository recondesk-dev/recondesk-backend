-- Role assignment at signup: direct signups → admin (workspace owner);
-- invite signups → staff (team member). Safe to re-run.

-- ── Column default ───────────────────────────────────────────────────────────
ALTER TABLE public.user_profiles
  ALTER COLUMN role SET DEFAULT 'admin';

-- ── Resolve role on insert/update when missing ───────────────────────────────
CREATE OR REPLACE FUNCTION public.user_profiles_resolve_role()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.role IS NULL OR btrim(NEW.role) = '' THEN
    IF EXISTS (
      SELECT 1
      FROM public.team_members tm
      WHERE tm.member_user_id = NEW.id
         OR (
           NEW.email IS NOT NULL
           AND lower(btrim(tm.invited_email)) = lower(btrim(NEW.email))
         )
    ) THEN
      NEW.role := 'staff';
    ELSE
      NEW.role := 'admin';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS user_profiles_resolve_role ON public.user_profiles;
CREATE TRIGGER user_profiles_resolve_role
  BEFORE INSERT OR UPDATE ON public.user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.user_profiles_resolve_role();

-- ── Auth signup: create profile with correct role ────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_role text := 'admin';
BEGIN
  IF EXISTS (
    SELECT 1
    FROM public.team_members tm
    WHERE lower(btrim(tm.invited_email)) = lower(btrim(NEW.email))
  ) THEN
    v_role := 'staff';
  END IF;

  INSERT INTO public.user_profiles (
    id,
    email,
    full_name,
    firm_name,
    phone,
    role
  )
  VALUES (
    NEW.id,
    NEW.email,
    NULLIF(btrim(COALESCE(NEW.raw_user_meta_data->>'full_name', '')), ''),
    NULLIF(btrim(COALESCE(NEW.raw_user_meta_data->>'firm_name', '')), ''),
    NULLIF(btrim(COALESCE(NEW.raw_user_meta_data->>'phone', '')), ''),
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

-- ── Backfill existing NULL / empty roles ─────────────────────────────────────
UPDATE public.user_profiles up
SET role = CASE
  WHEN EXISTS (
    SELECT 1
    FROM public.team_members tm
    WHERE tm.member_user_id = up.id
       OR (
         up.email IS NOT NULL
         AND lower(btrim(tm.invited_email)) = lower(btrim(up.email))
       )
  ) THEN 'staff'
  ELSE 'admin'
END
WHERE up.role IS NULL OR btrim(up.role) = '';
