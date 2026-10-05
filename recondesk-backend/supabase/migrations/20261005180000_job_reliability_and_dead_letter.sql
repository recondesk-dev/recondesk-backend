-- Migration: 20261005180000_job_reliability_and_dead_letter.sql
-- Add heartbeat, worker tracking, and dead-letter/failed jobs tracking for enterprise background reliability.

-- 1. Extend reconciliation_run with heartbeat, attempt tracking, and worker correlation
ALTER TABLE public.reconciliation_run
  ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS worker_task_id TEXT,
  ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS correlation_id TEXT,
  ADD COLUMN IF NOT EXISTS error_category TEXT;

CREATE INDEX IF NOT EXISTS idx_reconciliation_run_heartbeat
  ON public.reconciliation_run (status, last_heartbeat_at)
  WHERE status IN ('MATCHING', 'PROCESSING', 'importing');

-- 2. Extend reconciliation_import_runs mirror table if present
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables 
    WHERE table_schema = 'public' AND table_name = 'reconciliation_import_runs'
  ) THEN
    ALTER TABLE public.reconciliation_import_runs
      ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS worker_task_id TEXT,
      ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS correlation_id TEXT;
  END IF;
END $$;

-- 3. Dead letter / failed jobs table for Celery background tasks
CREATE TABLE IF NOT EXISTS public.failed_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id TEXT NOT NULL,
    task_name TEXT NOT NULL,
    queue TEXT,
    entity_id TEXT,
    entity_type TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    error_category TEXT,
    error_message TEXT,
    correlation_id TEXT,
    payload_summary JSONB,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_failed_jobs_task_name ON public.failed_jobs(task_name);
CREATE INDEX IF NOT EXISTS idx_failed_jobs_failed_at ON public.failed_jobs(failed_at DESC);
CREATE INDEX IF NOT EXISTS idx_failed_jobs_entity ON public.failed_jobs(entity_type, entity_id);

ALTER TABLE public.failed_jobs DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.failed_jobs TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.failed_jobs TO authenticated;

