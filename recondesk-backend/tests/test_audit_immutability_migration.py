"""Tests for audit logs database immutability migration and Alembic upgrade script."""

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_supabase_audit_immutability_migration_contents():
    """Verify Supabase migration enforces append-only trigger on audit_logs."""
    migration_file = BACKEND_DIR / "supabase/migrations/20261006150000_audit_logs_immutability.sql"
    if not migration_file.exists():
        migration_file = Path("supabase/migrations/20261006150000_audit_logs_immutability.sql")
    assert migration_file.exists(), "Migration file 20261006150000_audit_logs_immutability.sql must exist"
    
    content = migration_file.read_text(encoding="utf-8")
    assert "prevent_audit_log_modification" in content
    assert "BEFORE UPDATE OR DELETE ON public.audit_logs" in content
    assert "RAISE EXCEPTION" in content
    assert "append-only" in content


def test_supabase_storage_offload_migration_contents():
    """Verify Supabase migration adds storage metadata columns to reconciliation_results."""
    migration_file = BACKEND_DIR / "supabase/migrations/20261006140000_reconciliation_results_storage_offload.sql"
    if not migration_file.exists():
        migration_file = Path("supabase/migrations/20261006140000_reconciliation_results_storage_offload.sql")
    assert migration_file.exists(), "Migration file 20261006140000_reconciliation_results_storage_offload.sql must exist"

    content = migration_file.read_text(encoding="utf-8")
    assert "ALTER TABLE public.reconciliation_results" in content
    assert "ADD COLUMN IF NOT EXISTS storage_type" in content
    assert "ADD COLUMN IF NOT EXISTS storage_path" in content
    assert "ADD COLUMN IF NOT EXISTS payload_size_bytes" in content
    assert "ADD COLUMN IF NOT EXISTS compressed_size_bytes" in content


def test_alembic_sprint2b_migration_contents():
    """Verify Alembic migration script defines upgrade and downgrade correctly."""
    alembic_file = BACKEND_DIR / "alembic/versions/20261006140000_sprint2b_storage_and_audit.py"
    if not alembic_file.exists():
        alembic_file = Path("alembic/versions/20261006140000_sprint2b_storage_and_audit.py")
    assert alembic_file.exists(), "Alembic migration 20261006140000_sprint2b_storage_and_audit.py must exist"

    content = alembic_file.read_text(encoding="utf-8")
    assert "20261006140000_sprint2b_storage_and_audit" in content
    assert "20260923_payments_b2b_gstin" in content  # down_revision
    assert "storage_type" in content
    assert "trg_audit_logs_immutable" in content
    assert "def upgrade():" in content
    assert "def downgrade():" in content


def test_trigger_logic_behavior():
    """Verify trigger logic specification: blocks delete, blocks content update, allows firm_id nullification."""
    # Simulated trigger function logic mirroring PL/pgSQL
    def simulate_trigger(tg_op, old, new):
        if tg_op == "DELETE":
            raise RuntimeError("audit_logs table is append-only: deletions are strictly forbidden.")
        elif tg_op == "UPDATE":
            if (
                old.get("firm_id") is not None
                and new.get("firm_id") is None
                and old.get("id") == new.get("id")
                and old.get("action") == new.get("action")
                and old.get("entity_type") == new.get("entity_type")
                and old.get("created_at") == new.get("created_at")
            ):
                return new
            raise RuntimeError("audit_logs table is append-only: updates are strictly forbidden.")
        return new

    # 1. Normal insert
    assert simulate_trigger("INSERT", None, {"id": "1", "action": "test"}) == {"id": "1", "action": "test"}

    # 2. Delete must raise
    import pytest
    with pytest.raises(RuntimeError, match="deletions are strictly forbidden"):
        simulate_trigger("DELETE", {"id": "1"}, None)

    # 3. Content update must raise
    with pytest.raises(RuntimeError, match="updates are strictly forbidden"):
        simulate_trigger("UPDATE", {"id": "1", "action": "create"}, {"id": "1", "action": "tampered"})

    # 4. Metadata update must raise
    with pytest.raises(RuntimeError, match="updates are strictly forbidden"):
        simulate_trigger(
            "UPDATE",
            {"id": "1", "action": "create", "entity_type": "client", "created_at": "now", "metadata": {}},
            {"id": "1", "action": "create", "entity_type": "client", "created_at": "now", "metadata": {"malicious": True}},
        )

    # 5. User profile deletion cascade (firm_id nullification) succeeds
    allowed = simulate_trigger(
        "UPDATE",
        {"id": "1", "firm_id": "firm-123", "action": "create", "entity_type": "client", "created_at": "now"},
        {"id": "1", "firm_id": None, "action": "create", "entity_type": "client", "created_at": "now"},
    )
    assert allowed["firm_id"] is None
