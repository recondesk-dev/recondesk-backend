from functools import lru_cache
from typing import Any, Callable, Optional

from supabase import Client, create_client

from app.config import settings


@lru_cache
def get_supabase() -> Client:
    """Cached Supabase client using the service-role key (bypasses RLS)."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


@lru_cache
def get_supabase_anon() -> Client:
    """Cached Supabase client using the anon/public key (respects RLS)."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


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


def get_user_profile(user_id: str) -> Optional[dict]:
    """Fetch a single row from *user_profiles* by primary key.

    Returns the row dict, or None if not found / on error.
    """
    try:
        client = get_supabase()
        result = (
            client.table("user_profiles")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return result.data
    except Exception:
        return None
