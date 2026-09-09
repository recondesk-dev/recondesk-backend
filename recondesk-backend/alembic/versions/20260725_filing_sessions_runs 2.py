"""Create filing_sessions and filing_runs for GSTN taxpayer OTP + return filing.

Revision ID: filing_sessions_runs
Revises: auto_approve_confidence

``filing_sessions`` holds the Sandbox taxpayer access token (~6hr) and is
intentionally return-type-agnostic so IMS accept/reject and GSTR-1/3B filing
can share the same OTP session model later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "filing_sessions_runs"
down_revision = "auto_approve_confidence"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name LIMIT 1"
        ),
        {"name": name},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    if not _table_exists("filing_sessions"):
        op.execute(
            sa.text(
                """
                CREATE TABLE filing_sessions (
                    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    firm_id             UUID NOT NULL
                        REFERENCES user_profiles (id) ON DELETE CASCADE,
                    client_gstin_id     UUID
                        REFERENCES client_gstins (id) ON DELETE SET NULL,
                    gstin               TEXT NOT NULL,
                    username            TEXT NOT NULL DEFAULT '',
                    session_token       TEXT NOT NULL,
                    token_expires_at    TIMESTAMPTZ NOT NULL,
                    session_expires_at  TIMESTAMPTZ,
                    status              TEXT NOT NULL DEFAULT 'active',
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    logged_out_at       TIMESTAMPTZ,
                    CONSTRAINT filing_sessions_status_chk
                        CHECK (status IN ('active', 'expired', 'logged_out'))
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_sessions_firm_gstin "
                "ON filing_sessions (firm_id, gstin);"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_sessions_firm_active "
                "ON filing_sessions (firm_id, status, token_expires_at DESC) "
                "WHERE status = 'active';"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_sessions_client_gstin "
                "ON filing_sessions (client_gstin_id) "
                "WHERE client_gstin_id IS NOT NULL;"
            )
        )

    if not _table_exists("filing_runs"):
        op.execute(
            sa.text(
                """
                CREATE TABLE filing_runs (
                    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    firm_id             UUID NOT NULL
                        REFERENCES user_profiles (id) ON DELETE CASCADE,
                    client_gstin_id     UUID
                        REFERENCES client_gstins (id) ON DELETE SET NULL,
                    filing_session_id   UUID
                        REFERENCES filing_sessions (id) ON DELETE SET NULL,
                    gstin               TEXT NOT NULL,
                    return_type         TEXT NOT NULL,
                    period              VARCHAR(7) NOT NULL,
                    status              TEXT NOT NULL DEFAULT 'draft',
                    reference_id        TEXT,
                    ack_number          TEXT,
                    save_payload        JSONB,
                    raw_response        JSONB,
                    error_code          TEXT,
                    error_message       TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT filing_runs_return_type_chk
                        CHECK (return_type IN (
                            'gstr-1', 'gstr-1a', 'gstr-3b', 'gstr-9', 'other'
                        )),
                    CONSTRAINT filing_runs_status_chk
                        CHECK (status IN (
                            'draft',
                            'save_pending',
                            'saved',
                            'save_failed',
                            'proceeded',
                            'evc_pending',
                            'filed',
                            'failed'
                        )),
                    CONSTRAINT filing_runs_period_chk
                        CHECK (period ~ '^[0-9]{4}-[0-9]{2}$')
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_runs_firm_period "
                "ON filing_runs (firm_id, return_type, period, created_at DESC);"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_runs_gstin_period "
                "ON filing_runs (gstin, return_type, period, created_at DESC);"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_runs_session "
                "ON filing_runs (filing_session_id) "
                "WHERE filing_session_id IS NOT NULL;"
            )
        )


def downgrade() -> None:
    if _table_exists("filing_runs"):
        op.execute(sa.text("DROP TABLE IF EXISTS filing_runs CASCADE"))
    if _table_exists("filing_sessions"):
        op.execute(sa.text("DROP TABLE IF EXISTS filing_sessions CASCADE"))
