-- Enforce database-level immutability on audit_logs table (SOC2 / ISO 27001 compliance)
-- Prevents UPDATE and DELETE operations, ensuring the audit trail is strictly append-only.
-- Safe with user_profiles ON DELETE SET NULL cascade.

CREATE OR REPLACE FUNCTION public.prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit_logs table is append-only: deletions are strictly forbidden.';
    ELSIF TG_OP = 'UPDATE' THEN
        -- Allow system foreign-key cascade ON DELETE SET NULL for firm_id when a user profile is deleted,
        -- while strictly forbidding any user-space or application update to action, entity, metadata, or logs.
        IF (OLD.firm_id IS NOT NULL AND NEW.firm_id IS NULL)
           AND (OLD.id = NEW.id)
           AND (OLD.action = NEW.action)
           AND (OLD.entity_type = NEW.entity_type)
           AND (OLD.created_at = NEW.created_at) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'audit_logs table is append-only: updates are strictly forbidden.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON public.audit_logs;
CREATE TRIGGER trg_audit_logs_immutable
BEFORE UPDATE OR DELETE ON public.audit_logs
FOR EACH ROW
EXECUTE FUNCTION public.prevent_audit_log_modification();

COMMENT ON FUNCTION public.prevent_audit_log_modification IS
    'Guarantees immutability for statutory audit trail by blocking any UPDATE or DELETE operations.';
