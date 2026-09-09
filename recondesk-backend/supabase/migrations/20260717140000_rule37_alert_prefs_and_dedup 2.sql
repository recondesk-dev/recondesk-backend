-- Rule 37 proactive email alerts: preference toggle + per-invoice dedup.

-- 1) Notification preference (default ON for existing and new users)
ALTER TABLE public.notification_preferences
  ADD COLUMN IF NOT EXISTS rule37_alerts boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN public.notification_preferences.rule37_alerts IS
  'Email alerts when unpaid invoices approach or pass the Rule 37 180-day payment deadline.';

COMMENT ON TABLE public.notification_preferences IS
  'Per-user email notification toggles (run_completed, runs_expiring_soon, payment_receipts, rule37_alerts).';

-- 2) Dedup: one row per client invoice; re-alert on tier change or cooldown
CREATE TABLE IF NOT EXISTS public.rule37_alert_dedup (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_owner_id uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
  client_gstin_id uuid NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
  -- Stable across runs: supplier_gstin|invoice_number|invoice_date
  invoice_key text NOT NULL,
  last_alert_tier text NOT NULL,
  last_sent_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT rule37_alert_dedup_tier_check CHECK (
    last_alert_tier IN ('WARNING_60_DAYS', 'WARNING_30_DAYS', 'OVERDUE_UNPAID')
  ),
  CONSTRAINT rule37_alert_dedup_client_invoice_unique UNIQUE (client_gstin_id, invoice_key)
);

CREATE INDEX IF NOT EXISTS idx_rule37_alert_dedup_firm_owner
  ON public.rule37_alert_dedup (firm_owner_id);

CREATE INDEX IF NOT EXISTS idx_rule37_alert_dedup_last_sent
  ON public.rule37_alert_dedup (last_sent_at);

ALTER TABLE public.rule37_alert_dedup ENABLE ROW LEVEL SECURITY;

-- API uses service_role; no authenticated client policies needed for writes.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.rule37_alert_dedup
  TO postgres, service_role;

COMMENT ON TABLE public.rule37_alert_dedup IS
  'Tracks last Rule 37 email alert tier per invoice to avoid re-sending every scan cycle.';
