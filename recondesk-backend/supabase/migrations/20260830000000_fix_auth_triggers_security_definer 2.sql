-- Fix triggers on auth.users and user_profiles to have SECURITY DEFINER and explicit search_path
-- This prevents "Database error granting user" when Supabase Auth (GoTrue) creates or grants tokens to users.

CREATE OR REPLACE FUNCTION public.user_profile_role_for_auth_user(
  p_user_id uuid,
  p_email text,
  p_meta jsonb DEFAULT '{}'::jsonb
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
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
EXCEPTION WHEN OTHERS THEN
  RETURN 'admin';
END;
$$;

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_meta jsonb := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb);
  v_role text;
  v_full_name text := NULLIF(btrim(COALESCE(v_meta->>'full_name', '')), '');
  v_firm_name text := NULLIF(btrim(COALESCE(v_meta->>'firm_name', '')), '');
  v_phone text := NULLIF(btrim(COALESCE(v_meta->>'phone', '')), '');
BEGIN
  v_role := public.user_profile_role_for_auth_user(NEW.id, NEW.email, v_meta);

  INSERT INTO public.user_profiles (id, email, full_name, firm_name, phone, role)
  VALUES (
    NEW.id,
    NEW.email,
    v_full_name,
    v_firm_name,
    v_phone,
    v_role
  )
  ON CONFLICT (id) DO UPDATE SET
    full_name = COALESCE(v_full_name, user_profiles.full_name),
    firm_name = COALESCE(v_firm_name, user_profiles.firm_name),
    phone = COALESCE(v_phone, user_profiles.phone);

  RETURN NEW;
EXCEPTION WHEN OTHERS THEN
  -- Never block auth.users creation or token issuance on secondary profile operations
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_user();

CREATE OR REPLACE FUNCTION public.user_profiles_resolve_role()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
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
EXCEPTION WHEN OTHERS THEN
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS user_profiles_resolve_role ON public.user_profiles;
CREATE TRIGGER user_profiles_resolve_role
  BEFORE INSERT OR UPDATE ON public.user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.user_profiles_resolve_role();

-- Grant permissions so supabase_auth_admin has clean access
GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role, supabase_auth_admin;
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role, supabase_auth_admin;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO postgres, anon, authenticated, service_role, supabase_auth_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role, supabase_auth_admin;
