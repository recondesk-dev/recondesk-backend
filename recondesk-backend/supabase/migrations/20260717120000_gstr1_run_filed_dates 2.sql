-- GSTR-1A amendment window inputs on sell-side reconciliation runs.
-- Window is open after GSTR-1 is filed and closes when GSTR-3B is filed
-- (or at the statutory GSTR-3B due date for the period).

ALTER TABLE public.gstr1_reconciliation_run
  ADD COLUMN IF NOT EXISTS gstr1_filed_date date;

ALTER TABLE public.gstr1_reconciliation_run
  ADD COLUMN IF NOT EXISTS gstr3b_filed_date date;
