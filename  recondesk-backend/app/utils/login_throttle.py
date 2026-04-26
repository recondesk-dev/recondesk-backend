from __future__ import annotations
import os
import time
import redis

REDIS_URL = os.environ.get("REDIS_URL")
LOGIN_LIMIT = 10
LOGIN_WINDOW = 60  # seconds

def _get_redis():
    if REDIS_URL:
        try:
            return redis.from_url(REDIS_URL, decode_responses=True)
        except Exception:
            return None
    return None

# In-memory fallback
_memory: dict[str, list[float]] = {}

def _is_rate_limited(ip: str) -> bool:
    r = _get_redis()
    key = f"login_rate:{ip}"
    now = time.time()
    if r:
        try:
            pipe = r.pipeline()
            pipe.zadd(key, {str(now): now})
            pipe.zremrangebyscore(key, 0, now - LOGIN_WINDOW)
            pipe.zcard(key)
            pipe.expire(key, LOGIN_WINDOW)
            results = pipe.execute()
            count = results[2]
            return count > LOGIN_LIMIT
        except Exception:
            pass
    # fallback to in-memory
    timestamps = _memory.get(ip, [])
    timestamps = [t for t in timestamps if now - t < LOGIN_WINDOW]
    timestamps.append(now)
    _memory[ip] = timestamps
    return len(timestamps) > LOGIN_LIMIT

def is_login_locked(ip: str) -> bool:
    return _is_rate_limited(ip)

def record_login_failure(ip: str) -> None:
    pass  # counting handled in is_login_locked

def record_login_success(ip: str) -> None:
    pass  # no need to clear on success
