-- GSTR-3B Offset lifecycle on filing_runs.
-- Outer Sandbox status_cd "1" on Offset ≠ accepted for processing;
-- offset_complete is set only after Return Status inner status_cd P.
-- Once offset_complete (or later), Save and Offset for the same
-- (gstin, period, gstr-3b) are hard-blocked at the app layer.

ALTER TABLE public.filing_runs DROP CONSTRAINT IF EXISTS filing_runs_status_chk;

ALTER TABLE public.filing_runs
    ADD CONSTRAINT filing_runs_status_chk
    CHECK (status IN (
        'draft',
        'save_pending',
        'saved',
        'save_failed',
        'offset_pending',
        'offset_complete',
        'offset_failed',
        'proceeded',
        'evc_pending',
        'filed',
        'failed'
    ));

ALTER TABLE public.filing_runs
    ADD COLUMN IF NOT EXISTS offset_payload jsonb,
    ADD COLUMN IF NOT EXISTS offset_completed_at timestamptz,
    ADD COLUMN IF NOT EXISTS tx_pmt_snapshot jsonb;

CREATE INDEX IF NOT EXISTS idx_filing_runs_gstr3b_offset_gate
    ON public.filing_runs (gstin, period, status)
    WHERE return_type = 'gstr-3b'
      AND status IN (
          'offset_complete',
          'evc_pending',
          'filed'
      );

COMMENT ON COLUMN public.filing_runs.offset_payload IS
    'Exact {pdcash, pditc} body confirmed by the CA and POSTed to Offset Liability.';
COMMENT ON COLUMN public.filing_runs.offset_completed_at IS
    'Set when Return Status confirms Offset inner status_cd P — permanent gate.';
COMMENT ON COLUMN public.filing_runs.tx_pmt_snapshot IS
    'Post-Offset Get GSTR-3B Details tx_pmt block; shown as proof on 409 gate blocks.';
