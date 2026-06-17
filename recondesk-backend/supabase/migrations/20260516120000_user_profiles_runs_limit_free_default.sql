-- Align runs_limit with free_runs_remaining (2) for the free tier.
-- Safe to re-run: conditional DDL + scoped UPDATE (skips paid accounts).

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_profiles'
      AND column_name = 'runs_limit'
  ) THEN
    ALTER TABLE public.user_profiles
      ADD COLUMN runs_limit integer DEFAULT 2;
  ELSE
    ALTER TABLE public.user_profiles
      ALTER COLUMN runs_limit SET DEFAULT 2;
  END IF;
END $$;

-- Free-tier housekeeping: set display cap to 2 for users who have never paid
-- and hold no purchased-run balance. Does not change rows with paid history or runs_balance > 0.
UPDATE public.user_profiles up
SET runs_limit = 2
WHERE (up.plan IS NULL OR lower(trim(up.plan)) = 'free')
  AND COALESCE(up.runs_balance, 0) = 0
  AND NOT EXISTS (
    SELECT 1
    FROM public.payments p
    WHERE p.firm_owner_id = up.id
      AND lower(coalesce(p.status::text, '')) = 'paid'
  )
  AND (up.runs_limit IS DISTINCT FROM 2);
