"""AWS Aurora PostgreSQL database connection layer for ReconDesk.

Initial migration layer providing:
- SQLAlchemy 2.x engine configured for AWS Aurora (with psycopg2)
- Resilient connection pooling with pool_pre_ping and connection recycling
- Conservative development pool defaults (pool_size=2, max_overflow=0)
- Configurable SSL and TCP keepalive suitable for Aurora clusters
- Reentrant, deadlock-free sessionmaker and Session factory
- Strict isolation: requires explicit AURORA_DATABASE_URL to avoid connecting to Supabase
- Safe FastAPI route dependency (`get_aurora_db`) guarded by `AURORA_DB_ENABLED`
- Safe read-only health check (`check_aurora_health`) executing `SELECT 1` without credential exposure
"""

from __future__ import annotations

import logging
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Generator, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, status
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import get_settings

_log = logging.getLogger("recondesk.aurora")

# Reentrant lock for thread-safe singleton initialization (prevents self-deadlock)
_lock = threading.RLock()
_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


class AuroraDatabaseError(Exception):
    """Base exception for Aurora database operations."""


class AuroraDisabledError(AuroraDatabaseError):
    """Raised when Aurora DB operations are requested while Aurora is disabled."""


class AuroraConfigurationError(AuroraDatabaseError):
    """Raised when Aurora connection configuration is missing or invalid."""


class AuroraConnectionError(AuroraDatabaseError):
    """Raised when establishing a connection to Aurora fails."""


def normalize_database_url(url: str) -> str:
    """Ensure database URL uses postgresql+psycopg2 scheme compatible with SQLAlchemy 2.x."""
    trimmed = (url or "").strip().strip('"').strip("'")
    if not trimmed:
        return ""
    if trimmed.startswith("postgres://"):
        return "postgresql+psycopg2://" + trimmed[len("postgres://"):]
    if trimmed.startswith("postgresql://") and not trimmed.startswith("postgresql+"):
        return "postgresql+psycopg2://" + trimmed[len("postgresql://"):]
    return trimmed


def mask_database_url(url: str) -> str:
    """Safely mask user passwords and sensitive query tokens in database URLs for logging and diagnostics."""
    trimmed = (url or "").strip()
    if not trimmed:
        return ""
    try:
        u = make_url(trimmed)
        masked = u.render_as_string(hide_password=True)
    except Exception:
        masked = re.sub(
            r"://([^/:\s]+):(.+?)@([a-zA-Z0-9.\-_\[\]]+(?::\d+)?(?:[/?\s]|$))",
            r"://\1:***@\3",
            trimmed,
        )
    # Redact any sensitive query parameters (e.g., token, secret, password)
    masked = re.sub(
        r"([?&](?:password|token|secret|key|api_key|X-Amz-Security-Token|auth)=)[^&]+",
        r"\1***",
        masked,
        flags=re.IGNORECASE,
    )
    return masked


def sanitize_db_error(msg: str) -> str:
    """Strip out any sensitive credentials, URLs with passwords, or secret tokens from error strings."""
    if not msg:
        return "Database operation error"
    # Redact ://user:password@host (handles passwords containing @, special chars, and query strings)
    sanitized = re.sub(
        r"://([^/:\s]+):(.+?)@([a-zA-Z0-9.\-_\[\]]+(?::\d+)?(?:[/?\s]|$))",
        r"://\1:***@\3",
        msg,
    )
    # Redact quoted password parameter: password='...' or password="..."
    sanitized = re.sub(
        r"password\s*=\s*([\'\"]).*?\1",
        r"password=\1***\1",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Redact unquoted password parameter: password=value
    sanitized = re.sub(
        r"password\s*=\s*(?!\'{3}|\"{3}|[\'\"]\*\*\*[\'\"])(?![\'\"])\S+",
        r"password=***",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Redact token parameter: token='...' or token=value
    sanitized = re.sub(
        r"(token\s*=\s*['\"]).*?(['\"])",
        r"\1***\2",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(token\s*=\s*)(?!\'{3}|\"{3}|[\'\"]\*\*\*[\'\"])(?![\'\"])\S+",
        r"token=***",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Redact secret / key params
    sanitized = re.sub(
        r"(secret\s*=\s*['\"]).*?(['\"])",
        r"\1***\2",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(secret\s*=\s*)(?!\'{3}|\"{3}|[\'\"]\*\*\*[\'\"])(?![\'\"])\S+",
        r"secret=***",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Redact sensitive query parameters in embedded URLs
    sanitized = re.sub(
        r"([?&](?:password|token|secret|key|api_key|X-Amz-Security-Token|auth)=)[^&\s]+",
        r"\1***",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def is_aurora_enabled() -> bool:
    """Return whether the Aurora database layer is enabled for application use."""
    return bool(get_settings().AURORA_DB_ENABLED)


def get_aurora_database_url() -> str:
    """Retrieve the explicit database URL for Aurora.

    Requires an explicit AURORA_DATABASE_URL (or AURORA_DB_URL).
    Does not fallback to DATABASE_URL to avoid accidentally connecting to Supabase.
    """
    s = get_settings()
    raw = (s.AURORA_DATABASE_URL or "").strip()
    return normalize_database_url(raw)


def build_aurora_connect_args(url: str) -> dict[str, Any]:
    """Construct psycopg2 connect_args suitable for AWS Aurora PostgreSQL.

    Configures:
    - Connection timeout (to prevent hung connection attempts)
    - SSL mode suitable for Aurora clusters (defaulting to 'require' for remote hosts)
    - TCP keepalives (to prevent idle connections being severed across AWS NAT/ALB)
    - Application name for connection identification in pg_stat_activity
    """
    connect_args: dict[str, Any] = {}
    if not url:
        return connect_args

    s = get_settings()

    # Determine backend dialect / scheme
    scheme = url.split("://")[0] if "://" in url else ""
    if not ("postgres" in scheme or "psycopg2" in scheme):
        # Non-postgres dialect (e.g. sqlite in lightweight tests), skip psycopg2-specific connect_args
        return connect_args

    # Check query string in URL
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    # 1. Connection timeout
    connect_args["connect_timeout"] = max(1, int(s.AURORA_CONNECT_TIMEOUT_SECONDS))

    # 2. SSL mode suitable for Aurora
    # If the URL already specifies sslmode in query params, respect it
    if "sslmode" not in query_params:
        if s.AURORA_SSL_MODE:
            connect_args["sslmode"] = s.AURORA_SSL_MODE.strip()
        else:
            host = (parsed.hostname or "").lower()
            if host in ("localhost", "127.0.0.1", ""):
                # Local dev without SSL
                pass
            else:
                # AWS Aurora clusters require SSL
                connect_args["sslmode"] = "require"

    if s.AURORA_SSL_CERT_PATH and "sslrootcert" not in query_params:
        connect_args["sslrootcert"] = s.AURORA_SSL_CERT_PATH.strip()

    # 3. TCP keepalives to prevent AWS NAT/firewall silent connection drops (standard AWS Aurora tuning)
    connect_args["keepalives"] = 1
    connect_args["keepalives_idle"] = 30
    connect_args["keepalives_interval"] = 10
    connect_args["keepalives_count"] = 5

    # 4. Application name for pg_stat_activity observability
    connect_args["application_name"] = "recondesk-backend"

    return connect_args


def create_aurora_engine(
    db_url: Optional[str] = None,
    *,
    pool_size: Optional[int] = None,
    max_overflow: Optional[int] = None,
    pool_recycle: Optional[int] = None,
    pool_timeout: Optional[int] = None,
    echo: bool = False,
    **kwargs: Any,
) -> Engine:
    """Create a new SQLAlchemy 2.x Engine configured for AWS Aurora PostgreSQL.

    Configured with:
    - pool_pre_ping=True (recovers gracefully from Aurora failover or broken sockets)
    - Connection recycling (to re-resolve DNS during cluster failover and avoid stale connections)
    - Conservative development pool defaults (pool_size=2, max_overflow=0)
    - Proper acquisition timeouts
    """
    target_url = normalize_database_url(db_url) if db_url else get_aurora_database_url()
    if not target_url:
        raise AuroraConfigurationError(
            "AURORA_DATABASE_URL is not configured. An explicit Aurora connection string "
            "is required to prevent accidental connection to Supabase."
        )

    s = get_settings()
    c_args = build_aurora_connect_args(target_url)

    # Allow custom connect_args override from kwargs
    if "connect_args" in kwargs:
        merged_connect_args = {**c_args, **kwargs.pop("connect_args")}
    else:
        merged_connect_args = c_args

    p_size = pool_size if pool_size is not None else s.AURORA_POOL_SIZE
    p_overflow = max_overflow if max_overflow is not None else s.AURORA_MAX_OVERFLOW
    p_recycle = pool_recycle if pool_recycle is not None else s.AURORA_POOL_RECYCLE_SECONDS
    p_timeout = pool_timeout if pool_timeout is not None else s.AURORA_POOL_TIMEOUT_SECONDS

    # Handle SQLite or mock URLs that don't support QueuePool sizing
    engine_kwargs: dict[str, Any] = {
        "echo": echo,
        "pool_pre_ping": True,
        **kwargs,
    }
    if merged_connect_args:
        engine_kwargs["connect_args"] = merged_connect_args

    if not target_url.startswith("sqlite"):
        engine_kwargs.update({
            "poolclass": QueuePool,
            "pool_size": p_size,
            "max_overflow": p_overflow,
            "pool_recycle": p_recycle,
            "pool_timeout": p_timeout,
        })

    _log.info(
        "Initializing Aurora database engine for %s (pool_pre_ping=True, pool_size=%s, overflow=%s, recycle=%ss)",
        mask_database_url(target_url),
        p_size,
        p_overflow,
        p_recycle,
    )

    try:
        return sa.create_engine(target_url, **engine_kwargs)
    except Exception as exc:
        sanitized = sanitize_db_error(str(exc))
        _log.error("Failed to initialize Aurora engine: %s", sanitized)
        raise AuroraConnectionError(f"Failed to create Aurora engine: {sanitized}") from None


def get_aurora_engine() -> Engine:
    """Return the cached singleton Aurora SQLAlchemy Engine, initializing lazily."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = create_aurora_engine()
    return _engine


def get_aurora_sessionmaker(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Return a sessionmaker factory bound to the Aurora engine or a specified engine.

    Thread-safe and reentrant; avoids lock contention by resolving the engine before
    allocating the session factory.
    """
    global _session_factory
    if engine is not None:
        return sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    if _session_factory is None:
        # First ensure engine is initialized (it manages its own lock safely)
        target_engine = get_aurora_engine()
        with _lock:
            if _session_factory is None:
                _session_factory = sessionmaker(
                    bind=target_engine,
                    autoflush=False,
                    expire_on_commit=False,
                    class_=Session,
                )
    return _session_factory


def get_aurora_session() -> Session:
    """Create a new SQLAlchemy Session against Aurora."""
    return get_aurora_sessionmaker()()


def reset_aurora_engine() -> None:
    """Dispose the current engine and clear session factories (used in tests and config reloads)."""
    global _engine, _session_factory
    with _lock:
        if _engine is not None:
            try:
                _engine.dispose()
            except Exception:
                pass
            _engine = None
        _session_factory = None


@contextmanager
def aurora_session_scope() -> Generator[Session, None, None]:
    """Transactional context manager for background tasks, scripts, and standalone workers.

    Commits on successful completion, rolls back on exception, and ensures session closure.
    """
    session = get_aurora_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_aurora_db() -> Generator[Session, None, None]:
    """FastAPI route dependency yielding a scoped SQLAlchemy session for Aurora.

    Safety:
    - Disabled by default: if AURORA_DB_ENABLED is not set, raises 503.
    - Rolls back on unhandled exceptions and guarantees session close in `finally`.
    """
    if not is_aurora_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Aurora database layer is currently disabled. Enable AURORA_DB_ENABLED for development testing.",
        )

    db = get_aurora_session()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_aurora_health(
    engine: Optional[Engine] = None,
    *,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Execute a read-only SELECT 1 health check against Aurora without exposing credentials.

    Returns a structured status dictionary:
    - On success: {"status": "ok", "healthy": True, "latency_ms": 1.23, "database": "aurora_postgresql"}
    - When unconfigured: {"status": "unconfigured", "healthy": False, "message": "...", "database": "aurora_postgresql"}
    - On connection failure: {"status": "error", "healthy": False, "error": "<sanitized error>", "latency_ms": ..., "database": "aurora_postgresql"}
    """
    del timeout  # Socket/connect_timeout handles network deadlines; parameter kept for interface consistency
    target_engine = engine
    if target_engine is None:
        url = get_aurora_database_url()
        if not url:
            return {
                "status": "unconfigured",
                "healthy": False,
                "message": (
                    "AURORA_DATABASE_URL is not configured. An explicit Aurora connection string "
                    "is required to avoid connecting to Supabase."
                ),
                "database": "aurora_postgresql",
            }
        try:
            target_engine = get_aurora_engine()
        except Exception as exc:
            return {
                "status": "error",
                "healthy": False,
                "error": sanitize_db_error(str(exc)),
                "database": "aurora_postgresql",
            }

    start = time.perf_counter()
    try:
        with target_engine.connect() as conn:
            res = conn.execute(sa.text("SELECT 1")).scalar()
            if res != 1:
                raise RuntimeError(f"Unexpected query response: {res}")

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": "ok",
            "healthy": True,
            "latency_ms": elapsed_ms,
            "database": "aurora_postgresql",
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        sanitized = sanitize_db_error(str(exc))
        _log.warning("Aurora health check probe failed: %s", sanitized)
        return {
            "status": "error",
            "healthy": False,
            "error": sanitized,
            "latency_ms": elapsed_ms,
            "database": "aurora_postgresql",
        }


def set_aurora_session_context(
    session: Session,
    *,
    user_id: Optional[Any] = None,
    firm_owner_id: Optional[Any] = None,
    role: Optional[str] = None,
) -> None:
    """Set transaction-local authorization context for an Aurora PostgreSQL session.

    Uses PostgreSQL transaction-local semantics (SET LOCAL / set_config(..., is_local=true)):
      - app.current_user_id: canonical ReconDesk user_profiles.id
      - app.current_firm_owner_id: canonical ReconDesk firm_owner_id
      - app.current_user_role: canonical user role (e.g. 'admin', 'staff')

    Guarantees:
      - Bound to the current transaction. When transaction commits or rolls back,
        PostgreSQL automatically discards the setting (no pool leakage).
      - Thread-safe and session-isolated.
      - Safely handles UUID values and strings.
      - Graceful handling for non-PostgreSQL dialects (e.g. SQLite test fixtures).
    """
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    str_uid = str(user_id).strip() if user_id is not None else None
    str_foid = str(firm_owner_id).strip() if firm_owner_id is not None else None
    str_role = str(role).strip().lower() if role is not None else None

    if dialect_name == "postgresql":
        if str_uid is not None:
            session.execute(
                sa.text("SELECT set_config('app.current_user_id', :val, true)"),
                {"val": str_uid},
            )
        if str_foid is not None:
            session.execute(
                sa.text("SELECT set_config('app.current_firm_owner_id', :val, true)"),
                {"val": str_foid},
            )
        if str_role is not None:
            session.execute(
                sa.text("SELECT set_config('app.current_user_role', :val, true)"),
                {"val": str_role},
            )
    else:
        # Test-only fallback for SQLite / non-PostgreSQL dialects
        ctx_map: dict[str, Optional[str]] = session.info.setdefault("aurora_context", {})
        if str_uid is not None:
            ctx_map["user_id"] = str_uid
        if str_foid is not None:
            ctx_map["firm_owner_id"] = str_foid
        if str_role is not None:
            ctx_map["role"] = str_role


def get_aurora_session_context(session: Session) -> dict[str, Optional[str]]:
    """Retrieve the current transaction authorization context from the Aurora session."""
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "postgresql":
        try:
            row = session.execute(
                sa.text("""
                    SELECT
                        current_setting('app.current_user_id', true) AS user_id,
                        current_setting('app.current_firm_owner_id', true) AS firm_owner_id,
                        current_setting('app.current_user_role', true) AS role
                """)
            ).mappings().first()
            if row:
                return {
                    "user_id": row.get("user_id") or None,
                    "firm_owner_id": row.get("firm_owner_id") or None,
                    "role": row.get("role") or None,
                }
        except Exception as exc:
            _log.warning("Failed to query PostgreSQL session context: %s", type(exc).__name__)
        return {
            "user_id": None,
            "firm_owner_id": None,
            "role": None,
        }

    # Test-only fallback for SQLite / non-PostgreSQL dialects
    ctx_map = session.info.get("aurora_context", {})
    return {
        "user_id": ctx_map.get("user_id"),
        "firm_owner_id": ctx_map.get("firm_owner_id"),
        "role": ctx_map.get("role"),
    }


def clear_aurora_session_context(session: Session) -> None:
    """Clear transaction-local authorization context from the Aurora session."""
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    session.info.pop("aurora_context", None)

    if dialect_name == "postgresql":
        try:
            session.execute(
                sa.text("""
                    SELECT
                        set_config('app.current_user_id', '', true),
                        set_config('app.current_firm_owner_id', '', true),
                        set_config('app.current_user_role', '', true)
                """)
            )
        except Exception:
            pass


@sa.event.listens_for(Session, "after_transaction_end")
def _clear_session_info_aurora_context(session: Session, transaction: Any) -> None:
    """Ensure test-only session.info context does not leak across transactions."""
    if getattr(transaction, "parent", None) is None:
        session.info.pop("aurora_context", None)
