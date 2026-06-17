"""Reject oversized JSON bodies and overly nested JSON (non-multipart)."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.utils.errors import error_response

_MAX_BYTES = 1 * 1024 * 1024
_MAX_DEPTH = 10


def _max_json_depth(value: Any, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        return depth
    if isinstance(value, dict):
        m = depth
        for v in value.values():
            m = max(m, _max_json_depth(v, depth + 1))
        return m
    if isinstance(value, list):
        m = depth
        for v in value:
            m = max(m, _max_json_depth(v, depth + 1))
        return m
    return depth


class BodySizeJsonDepthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return
        headers = {
            (k[0].decode() if isinstance(k[0], bytes) else k[0]).lower(): (
                k[1].decode() if isinstance(k[1], bytes) else k[1]
            )
            for k in scope.get("headers", [])
        }
        ct = (headers.get("content-type") or "").lower()
        if "multipart/form-data" in ct or "application/octet-stream" in ct:
            await self.app(scope, receive, send)
            return

        body = b""
        more = True
        while more:
            message: Message = await receive()
            if message["type"] != "http.request":
                more = False
                break
            body += message.get("body", b"")
            more = bool(message.get("more_body", False))
            if len(body) > _MAX_BYTES + 1:
                resp = error_response(413, "Request body too large (max 1MB)")
                await resp(scope, receive, send)
                return

        if len(body) > _MAX_BYTES:
            resp = error_response(413, "Request body too large (max 1MB)")
            await resp(scope, receive, send)
            return

        if body and "application/json" in ct:
            try:
                obj = json.loads(body)
            except json.JSONDecodeError:
                resp = error_response(400, "Invalid JSON in request body")
                await resp(scope, receive, send)
                return
            if _max_json_depth(obj) > _MAX_DEPTH:
                resp = error_response(400, "JSON nesting exceeds maximum depth")
                await resp(scope, receive, send)
                return

        async def new_receive() -> Message:
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, new_receive, send)


class SecurityHeadersMiddleware:
    """HSTS, nosniff, frame deny, XSS, Referrer-Policy (every response)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = list(message.get("headers", []))
                extra = [
                    (
                        b"strict-transport-security",
                        b"max-age=31536000; includeSubDomains",
                    ),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"x-xss-protection", b"1; mode=block"),
                    (
                        b"referrer-policy",
                        b"strict-origin-when-cross-origin",
                    ),
                ]
                for pair in extra:
                    if not any(
                        (x[0] or b"").lower() == pair[0].lower() for x in h
                    ):
                        h.append(pair)
                message = {**message, "headers": h}
            await send(message)

        await self.app(scope, receive, send_with_headers)
