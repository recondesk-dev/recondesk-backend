-- Billing: free runs, run credit batches, payments columns, paid_at on runs.
-- Safe to re-run: uses IF NOT EXISTS / DO blocks where needed.

-- ── user_profiles ───────────────────────────────────────────────────────────
ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS free_runs_remaining integer NOT NULL DEFAULT 2;

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS runs_balance integer NOT NULL DEFAULT 0;

ALTER TABLE public.user_profiles
  ADD COLUMN IF NOT EXISTS firm_city text;

-- ── reconciliation_run (singular; matches FastAPI / worker) ─────────────────
ALTER TABLE public.reconciliation_run
  ADD COLUMN IF NOT EXISTS paid_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_reconciliation_run_paid_at
  ON public.reconciliation_run (paid_at);

-- ── payments (extend existing) ─────────────────────────────────────────────
ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS plan text;

ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS runs_purchased integer;

ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS base_amount_paise bigint;

ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS gst_paise bigint;

ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS total_amount_paise bigint;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'payments_plan_check'
  ) THEN
    ALTER TABLE public.payments ADD CONSTRAINT payments_plan_check CHECK (
      plan IS NULL OR plan IN ('starter', 'growth', 'pro', 'enterprise')
    );
  END IF;
END $$;

-- ── run_credits ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.run_credits (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_owner_id uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
  payment_id uuid REFERENCES public.payments (id) ON DELETE SET NULL,
  plan text NOT NULL CHECK (plan IN ('starter', 'growth', 'pro')),
  runs_purchased integer NOT NULL,
  runs_remaining integer NOT NULL,
  purchased_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_run_credits_owner_expires
  ON public.run_credits (firm_owner_id, expires_at);

ALTER TABLE public.run_credits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "run_credits_select_own" ON public.run_credits;
CREATE POLICY "run_credits_select_own" ON public.run_credits
  FOR SELECT USING (firm_owner_id = auth.uid());

DROP POLICY IF EXISTS "run_credits_insert_own" ON public.run_credits;
CREATE POLICY "run_credits_insert_own" ON public.run_credits
  FOR INSERT WITH CHECK (firm_owner_id = auth.uid());

DROP POLICY IF EXISTS "run_credits_update_own" ON public.run_credits;
CREATE POLICY "run_credits_update_own" ON public.run_credits
  FOR UPDATE USING (firm_owner_id = auth.uid());

COMMENT ON TABLE public.run_credits IS 'Purchased reconciliation run batches; FIFO consume by expires_at.';
