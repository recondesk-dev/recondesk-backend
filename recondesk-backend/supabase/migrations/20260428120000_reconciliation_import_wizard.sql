-- Import wizard runs (parallel to legacy reconciliation_runs processing table).
-- Apply via Supabase SQL editor or: supabase db push

create table if not exists public.reconciliation_import_runs (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.client_gstins (id) on delete cascade,
  firm_owner_id uuid references public.user_profiles (id) on delete set null,
  period date not null,
  status text not null default 'draft'
    check (status in (
      'draft', 'gstr_uploaded', 'pr_uploaded', 'pending', 'processing',
      'complete', 'error', 'cancelled'
    )),
  current_step int not null default 1 check (current_step between 1 and 4),
  gstr2b_r2_key text,
  gstr2b_file_name text,
  gstr2b_file_size int,
  gstr2b_file_hash text,
  gstr2b_uploaded_at timestamptz,
  gstr2b_record_count int default 0,
  sanity_check_results jsonb,
  pr_r2_key text,
  pr_file_name text,
  pr_file_size int,
  pr_file_hash text,
  pr_uploaded_at timestamptz,
  pr_record_count int default 0,
  column_mapping jsonb,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  progress_pct int not null default 0,
  status_message text,
  error_detail text
);

create unique index if not exists reconciliation_import_runs_one_active_per_client_period
  on public.reconciliation_import_runs (client_id, period)
  where status not in ('complete', 'cancelled', 'error');

create index if not exists reconciliation_import_runs_client_id_idx
  on public.reconciliation_import_runs (client_id);

create table if not exists public.reconciliation_import_run_audit_log (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.reconciliation_import_runs (id) on delete cascade,
  user_id uuid not null,
  event text not null,
  detail jsonb,
  created_at timestamptz not null default now()
);

create index if not exists reconciliation_import_run_audit_log_run_id_idx
  on public.reconciliation_import_run_audit_log (run_id);

-- updated_at trigger
create or replace function public.set_reconciliation_import_runs_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_reconciliation_import_runs_updated_at on public.reconciliation_import_runs;
create trigger trg_reconciliation_import_runs_updated_at
  before update on public.reconciliation_import_runs
  for each row execute function public.set_reconciliation_import_runs_updated_at();

alter table public.reconciliation_import_runs enable row level security;
alter table public.reconciliation_import_run_audit_log enable row level security;

-- Service role bypasses RLS; add policies if clients use anon key directly.

comment on table public.reconciliation_import_runs is 'Multi-step GSTR-2B + PR import wizard state';
comment on table public.reconciliation_import_run_audit_log is 'Audit trail for wizard actions and status transitions';
