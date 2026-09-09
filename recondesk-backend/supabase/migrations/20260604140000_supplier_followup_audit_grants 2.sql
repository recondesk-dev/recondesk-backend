-- Grants and RLS for supplier_followup_audit (FastAPI inserts via service_role).

GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.supplier_followup_audit
    TO postgres, service_role;

GRANT SELECT, INSERT ON TABLE public.supplier_followup_audit
    TO authenticated;

-- Service role bypasses RLS; disable RLS so misconfigured keys fail loudly in logs, not silently.
ALTER TABLE public.supplier_followup_audit DISABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.supplier_followup_audit IS
    'Audit trail for supplier follow-up letters; snapshot JSON is captured at generation time from the client.';
