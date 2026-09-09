"""Shared limiter instance - imported by routers."""
from __future__ import annotations
from slowapi import Limiter
from slowapi.util import get_remote_address
import os


def get_real_ip(request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


redis_url = os.environ.get("REDIS_URL", None)

if redis_url:
    limiter = Limiter(key_func=get_real_ip, storage_uri=redis_url)
else:
    limiter = Limiter(key_func=get_real_ip)
