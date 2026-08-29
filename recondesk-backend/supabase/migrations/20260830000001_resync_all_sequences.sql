-- Resynchronize all sequence counters in auth and public schemas to max(id) + 1
-- Prevents duplicate key errors on refresh_tokens, audit_log_entries, and tables after data migrations.

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT table_schema, table_name, column_name,
               pg_get_serial_sequence(quote_ident(table_schema) || '.' || quote_ident(table_name), column_name) AS seq
        FROM information_schema.columns
        WHERE column_default LIKE 'nextval(%'
          AND table_schema IN ('auth', 'public')
    ) LOOP
        IF r.seq IS NOT NULL THEN
            EXECUTE format('SELECT setval(%L, COALESCE((SELECT MAX(%I) FROM %I.%I), 0) + 1, false);',
                           r.seq, r.column_name, r.table_schema, r.table_name);
        END IF;
    END LOOP;
END $$;
