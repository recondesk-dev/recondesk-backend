-- Enhanced audit_logs: firm scoping, actor display fields, entity labels, admin-only RLS.
-- firm_id references the workspace owner (user_profiles.id); there is no separate firms table.

ALTER TABLE public.audit_logs
    ADD COLUMN IF NOT EXISTS firm_id UUID,
    ADD COLUMN IF NOT EXISTS user_name TEXT,
    ADD COLUMN IF NOT EXISTS role TEXT,
    ADD COLUMN IF NOT EXISTS entity_label TEXT;

CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_created
    ON public.audit_logs (firm_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_user
    ON public.audit_logs (firm_id, user_id, created_at DESC);

COMMENT ON COLUMN public.audit_logs.firm_id IS
    'Workspace owner user_profiles.id (firm anchor).';

-- Insert-only for authenticated; service_role bypasses RLS for FastAPI writes.
REVOKE UPDATE, DELETE ON TABLE public.audit_logs FROM authenticated;
GRANT SELECT, INSERT ON TABLE public.audit_logs TO authenticated;
GRANT ALL ON TABLE public.audit_logs TO service_role;

ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_logs_admin_select ON public.audit_logs;
CREATE POLICY audit_logs_admin_select
    ON public.audit_logs
    FOR SELECT
    TO authenticated
    USING (firm_id = auth.uid());

DROP POLICY IF EXISTS audit_logs_insert ON public.audit_logs;
CREATE POLICY audit_logs_insert
    ON public.audit_logs
    FOR INSERT
    TO authenticated
    WITH CHECK (user_id = auth.uid());

COMMENT ON TABLE public.audit_logs IS
    'Insert-only workspace audit trail. Admins read via firm_id = auth.uid(); staff cannot read.';
