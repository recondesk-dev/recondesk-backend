-- Speeds runs list / manage-data / client history ordered by newest first.
CREATE INDEX IF NOT EXISTS idx_reconciliation_run_client_created_at
  ON public.reconciliation_run (client_gstin_id, created_at DESC);
