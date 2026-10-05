"""Per-request context (e.g. correlation id for audit logs and distributed tracing)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
    """Inspect or assign correlation_id and inject into response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        # Check standard distributed tracing headers
        cid = (
            headers.get("x-correlation-id")
            or headers.get("x-request-id")
            or new_correlation_id()
        ).strip()
        if not cid:
            cid = new_correlation_id()

        token = correlation_id_var.set(cid)

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                resp_headers = list(message.get("headers", []))
                # Inject both X-Correlation-ID and X-Request-ID for client tracing
                cid_bytes = cid.encode("latin-1")
                resp_headers.append((b"x-correlation-id", cid_bytes))
                resp_headers.append((b"x-request-id", cid_bytes))
                message["headers"] = resp_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            correlation_id_var.reset(token)
