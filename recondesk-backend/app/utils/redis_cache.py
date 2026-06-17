from __future__ import annotations

import json
import logging
from typing import Any, Optional
import redis

from app.config import settings

_log = logging.getLogger(__name__)

# Cache client connection cached at module level
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> Optional[redis.Redis]:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_URL:
        return None
    try:
        # decode_responses=True ensures we read string values instead of bytes
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return _redis_client
    except Exception as exc:
        _log.warning("Failed to connect to Redis at %s: %s", settings.REDIS_URL, exc)
        return None


def cache_get(key: str) -> Optional[Any]:
    r = get_redis_client()
    if not r:
        return None
    try:
        val = r.get(key)
        if val is not None:
            return json.loads(val)
    except Exception as exc:
        _log.warning("Redis get error for key %s: %s", key, exc)
    return None


def cache_set(key: str, value: Any, ttl_seconds: int = 30) -> bool:
    r = get_redis_client()
    if not r:
        return False
    try:
        r.set(key, json.dumps(value), ex=ttl_seconds)
        return True
    except Exception as exc:
        _log.warning("Redis set error for key %s: %s", key, exc)
    return False


def cache_delete(key: str) -> bool:
    r = get_redis_client()
    if not r:
        return False
    try:
        r.delete(key)
        return True
    except Exception as exc:
        _log.warning("Redis delete error for key %s: %s", key, exc)
    return False


def cache_delete_pattern(pattern: str) -> bool:
    r = get_redis_client()
    if not r:
        return False
    try:
        keys = list(r.scan_iter(match=pattern))
        if keys:
            r.delete(*keys)
        return True
    except Exception as exc:
        _log.warning("Redis delete pattern error for pattern %s: %s", pattern, exc)
    return False


def invalidate_user_dashboard(user_id: str) -> None:
    """Clear cached dashboard runs and billing status for a specific user."""
    uid = str(user_id).strip()
    if uid:
        cache_delete_pattern(f"cache:runs:{uid}:*")
        cache_delete(f"cache:billing_status:{uid}")
