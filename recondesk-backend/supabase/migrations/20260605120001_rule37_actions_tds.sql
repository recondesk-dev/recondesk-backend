-- Manual TDS adjustment fields for Rule 37 mark-paid actions (CA-entered, not IT-verified).

ALTER TABLE rule37_actions
  ADD COLUMN IF NOT EXISTS amount_paid numeric(15,2),
  ADD COLUMN IF NOT EXISTS tds_deducted numeric(15,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tds_confirmed boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS total_settled numeric(15,2),
  ADD COLUMN IF NOT EXISTS payment_coverage text;
