"""Redact secrets that must never appear in logs or Sentry.

Sandbox File GSTR-1 puts EVC OTP (and PAN) on the **query string**:
``POST .../gstr-1/{year}/{month}/file?pan=...&otp=...``

httpx exceptions and careless ``params=`` logging would otherwise persist
those values. Use these helpers in ``sandbox_filing_client`` and in Sentry
``before_send``.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query keys scrubbed wherever a full URL or param dict might be recorded.
SENSITIVE_QUERY_KEYS = frozenset({
    "otp",
    "evc_otp",
    "evcotp",
    "pan",  # authorized-signatory PAN on File / EVC calls
})


def scrub_query_params(
    params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a copy of ``params`` with sensitive values replaced by ``[REDACTED]``."""
    if not params:
        return {}
    out: dict[str, Any] = {}
    for key, value in params.items():
        if str(key).strip().lower() in SENSITIVE_QUERY_KEYS:
            out[key] = "[REDACTED]"
        else:
            out[key] = value
    return out


def scrub_url(url: str | None) -> str:
    """Strip/redact sensitive query keys from a URL string."""
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.query:
        return url
    scrubbed = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.strip().lower() in SENSITIVE_QUERY_KEYS:
            scrubbed.append((key, "[REDACTED]"))
        else:
            scrubbed.append((key, value))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(scrubbed), parts.fragment)
    )


def safe_httpx_error_text(exc: BaseException) -> str:
    """Stringify an httpx error without leaking File ``otp``/``pan`` query values.

    ``httpx.HTTPStatusError`` / ``RequestError`` include ``request.url`` (with
    query) in ``str(exc)``. Prefer this over ``str(exc)`` or ``repr(exc)`` in
    logs and exception messages that may reach Sentry.
    """
    request = getattr(exc, "request", None)
    response = getattr(exc, "response", None)
    if request is not None:
        method = getattr(request, "method", "?")
        raw_url = str(getattr(request, "url", "") or "")
        status = getattr(response, "status_code", None) if response is not None else None
        if status is not None:
            return f"{method} {scrub_url(raw_url)} → HTTP {status}"
        return f"{method} {scrub_url(raw_url)}"
    # Fallback: scrub any URL-looking substrings is overkill; just use type name.
    return f"{type(exc).__name__}: {scrub_url(str(exc))}"


def sentry_scrub_event(
    event: MutableMapping[str, Any],
    _hint: Optional[dict[str, Any]] = None,
) -> MutableMapping[str, Any]:
    """Sentry ``before_send``: redact sensitive query keys on request URLs."""
    request = event.get("request")
    if isinstance(request, dict):
        if "url" in request and isinstance(request["url"], str):
            request["url"] = scrub_url(request["url"])
        qs = request.get("query_string")
        if isinstance(qs, str) and qs:
            # query_string may be raw "a=1&otp=123" without leading ?
            request["query_string"] = scrub_url("http://local/?" + qs).split("?", 1)[-1]
        elif isinstance(qs, (list, tuple)):
            request["query_string"] = [
                (
                    k,
                    "[REDACTED]"
                    if str(k).strip().lower() in SENSITIVE_QUERY_KEYS
                    else v,
                )
                for k, v in qs
            ]

    # Exception values sometimes embed the full httpx URL.
    for entry in event.get("exception", {}).get("values", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("value"), str):
            entry["value"] = scrub_url(entry["value"])

    return event
