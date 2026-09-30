"""Reusable FastAPI dependencies (re-exports + role checks)."""

from app.auth import (  # noqa: F401
    get_current_active_user,
    get_current_user,
    get_current_user_id,
    get_user_role,
    require_admin,
    require_role,
)
from app.aurora import (  # noqa: F401
    check_aurora_health,
    get_aurora_db,
    is_aurora_enabled,
)
