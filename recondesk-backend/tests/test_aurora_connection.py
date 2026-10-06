"""Unit and optional integration tests for the AWS Aurora PostgreSQL connection layer."""

import concurrent.futures
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.aurora import (
    AuroraConfigurationError,
    AuroraConnectionError,
    aurora_session_scope,
    build_aurora_connect_args,
    check_aurora_health,
    create_aurora_engine,
    get_aurora_database_url,
    get_aurora_db,
    get_aurora_engine,
    get_aurora_sessionmaker,
    is_aurora_enabled,
    mask_database_url,
    normalize_database_url,
    reset_aurora_engine,
    sanitize_db_error,
)
from app.config import Settings


@pytest.fixture(autouse=True)
def cleanup_aurora_singletons():
    """Ensure singleton engine and sessionmaker state are reset before and after each test."""
    reset_aurora_engine()
    yield
    reset_aurora_engine()


# ── URL Normalization & Sanitization Tests ─────────────────────────────────────

def test_normalize_database_url_postgres_scheme():
    url = "postgres://user:pass@aurora-cluster.xyz.ap-south-1.rds.amazonaws.com:5432/recondesk"
    expected = "postgresql+psycopg2://user:pass@aurora-cluster.xyz.ap-south-1.rds.amazonaws.com:5432/recondesk"
    assert normalize_database_url(url) == expected


def test_normalize_database_url_postgresql_scheme():
    url = "postgresql://user:pass@aurora-cluster.xyz.ap-south-1.rds.amazonaws.com:5432/recondesk"
    expected = "postgresql+psycopg2://user:pass@aurora-cluster.xyz.ap-south-1.rds.amazonaws.com:5432/recondesk"
    assert normalize_database_url(url) == expected


def test_normalize_database_url_already_normalized():
    url = "postgresql+psycopg2://user:pass@localhost:5432/testdb"
    assert normalize_database_url(url) == url


def test_normalize_database_url_empty_and_whitespace():
    assert normalize_database_url("") == ""
    assert normalize_database_url("   ") == ""
    assert normalize_database_url(None) == ""


def test_mask_database_url_hides_password_and_tokens():
    secret_pass = "SuperSecret_P@ss#123"
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    url = (
        f"postgresql+psycopg2://aurora_admin:{secret_pass}@aurora-cluster.xyz.rds.amazonaws.com:5432/recondesk"
        f"?token={token}&sslmode=require&secret=myAwsSecretKey"
    )
    masked = mask_database_url(url)
    assert secret_pass not in masked
    assert token not in masked
    assert "myAwsSecretKey" not in masked
    assert "aurora_admin:***@" in masked
    assert "token=***" in masked
    assert "secret=***" in masked
    assert "sslmode=require" in masked
    assert "recondesk" in masked


def test_sanitize_db_error_redacts_credentials_tokens_and_secrets():
    secret_pass = "P@ssw0rd987"
    raw_error = (
        f"OperationalError: connection to postgresql://recon_user:{secret_pass}@aurora.internal:5432/recon "
        f"failed with password='{secret_pass}' token='my-jwt-token' secret=top_secret_key"
    )
    sanitized = sanitize_db_error(raw_error)
    assert secret_pass not in sanitized
    assert "my-jwt-token" not in sanitized
    assert "top_secret_key" not in sanitized
    assert "recon_user:***@" in sanitized
    assert "password='***'" in sanitized
    assert "token='***'" in sanitized
    assert "secret=***" in sanitized


# ── Strict URL Isolation Tests (No Silent Fallback to Supabase) ────────────────

def test_get_aurora_database_url_does_not_fallback_to_supabase(monkeypatch):
    """When only DATABASE_URL (Supabase) is configured, Aurora URL must remain empty."""
    mock_settings = Settings(
        DATABASE_URL="postgres://postgres:supabase_password@db.supabase.co:5432/postgres",
        AURORA_DATABASE_URL="",
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)
    assert get_aurora_database_url() == ""


def test_get_aurora_database_url_requires_explicit_aurora_url(monkeypatch):
    mock_settings = Settings(
        DATABASE_URL="postgres://supabase_user:pass@supabase-host:5432/db",
        AURORA_DATABASE_URL="postgres://aurora_user:pass@aurora-host:5432/db",
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)
    assert get_aurora_database_url() == "postgresql+psycopg2://aurora_user:pass@aurora-host:5432/db"


def test_create_aurora_engine_missing_explicit_url_raises(monkeypatch):
    """Verify that having only DATABASE_URL does not allow create_aurora_engine() to silently connect to Supabase."""
    mock_settings = Settings(
        DATABASE_URL="postgres://supabase_user:pass@supabase-host:5432/db",
        AURORA_DATABASE_URL="",
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)
    with pytest.raises(AuroraConfigurationError) as exc_info:
        create_aurora_engine()
    assert "AURORA_DATABASE_URL is not configured" in str(exc_info.value)
    assert "Supabase" in str(exc_info.value)


# ── Configuration & Connect Arguments Tests ───────────────────────────────────

def test_build_aurora_connect_args_remote_aurora_defaults(monkeypatch):
    mock_settings = Settings(
        AURORA_CONNECT_TIMEOUT_SECONDS=8,
        AURORA_SSL_MODE=None,
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    url = "postgresql+psycopg2://admin:pass@aurora-instance.cluster-xyz.ap-south-1.rds.amazonaws.com:5432/recondesk"
    connect_args = build_aurora_connect_args(url)

    assert connect_args["connect_timeout"] == 8
    assert connect_args["sslmode"] == "require"
    assert connect_args["keepalives"] == 1
    assert connect_args["keepalives_idle"] == 30
    assert connect_args["application_name"] == "recondesk-backend"


def test_build_aurora_connect_args_localhost_no_forced_ssl(monkeypatch):
    mock_settings = Settings(AURORA_SSL_MODE=None)
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    url = "postgresql+psycopg2://local:pass@localhost:5432/local_db"
    connect_args = build_aurora_connect_args(url)
    assert "sslmode" not in connect_args


def test_build_aurora_connect_args_respects_url_sslmode(monkeypatch):
    mock_settings = Settings(AURORA_SSL_MODE="require")
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    url = "postgresql+psycopg2://admin:pass@aurora.rds.amazonaws.com:5432/recondesk?sslmode=verify-full"
    connect_args = build_aurora_connect_args(url)
    assert "sslmode" not in connect_args  # Handled natively by URL query param without conflict


def test_build_aurora_connect_args_custom_ssl_cert(monkeypatch):
    mock_settings = Settings(
        AURORA_SSL_CERT_PATH="/etc/ssl/certs/global-bundle.pem",
        AURORA_SSL_MODE="verify-ca",
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    url = "postgresql+psycopg2://admin:pass@aurora.rds.amazonaws.com:5432/recondesk"
    connect_args = build_aurora_connect_args(url)
    assert connect_args["sslmode"] == "verify-ca"
    assert connect_args["sslrootcert"] == "/etc/ssl/certs/global-bundle.pem"


# ── Conservative Pool Defaults & Overrides Tests ──────────────────────────────

def test_create_aurora_engine_conservative_defaults(monkeypatch):
    """Verify conservative development pool defaults: pool_size=2 and max_overflow=0."""
    mock_settings = Settings(
        AURORA_DATABASE_URL="postgresql+psycopg2://user:secret@aurora-host:5432/db",
        AURORA_POOL_SIZE=2,
        AURORA_MAX_OVERFLOW=0,
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        engine = create_aurora_engine()
        assert engine == mock_engine
        mock_create_engine.assert_called_once()
        _, kwargs = mock_create_engine.call_args

        assert kwargs["pool_pre_ping"] is True
        assert kwargs["pool_size"] == 2
        assert kwargs["max_overflow"] == 0


def test_create_aurora_engine_pool_overrides(monkeypatch):
    """Verify that pool settings can be explicitly overridden via create_aurora_engine kwargs."""
    mock_settings = Settings(
        AURORA_DATABASE_URL="postgresql+psycopg2://user:secret@aurora-host:5432/db",
        AURORA_POOL_SIZE=2,
        AURORA_MAX_OVERFLOW=0,
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        create_aurora_engine(pool_size=15, max_overflow=30)
        _, kwargs = mock_create_engine.call_args

        assert kwargs["pool_size"] == 15
        assert kwargs["max_overflow"] == 30


# ── Deadlock Regression & Singleton Factory Tests ─────────────────────────────

def test_get_aurora_sessionmaker_default_no_deadlock(monkeypatch):
    """Regression test: calling get_aurora_sessionmaker() without an explicit engine

    must initialize the default engine and session factory without deadlocking.
    Uses a 3-second timeout to guarantee the test suite fails promptly if a deadlock occurs.
    """
    reset_aurora_engine()
    mock_settings = Settings(
        AURORA_DATABASE_URL="postgresql+psycopg2://user:secret@aurora-host:5432/db",
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_engine = MagicMock(spec=sa.Engine)
        mock_create_engine.return_value = mock_engine

        def _init_factory():
            return get_aurora_sessionmaker()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_init_factory)
            try:
                factory = future.result(timeout=3.0)
            except concurrent.futures.TimeoutError:
                pytest.fail("Deadlock detected in get_aurora_sessionmaker() initialization!")

        assert factory is not None
        mock_create_engine.assert_called_once()
        assert get_aurora_engine() == mock_engine


def test_get_aurora_engine_singleton(monkeypatch):
    mock_settings = Settings(
        AURORA_DATABASE_URL="postgresql+psycopg2://user:secret@aurora-host:5432/db",
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        eng1 = get_aurora_engine()
        eng2 = get_aurora_engine()
        assert eng1 is eng2
        assert mock_create_engine.call_count == 1


def test_reset_aurora_engine(monkeypatch):
    mock_settings = Settings(
        AURORA_DATABASE_URL="postgresql+psycopg2://user:secret@aurora-host:5432/db",
    )
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        get_aurora_engine()
        reset_aurora_engine()
        mock_engine.dispose.assert_called_once()


def test_aurora_session_scope_success():
    mock_session = MagicMock(spec=Session)
    mock_factory = MagicMock(return_value=mock_session)

    with patch("app.aurora.get_aurora_sessionmaker", return_value=mock_factory):
        with aurora_session_scope() as session:
            assert session == mock_session

        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()
        mock_session.rollback.assert_not_called()


def test_aurora_session_scope_rollback_on_error():
    mock_session = MagicMock(spec=Session)
    mock_factory = MagicMock(return_value=mock_session)

    with patch("app.aurora.get_aurora_sessionmaker", return_value=mock_factory):
        with pytest.raises(ValueError):
            with aurora_session_scope() as session:
                raise ValueError("Operation failed inside session scope")

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()
        mock_session.commit.assert_not_called()


# ── FastAPI Route Dependency Tests ─────────────────────────────────────────────

def test_get_aurora_db_disabled_raises_503(monkeypatch):
    mock_settings = Settings(AURORA_DB_ENABLED=False)
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)
    assert not is_aurora_enabled()

    gen = get_aurora_db()
    with pytest.raises(HTTPException) as exc_info:
        next(gen)
    assert exc_info.value.status_code == 503
    assert "Aurora database layer is currently disabled" in exc_info.value.detail


def test_get_aurora_db_yields_session_when_enabled(monkeypatch):
    mock_settings = Settings(AURORA_DB_ENABLED=True)
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)
    assert is_aurora_enabled()

    mock_session = MagicMock(spec=Session)
    with patch("app.aurora.get_aurora_session", return_value=mock_session):
        gen = get_aurora_db()
        yielded_session = next(gen)
        assert yielded_session is mock_session

        # Exiting generator triggers finally block
        with pytest.raises(StopIteration):
            next(gen)
        mock_session.close.assert_called_once()


def test_get_aurora_db_rolls_back_on_route_exception(monkeypatch):
    mock_settings = Settings(AURORA_DB_ENABLED=True)
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    mock_session = MagicMock(spec=Session)
    with patch("app.aurora.get_aurora_session", return_value=mock_session):
        gen = get_aurora_db()
        next(gen)
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("Unhandled route exception"))

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


# ── Health Check Function Tests ────────────────────────────────────────────────

def test_check_aurora_health_unconfigured(monkeypatch):
    mock_settings = Settings(AURORA_DATABASE_URL="")
    monkeypatch.setattr("app.aurora.get_settings", lambda: mock_settings)

    health = check_aurora_health()
    assert health["status"] == "unconfigured"
    assert health["healthy"] is False
    assert "AURORA_DATABASE_URL is not configured" in health["message"]


def test_check_aurora_health_success():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.scalar.return_value = 1

    health = check_aurora_health(mock_engine)
    assert health["status"] == "ok"
    assert health["healthy"] is True
    assert "latency_ms" in health
    assert health["database"] == "aurora_postgresql"


def test_check_aurora_health_failure_masks_credentials():
    secret_pass = "MySecretAuroraPassword777"
    sensitive_error = f"OperationalError: password authentication failed for postgresql://admin:{secret_pass}@aurora:5432?token=xyz"

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.side_effect = Exception(sensitive_error)

    health = check_aurora_health(mock_engine)
    assert health["status"] == "error"
    assert health["healthy"] is False
    assert secret_pass not in health["error"]
    assert "xyz" not in health["error"]
    assert "admin:***@" in health["error"]


# ── Optional Live Integration Test (Strictly Read-Only) ────────────────────────

LIVE_TEST_DB_URL = os.environ.get("TEST_AURORA_DATABASE_URL", "").strip()


@pytest.mark.skipif(
    not LIVE_TEST_DB_URL,
    reason="Explicit test database URL not supplied (set TEST_AURORA_DATABASE_URL to run live integration test)",
)
def test_aurora_live_integration_connection():
    """Live integration test that runs ONLY when an explicit TEST_AURORA_DATABASE_URL is supplied in the environment.

    Strictly read-only: executes only SELECT 1 without creating, altering, inserting, updating, or deleting
    any database objects or records.
    """
    engine = create_aurora_engine(LIVE_TEST_DB_URL)
    try:
        health = check_aurora_health(engine)
        assert health["status"] == "ok"
        assert health["healthy"] is True
        assert health["latency_ms"] >= 0

        # Verify sessionmaker with read-only SELECT 1 query
        session_factory = get_aurora_sessionmaker(engine=engine)
        with session_factory() as session:
            result = session.execute(sa.text("SELECT 1")).scalar()
            assert result == 1
    finally:
        engine.dispose()
