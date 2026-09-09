-- Per-period "Mark GSTR-1A as filed" actions for a GSTR-1 reconciliation run.
-- Mirrors rule37_actions uniqueness (run_id + period) for settlement-style history.

CREATE TABLE IF NOT EXISTS public.gstr1a_period_actions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      uuid NOT NULL REFERENCES public.gstr1_reconciliation_run(id) ON DELETE CASCADE,
  period      varchar(32) NOT NULL,
  status      text NOT NULL DEFAULT 'filed',
  filed_date  date,
  note        text,
  user_id     text NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr1a_period_actions_run_id
  ON public.gstr1a_period_actions (run_id);

GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.gstr1a_period_actions
  TO postgres, service_role;

GRANT SELECT, INSERT, UPDATE ON TABLE public.gstr1a_period_actions
  TO authenticated;

-- FastAPI uses service_role; access is enforced in the API layer (same as rule37_actions).
ALTER TABLE public.gstr1a_period_actions DISABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.gstr1a_period_actions IS
  'GSTR-1A filed actions per reconciliation run period (mark GSTR-1A as filed).';
