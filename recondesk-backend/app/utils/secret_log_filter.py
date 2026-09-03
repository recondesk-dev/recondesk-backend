"""Filter log records to avoid emitting configured secrets."""

from __future__ import annotations

import logging
from typing import Iterable

from app.config import get_settings


class SecretRedactFilter(logging.Filter):
    """Replace known secret substrings in log messages with [REDACTED]."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._snippets: list[str] = []

    def _load_secrets(self) -> None:
        s = get_settings()
        out: list[str] = []
        for attr in (
            "JWT_SECRET",
            "SECRET_KEY",
            "DATABASE_URL",
            "RAZORPAY_KEY_SECRET",
            "R2_SECRET_ACCESS_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_ANON_KEY",
            "RESEND_API_KEY",
            "SES_SMTP_PASS",
            "REDIS_URL",
        ):
            v = getattr(s, attr, None)
            if isinstance(v, str) and len(v) >= 6:
                out.append(v)
        self._snippets = sorted(out, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not self._snippets:
            self._load_secrets()
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for snip in self._snippets:
            if snip in msg:
                msg = msg.replace(snip, "[REDACTED]")
        record.msg = msg
        record.args = ()
        return True
