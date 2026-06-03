from functools import lru_cache
from typing import Any, Callable, Optional

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.config import get_settings, httpx_timeout_client

_VALID_PROFILE_ROLES = frozenset({"admin", "staff"})


@lru_cache
def get_supabase() -> Client:
    """Cached Supabase client using the service-role key (bypasses RLS)."""
    s = get_settings()
    opts = SyncClientOptions(httpx_client=httpx_timeout_client())
    return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY, options=opts)


@lru_cache
def get_supabase_anon() -> Client:
    """Cached Supabase client using the anon/public key (respects RLS)."""
    s = get_settings()
    opts = SyncClientOptions(httpx_client=httpx_timeout_client())
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
    """Return a normalized role; infer admin vs staff when missing or invalid."""
    role = str(raw_role or "").strip().lower()
    if role in _VALID_PROFILE_ROLES:
        return role
    sb = client or get_supabase()
    if _is_invited_user(sb, user_id=user_id, email=email):
        return "staff"
    return "admin"


def get_user_profile(user_id: str) -> Optional[dict]:
    """Fetch a single row from *user_profiles* by primary key.

    Returns the row dict, or None if not found / on error.
    Missing or invalid *role* values are resolved and persisted when possible.
    """
    try:
        client = get_supabase()
        result = (
            client.table("user_profiles")
            .select(_USER_PROFILE_SELECT)
            .eq("id", user_id)
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
        if str(raw_role or "").strip().lower() not in _VALID_PROFILE_ROLES:
            try:
                client.table("user_profiles").update({"role": resolved}).eq(
                    "id", user_id
                ).execute()
            except Exception:
                pass
        return profile
    except Exception:
        return None
