-- RLS so the browser Supabase client can read active import runs (resume flow).
-- Optional: tighten policies to match your auth setup.

alter table public.reconciliation_import_runs
  add column if not exists pr_column_headers jsonb;

drop policy if exists import_runs_owner_select on public.reconciliation_import_runs;
create policy import_runs_owner_select
  on public.reconciliation_import_runs
  for select
  to authenticated
  using (
    firm_owner_id = auth.uid()
    or created_by = auth.uid()
  );

drop policy if exists import_runs_owner_update on public.reconciliation_import_runs;
create policy import_runs_owner_update
  on public.reconciliation_import_runs
  for update
  to authenticated
  using (created_by = auth.uid())
  with check (created_by = auth.uid());
