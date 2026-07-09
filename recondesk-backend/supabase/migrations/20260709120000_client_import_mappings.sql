-- Persistent PR column mappings per client GSTIN.
-- Applied before purchase-register normalization so custom headers reshape
-- into the parser's expected schema.

create table if not exists public.client_import_mappings (
  id uuid primary key default gen_random_uuid(),
  client_gstin_id uuid not null references public.client_gstins (id) on delete cascade,
  source_column_name text not null,
  target_field text not null
    check (target_field in (
      'gstin',
      'invoice_number',
      'invoice_date',
      'taxable_value',
      'cgst',
      'sgst',
      'igst',
      'cess'
    )),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint client_import_mappings_client_target_unique
    unique (client_gstin_id, target_field)
);

create index if not exists client_import_mappings_client_gstin_id_idx
  on public.client_import_mappings (client_gstin_id);

create or replace function public.set_client_import_mappings_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_client_import_mappings_updated_at
  on public.client_import_mappings;
create trigger trg_client_import_mappings_updated_at
  before update on public.client_import_mappings
  for each row execute function public.set_client_import_mappings_updated_at();

alter table public.client_import_mappings enable row level security;

comment on table public.client_import_mappings is
  'Saved PR column → standard-field mappings per client_gstin_id';
