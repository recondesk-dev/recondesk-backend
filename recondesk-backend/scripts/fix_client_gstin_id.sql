-- Fix client_gstin_id width for UUIDs (client_gstins.id). Run ONE section at a time in Supabase SQL Editor.
-- If something errors, run the diagnostics at the bottom and share the messages.

-- ── 0) Optional: see what exists and current types ───────────────────────────
-- SELECT table_name, column_name, data_type, character_maximum_length
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name IN ('reconciliation_run','gstr_records','pr_records')
--   AND column_name = 'client_gstin_id';

-- ── 1) Preferred: widen to TEXT (avoids length issues; works from varchar or text) ──

ALTER TABLE public.reconciliation_run
  ALTER COLUMN client_gstin_id TYPE TEXT USING client_gstin_id::text;

ALTER TABLE public.gstr_records
  ALTER COLUMN client_gstin_id TYPE TEXT USING client_gstin_id::text;

ALTER TABLE public.pr_records
  ALTER COLUMN client_gstin_id TYPE TEXT USING client_gstin_id::text;

-- ── 2) If you get an error about constraint uq_run_dedup, use this block for reconciliation_run ONLY ──
-- (Run instead of the reconciliation_run line in section 1)

-- ALTER TABLE public.reconciliation_run DROP CONSTRAINT IF EXISTS uq_run_dedup;
-- ALTER TABLE public.reconciliation_run
--   ALTER COLUMN client_gstin_id TYPE TEXT USING client_gstin_id::text;
-- ALTER TABLE public.reconciliation_run
--   ADD CONSTRAINT uq_run_dedup UNIQUE (client_gstin_id, period, file_type, file_hash);

-- ── 3) If column is already UUID type, use: ─────────────────────────────────
-- ALTER TABLE public.reconciliation_run
--   ALTER COLUMN client_gstin_id TYPE TEXT USING client_gstin_id::text;
