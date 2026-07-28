-- Persist the full supplier follow-up letter body alongside existing audit metadata.
-- Nullable for legacy rows written before this column existed.

ALTER TABLE public.supplier_followup_audit
    ADD COLUMN IF NOT EXISTS letter_body text;

COMMENT ON COLUMN public.supplier_followup_audit.letter_body IS
    'Full letter text as generated/copied/downloaded by the CA at audit action time.';
