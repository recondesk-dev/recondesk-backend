from functools import lru_cache
from typing import Any, Callable, Optional

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.config import get_settings, httpx_timeout_client


@lru_cache
def get_supabase() -> Client:
    """Cached Supabase client using the service-role key (bypasses RLS)."""
    s = get_settings()
    opts = SyncClientOptions(
        httpx_client=httpx_timeout_client(),
        postgrest_client_timeout=120
    )
    return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY, options=opts)


@lru_cache
def get_supabase_anon() -> Client:
    """Cached Supabase client using the anon/public key (respects RLS)."""
    s = get_settings()
    opts = SyncClientOptions(
        httpx_client=httpx_timeout_client(),
        postgrest_client_timeout=120
    )
    return create_client(s.SUPABASE_URL, s.SUPABASE_ANON_KEY, options=opts)


def supabase_client() -> Client:
    """FastAPI dependency: returns the service-role Supabase client."""
    return get_supabase()


def get_db() -> Client:
    """FastAPI dependency: returns the service-role Supabase client."""
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
    client: Client,
    *,
    user_id: str,
    email: str | None,
) -> bool:
    """True when the user joined via a team invite (accepted or pending)."""
    uid = (user_id or "").strip()
    em = (email or "").strip().lower()
    try:
        if uid:
            member = (
                client.table("team_members")
                .select("id")
                .eq("member_user_id", uid)
                .limit(1)
                .execute()
            )
            if member.data:
                return True
        if em:
            invite = (
                client.table("team_members")
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
    raw_role: Any,
    *,
    user_id: str,
    email: str | None,
    client: Client | None = None,
) -> str:
    """Return canonical role: staff if invited, otherwise admin (workspace owner)."""
    del raw_role  # stored value may be wrong; always derive from invite status
    sb = client or get_supabase()
    if _is_invited_user(sb, user_id=user_id, email=email):
        return "staff"
    return "admin"


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
        if res.data and len(res.data) > 0:
            return res.data[0]
        return get_user_profile(uid) or insert_payload
    except Exception:
        return get_user_profile(uid) or insert_payload
