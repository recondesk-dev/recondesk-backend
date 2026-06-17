"""Per-request context (e.g. correlation id for audit logs)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

from starlette.types import ASGIApp, Receive, Scope, Send

correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def get_correlation_id() -> str:
    c = correlation_id_var.get()
    if c is None:
        c = new_correlation_id()
        correlation_id_var.set(c)
    return c


class CorrelationIdMiddleware:
    """Assign a correlation_id for the request; expose via context var."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = correlation_id_var.set(new_correlation_id())
        try:
            await self.app(scope, receive, send)
        finally:
            correlation_id_var.reset(token)
