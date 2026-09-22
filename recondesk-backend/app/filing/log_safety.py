"""Redact secrets that must never appear in logs or Sentry.

Sandbox File GSTR-1 puts EVC OTP (and PAN) on the **query string**:
``POST .../gstr-1/{year}/{month}/file?pan=...&otp=...``

httpx exceptions and careless ``params=`` logging would otherwise persist
those values. Use these helpers in ``sandbox_filing_client`` and in Sentry
``before_send``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, MutableMapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query keys scrubbed wherever a full URL or param dict might be recorded.
SENSITIVE_QUERY_KEYS = frozenset({
    "otp",
    "evc_otp",
    "evcotp",
    "pan",  # authorized-signatory PAN on File / EVC calls
    "signature",
    "pkcs7_signature",
    "pkcs7",
    "dsc_signature",
    "sig",
    "dsc",
})

# GSTIN: 15 alphanumeric characters
# Chars 1-2: State code (2 digits, 01-38, 97, 99)
# Chars 3-12: Taxpayer PAN (5 letters + 4 digits + 1 letter) -> SENSITIVE PII
# Chars 13-15: Entity vertical + 'Z' + Checksum ([1-9A-Z]Z[0-9A-Z])
_GSTIN_MASK_REGEX = re.compile(
    r"(?<![A-Za-z0-9])([0-9]{2})([A-Za-z]{5}[0-9]{4}[A-Za-z])([1-9A-Za-z][zZ][0-9A-Za-z])(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _mask_gstin_match(m: re.Match) -> str:
    state = m.group(1)
    suffix = m.group(3).upper()
    return f"{state}XXXXXXXXXX{suffix}"


def mask_gstin(text: str | None) -> str:
    """Mask characters 3–12 (the embedded PAN) of any 15-character GSTIN in text.

    Example:
        '27AABCU9603R1ZM' -> '27XXXXXXXXXX1ZM'
        '/api/vendors/scorecard/27AABCU9603R1ZM' -> '/api/vendors/scorecard/27XXXXXXXXXX1ZM'
    """
    if not text or not isinstance(text, str):
        return "" if text is None else str(text)
    return _GSTIN_MASK_REGEX.sub(_mask_gstin_match, text)


def scrub_data_recursively(obj: Any) -> Any:
    """Recursively scrub query secrets and mask GSTINs in strings, dicts, and lists."""
    if isinstance(obj, str):
        return mask_gstin(scrub_url(obj))
    if isinstance(obj, dict):
        return {k: scrub_data_recursively(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_data_recursively(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(scrub_data_recursively(item) for item in obj)
    return obj


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
            return f"{method} {mask_gstin(scrub_url(raw_url))} → HTTP {status}"
        return f"{method} {mask_gstin(scrub_url(raw_url))}"
    # Fallback: scrub any URL-looking substrings is overkill; just use type name.
    return f"{type(exc).__name__}: {mask_gstin(scrub_url(str(exc)))}"


def sentry_scrub_breadcrumb(
    crumb: dict[str, Any],
    _hint: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Sentry ``before_breadcrumb``: mask GSTINs and scrub sensitive query keys."""
    if not isinstance(crumb, dict):
        return crumb

    if "message" in crumb and isinstance(crumb["message"], str):
        crumb["message"] = mask_gstin(crumb["message"])

    if "data" in crumb and isinstance(crumb["data"], dict):
        crumb["data"] = scrub_data_recursively(crumb["data"])

    return crumb


def sentry_scrub_transaction(
    event: MutableMapping[str, Any],
    _hint: Optional[dict[str, Any]] = None,
) -> MutableMapping[str, Any]:
    """Sentry ``before_send_transaction``: mask GSTINs in transaction name, request, and spans."""
    if not isinstance(event, dict):
        return event

    if "transaction" in event and isinstance(event["transaction"], str):
        event["transaction"] = mask_gstin(event["transaction"])

    request = event.get("request")
    if isinstance(request, dict):
        if "url" in request and isinstance(request["url"], str):
            request["url"] = mask_gstin(scrub_url(request["url"]))
        qs = request.get("query_string")
        if isinstance(qs, str) and qs:
            request["query_string"] = mask_gstin(
                scrub_url("http://local/?" + qs).split("?", 1)[-1]
            )
        elif isinstance(qs, (list, tuple)):
            request["query_string"] = [
                (
                    k,
                    "[REDACTED]"
                    if str(k).strip().lower() in SENSITIVE_QUERY_KEYS
                    else mask_gstin(str(v)) if isinstance(v, str) else v,
                )
                for k, v in qs
            ]

    # Mask spans descriptions
    spans = event.get("spans")
    if isinstance(spans, list):
        for span in spans:
            if isinstance(span, dict):
                if "description" in span and isinstance(span["description"], str):
                    span["description"] = mask_gstin(span["description"])
                if "op" in span and isinstance(span["op"], str):
                    span["op"] = mask_gstin(span["op"])

    # Mask breadcrumbs if included in transaction payload
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict) and "values" in breadcrumbs:
        breadcrumbs["values"] = [
            sentry_scrub_breadcrumb(c) if isinstance(c, dict) else c
            for c in (breadcrumbs.get("values") or [])
        ]

    return event


def sentry_scrub_event(
    event: MutableMapping[str, Any],
    _hint: Optional[dict[str, Any]] = None,
) -> MutableMapping[str, Any]:
    """Sentry ``before_send``: redact sensitive query keys and mask GSTINs on error events."""
    if not isinstance(event, dict):
        return event

    if "transaction" in event and isinstance(event["transaction"], str):
        event["transaction"] = mask_gstin(event["transaction"])

    request = event.get("request")
    if isinstance(request, dict):
        if "url" in request and isinstance(request["url"], str):
            request["url"] = mask_gstin(scrub_url(request["url"]))
        qs = request.get("query_string")
        if isinstance(qs, str) and qs:
            # query_string may be raw "a=1&otp=123" without leading ?
            scrubbed_qs = scrub_url("http://local/?" + qs).split("?", 1)[-1]
            request["query_string"] = mask_gstin(scrubbed_qs)
        elif isinstance(qs, (list, tuple)):
            request["query_string"] = [
                (
                    k,
                    "[REDACTED]"
                    if str(k).strip().lower() in SENSITIVE_QUERY_KEYS
                    else mask_gstin(str(v)) if isinstance(v, str) else v,
                )
                for k, v in qs
            ]

    # Exception values sometimes embed the full httpx URL or GSTIN error details.
    for entry in event.get("exception", {}).get("values", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("value"), str):
            entry["value"] = mask_gstin(scrub_url(entry["value"]))

    # Breadcrumbs inside error events
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict) and "values" in breadcrumbs:
        breadcrumbs["values"] = [
            sentry_scrub_breadcrumb(c) if isinstance(c, dict) else c
            for c in (breadcrumbs.get("values") or [])
        ]

    return event
