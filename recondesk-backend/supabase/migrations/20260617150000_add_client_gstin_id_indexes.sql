-- Add client_gstin_id indexes to optimize queries filtering by client.
CREATE INDEX IF NOT EXISTS idx_gstr_records_client_gstin_id ON public.gstr_records (client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_pr_records_client_gstin_id ON public.pr_records (client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_client_gstin_id ON public.user_profiles (client_gstin_id);
