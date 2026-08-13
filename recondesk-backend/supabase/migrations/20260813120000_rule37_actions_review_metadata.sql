-- Add review_metadata column to rule37_actions for Tally Bridge weak-match review queue.
-- This stores party similarity score, match reason, and what it matched against
-- so CAs can make an informed approve/reject decision.

ALTER TABLE public.rule37_actions
  ADD COLUMN IF NOT EXISTS review_metadata JSONB DEFAULT NULL;

COMMENT ON COLUMN public.rule37_actions.review_metadata IS
  'Tally Bridge review context: party_sim, party_gate_min, bill_ref_score, reason, etc.';
