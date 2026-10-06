-- Add storage metadata columns to reconciliation_results for externalized payload storage (R2/S3)
-- Allows storing large enterprise reconciliation payloads in Cloudflare R2 / S3 object storage
-- while keeping lightweight metadata and pointer records in PostgreSQL.

ALTER TABLE public.reconciliation_results
    ADD COLUMN IF NOT EXISTS storage_type VARCHAR(32) DEFAULT 'db',
    ADD COLUMN IF NOT EXISTS storage_path TEXT,
    ADD COLUMN IF NOT EXISTS payload_size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS compressed_size_bytes BIGINT;

CREATE INDEX IF NOT EXISTS idx_reconciliation_results_storage_type
    ON public.reconciliation_results (storage_type);

COMMENT ON COLUMN public.reconciliation_results.storage_type IS
    'Storage mechanism for reconciliation payload: "db" (PostgreSQL row) or "r2" (Cloudflare R2 / S3 object storage).';

COMMENT ON COLUMN public.reconciliation_results.storage_path IS
    'Object key path in object storage when storage_type is "r2".';

COMMENT ON COLUMN public.reconciliation_results.payload_size_bytes IS
    'Uncompressed raw JSON size of reconciliation payload in bytes.';

COMMENT ON COLUMN public.reconciliation_results.compressed_size_bytes IS
    'Gzip-compressed size of reconciliation payload in bytes.';
