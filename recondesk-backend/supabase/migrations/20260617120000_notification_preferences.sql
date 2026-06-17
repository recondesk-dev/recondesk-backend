-- Create notification_preferences table to persist per-user email notification preferences.
-- Categories: run_completed, runs_expiring_soon, payment_receipts.
-- Default value for all preferences is true (enabled).

CREATE TABLE IF NOT EXISTS public.notification_preferences (
  user_id uuid PRIMARY KEY REFERENCES public.user_profiles (id) ON DELETE CASCADE,
  run_completed boolean NOT NULL DEFAULT true,
  runs_expiring_soon boolean NOT NULL DEFAULT true,
  payment_receipts boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Index for lookup (though primary key is indexed, it's good practice)
CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_preferences_user_id 
  ON public.notification_preferences (user_id);

-- Enable RLS
ALTER TABLE public.notification_preferences ENABLE ROW LEVEL SECURITY;

-- Select policy: users can only read their own preferences
DROP POLICY IF EXISTS "notification_preferences_select_own" ON public.notification_preferences;
CREATE POLICY "notification_preferences_select_own" ON public.notification_preferences
  FOR SELECT TO authenticated USING (user_id = auth.uid());

-- Insert policy: users can only insert their own preferences
DROP POLICY IF EXISTS "notification_preferences_insert_own" ON public.notification_preferences;
CREATE POLICY "notification_preferences_insert_own" ON public.notification_preferences
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());

-- Update policy: users can only update their own preferences
DROP POLICY IF EXISTS "notification_preferences_update_own" ON public.notification_preferences;
CREATE POLICY "notification_preferences_update_own" ON public.notification_preferences
  FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- Schema permissions
GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.notification_preferences TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notification_preferences TO postgres, service_role;

COMMENT ON TABLE public.notification_preferences IS 'Per-user email notification toggles (run_completed, runs_expiring_soon, payment_receipts).';
