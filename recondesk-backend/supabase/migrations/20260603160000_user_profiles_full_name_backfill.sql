-- Ensure full_name is copied from auth metadata into user_profiles on signup.
-- Safe to re-run.

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
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_user();

-- Backfill NULL full_name from auth.users metadata
UPDATE public.user_profiles p
SET full_name = u.raw_user_meta_data->>'full_name'
FROM auth.users u
WHERE p.id = u.id
  AND (p.full_name IS NULL OR btrim(p.full_name) = '')
  AND NULLIF(btrim(u.raw_user_meta_data->>'full_name'), '') IS NOT NULL;
