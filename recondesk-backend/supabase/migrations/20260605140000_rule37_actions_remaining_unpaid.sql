-- Remaining unpaid amount after Rule 37 settlement (net paid + statutory deduction).

ALTER TABLE rule37_actions
  ADD COLUMN IF NOT EXISTS remaining_unpaid_amount numeric(15,2);
