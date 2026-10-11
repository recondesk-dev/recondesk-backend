from functools import lru_cache
from typing import Any, Callable, Optional

try:
    from supabase import Client
except ImportError:
    Client = Any  # type: ignore[misc,assignment]

from app.config import get_settings


@lru_cache
def get_supabase() -> Any:
    """Authoritative database client: returns AuroraClient (AWS Aurora PostgreSQL)."""
    from app.aurora_client import AuroraClient
    return AuroraClient()


@lru_cache
def get_supabase_anon() -> Any:
    """Authoritative database client: returns AuroraClient (AWS Aurora PostgreSQL)."""
    from app.aurora_client import AuroraClient
    return AuroraClient()


def supabase_client() -> Any:
    """FastAPI dependency: returns the database client (AuroraClient or Supabase)."""
    return get_supabase()


def get_db() -> Any:
    """FastAPI dependency: returns the database client (AuroraClient or Supabase)."""
    return get_supabase()


def run_query(table: str, query_fn: Callable) -> Any:
    """Execute *query_fn* against *table* and return the response data.

    query_fn receives a Supabase table builder and should return
    the final builder (before .execute() is called).
    """
    try:
        client = get_supabase()
        builder = client.table(table)
        result = query_fn(builder).execute()
        return result.data
    except Exception as exc:
        raise exc


# Columns that exist in production; avoid select('*') so missing optional columns
# are never required by PostgREST.
_USER_PROFILE_SELECT = (
    "id, email, full_name, firm_name, phone, role, is_active, "
    "plan, runs_used, runs_limit, created_at, free_runs_remaining, runs_balance, firm_city, "
    "icai_membership_number, firm_gstin, onboarding_completed"
)

# Optional billing columns — fetched separately so missing migrations cannot break auth.
_USER_PROFILE_SUBSCRIPTION_SELECT = "gstin_limit, subscription_ends_at"


def _is_invited_user(
    client: Any = None,
    *,
    user_id: Optional[str] = None,
    email: str | None = None,
) -> bool:
    """True when the user joined via a team invite (accepted or pending)."""
    # Support calling as _is_invited_user(user_id)
    if user_id is None and isinstance(client, str):
        user_id = client
        client = None

    uid = (user_id or "").strip()
    em = (email or "").strip().lower()

    # 1. Phase 3C: Try Aurora tenancy repository first
    if uid:
        try:
            from app.repositories.tenancy import get_tenancy_repository
            repo = get_tenancy_repository()
            if repo is not None:
                tm = repo.get_team_membership(uid)
                if tm is not None:
                    return True
        except Exception:
            pass

    # 2. Supabase fallback
    sb = client or get_supabase()
    try:
        if uid:
            member = (
                sb.table("team_members")
                .select("id")
                .eq("member_user_id", uid)
                .limit(1)
                .execute()
            )
            if member.data:
                return True
        if em:
            invite = (
                sb.table("team_members")
                .select("id")
                .eq("invited_email", em)
                .limit(1)
                .execute()
            )
            if invite.data:
                return True
    except Exception:
        pass
    return False


def resolve_user_role(
    raw_role: Any = None,
    *,
    user_id: Optional[str] = None,
    email: str | None = None,
    client: Client | None = None,
) -> str:
    """Return canonical role with fail-closed security guarantees."""
    from app.models.roles import ALL_ROLES, DEFAULT_FAIL_CLOSED_ROLE, normalize_role

    if raw_role and isinstance(raw_role, str) and raw_role.strip().lower() in ALL_ROLES:
        return normalize_role(raw_role)

    target_uid = str(user_id or "").strip()

    # 1. Try Aurora tenancy repository
    if target_uid:
        try:
            from app.repositories.tenancy import get_tenancy_repository
            repo = get_tenancy_repository()
            if repo is not None:
                aurora_role = repo.get_user_role(target_uid)
                if aurora_role is not None:
                    return normalize_role(aurora_role)
        except Exception:
            pass

    # 2. Supabase team membership resolution
    sb = client or get_supabase()
    if target_uid:
        try:
            tm = (
                sb.table("team_members")
                .select("role")
                .eq("member_user_id", target_uid)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if tm.data and tm.data[0].get("role"):
                return normalize_role(tm.data[0]["role"])
        except Exception:
            pass

    if _is_invited_user(sb, user_id=target_uid, email=email):
        return "staff"


    # Check if user owns active clients (firm owner anchor)
    if target_uid:
        try:
            c = (
                sb.table("client_gstins")
                .select("id")
                .eq("firm_owner_id", target_uid)
                .limit(1)
                .execute()
            )
            if c.data:
                return "owner"
        except Exception:
            pass

    # FAIL CLOSED: Default strictly to viewer for unassigned / unknown accounts
    return DEFAULT_FAIL_CLOSED_ROLE


def get_user_profile(user_id: str) -> Optional[dict]:
    """Fetch a single row from *user_profiles* by primary key.

    Phase 3B Dual-Read:
    1. If Aurora tenancy repository is configured and returns a profile, return it.
    2. If Aurora is disabled, unavailable, or the profile is missing in Aurora,
       safely fall back to the established Supabase implementation.
    """
    uid = str(user_id or "").strip()
    if not uid:
        return None

    # 1. Attempt Aurora tenancy read
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            aurora_prof = repo.get_user_profile(uid)
            if aurora_prof is not None:
                return aurora_prof
    except Exception:
        # Aurora infrastructure failure: fall through to established Supabase path
        pass

    # 2. Established Supabase query
    try:
        client = get_supabase()
        result = (
            client.table("user_profiles")
            .select(_USER_PROFILE_SELECT)
            .eq("id", uid)
            .single()
            .execute()
        )
        profile = result.data
        if profile is None:
            return None
        raw_role = profile.get("role")
        resolved = resolve_user_role(
            raw_role,
            user_id=user_id,
            email=profile.get("email"),
            client=client,
        )
        profile["role"] = resolved
        stored = str(raw_role or "").strip().lower()
        if stored != resolved:
            try:
                client.table("user_profiles").update({"role": resolved}).eq(
                    "id", user_id
                ).execute()
                from app.services.tenancy_sync import mirror_user_profile_update_to_aurora
                mirror_user_profile_update_to_aurora(user_id, {"role": resolved})
            except Exception:
                pass
        # Optional column (alembic 20260714). Fail soft if migration not applied yet.
        try:
            thr = (
                client.table("user_profiles")
                .select("auto_approve_confidence_threshold")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            if thr.data:
                raw_thr = thr.data[0].get("auto_approve_confidence_threshold")
                if raw_thr is not None:
                    profile["auto_approve_confidence_threshold"] = int(raw_thr)
                else:
                    profile["auto_approve_confidence_threshold"] = 95
            else:
                profile["auto_approve_confidence_threshold"] = 95
        except Exception:
            profile["auto_approve_confidence_threshold"] = 95

        # Optional GSTIN subscription columns. Fail soft if migration not applied yet.
        try:
            sub = (
                client.table("user_profiles")
                .select(_USER_PROFILE_SUBSCRIPTION_SELECT)
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            if sub.data:
                row = sub.data[0]
                if row.get("gstin_limit") is not None:
                    profile["gstin_limit"] = int(row["gstin_limit"])
                if "subscription_ends_at" in row:
                    profile["subscription_ends_at"] = row.get("subscription_ends_at")
        except Exception:
            pass

        return profile
    except Exception:
        return None


def ensure_user_profile(
    user_id: str,
    *,
    client: Client | None = None,
) -> dict:
    """Ensure a user_profiles row exists for user_id; auto-create from auth.users if missing."""
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id cannot be empty")

    profile = get_user_profile(uid)
    if profile is not None:
        try:
            from app.services.tenancy_sync import mirror_user_profile_upsert_to_aurora
            mirror_user_profile_upsert_to_aurora(profile, uid)
        except Exception:
            pass
        return profile

    sb = client or get_supabase()
    email = None
    try:
        auth_user = sb.auth.admin.get_user_by_id(uid)
        if auth_user and getattr(auth_user, "user", None):
            email = getattr(auth_user.user, "email", None)
    except Exception:
        email = None

    role = resolve_user_role(None, user_id=uid, email=email, client=sb)

    insert_payload = {
        "id": uid,
        "email": email,
        "role": role,
        "is_active": True,
    }

    try:
        res = sb.table("user_profiles").insert(insert_payload).execute()
        from app.services.tenancy_sync import mirror_user_profile_upsert_to_aurora
        created = res.data[0] if (res.data and len(res.data) > 0) else insert_payload
        mirror_user_profile_upsert_to_aurora(created, uid)
        if res.data and len(res.data) > 0:
            return res.data[0]
        return get_user_profile(uid) or insert_payload
    except Exception:
        fallback = get_user_profile(uid) or insert_payload
        try:
            from app.services.tenancy_sync import mirror_user_profile_upsert_to_aurora
            mirror_user_profile_upsert_to_aurora(fallback, uid)
        except Exception:
            pass
        return fallback
