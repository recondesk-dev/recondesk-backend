-- Add nullable match_confidence column to reconciliation_results.
-- Stores the invoice_similarity() score [0.0–1.0] for L5/fuzzy matches.
-- NULL for L1–L4 exact matches (no graded score to surface).
-- This is additive — no existing columns are modified or dropped.

ALTER TABLE IF EXISTS reconciliation_results
  ADD COLUMN IF NOT EXISTS match_confidence REAL;

COMMENT ON COLUMN reconciliation_results.match_confidence IS
  'Invoice similarity score [0.0–1.0] for L5/fuzzy matches. NULL for exact matches.';
