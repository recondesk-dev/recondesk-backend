-- Outer Sandbox status_cd "1" on Save ≠ accepted for processing.
-- Runs: draft → save_pending → saved | save_failed after Return Status
-- shows inner GSTN status_cd P / ER|PE.

ALTER TABLE public.filing_runs DROP CONSTRAINT IF EXISTS filing_runs_status_chk;

ALTER TABLE public.filing_runs
    ADD CONSTRAINT filing_runs_status_chk
    CHECK (status IN (
        'draft',
        'save_pending',
        'saved',
        'save_failed',
        'proceeded',
        'evc_pending',
        'filed',
        'failed'
    ));
