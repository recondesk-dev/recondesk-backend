"""Sandbox.co.in taxpayer filing client (OTP session + GSTR-1 / GSTR-3B).

Separate from ``sandbox_gst_client.py`` (stateless IMS/2B). This client owns
the stateful taxpayer session and return filing chains.

Auth (confirmed live 2026-07): generate OTP → verify OTP → refresh.
Logout may return GSTN ``TEC4002`` (HTTP 200, status_cd 0) — treated as
non-fatal; local ``filing_sessions`` is marked ``logged_out`` regardless.
Session safety net is ``token_expires_at`` (~6h), not logout success.

Dual ``status_cd`` (critical):
  - Outer ``data.status_cd == "1"`` means Sandbox/GSTN *accepted the request*
    for processing (Save / Offset / Proceed / Reset), **not** that GSTN
    finished successfully.
  - Inner ``data.data.status_cd`` on Return Status is the real outcome:
    ``P`` = processed/success, ``ER`` = error, ``PE`` = processed with error,
    ``REC`` = still received/in progress.
  Save stays ``save_pending`` until Status shows ``P``; Offset stays
  ``offset_pending`` until Status shows ``P``. ``ER``/``PE`` →
  ``save_failed`` / ``offset_failed``. Never trust the outer ``status_cd``
  alone when an inner one is present.

GSTR-3B Save / Offset Liability call :func:`assert_gstr3b_save_allowed` /
:func:`assert_gstr3b_offset_allowed` **inside** those methods (require
``sb``) so no caller can skip the period Offset gate.

EVC OTP on File is a query param (``?pan=&otp=``). Never log or persist it;
use ``log_safety`` scrubbers for any URL/params that touch that call.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import httpx

from app.filing.log_safety import (
    safe_httpx_error_text,
    scrub_query_params,
    scrub_url,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.sandbox.co.in"
_DEFAULT_API_VERSION = "1.0.0"

# Inner GSTN Return Status codes (Sandbox OpenAPI GetGstReturnStatusSuccessPayload).
GSTN_STATUS_PROCESSED = "P"
GSTN_STATUS_ERROR = "ER"
GSTN_STATUS_PROCESSED_ERROR = "PE"
GSTN_STATUS_RECEIVED = "REC"
GSTN_STATUS_FAILURES = frozenset({GSTN_STATUS_ERROR, GSTN_STATUS_PROCESSED_ERROR})
GSTN_STATUS_PENDING = frozenset({GSTN_STATUS_RECEIVED})


class FilingClientError(Exception):
    """Base error for the filing client."""


class FilingAuthError(FilingClientError):
    """Platform or taxpayer authentication failure."""


class FilingGstnError(FilingClientError):
    """GSTN business failure inside an HTTP 200 Sandbox envelope."""

    def __init__(
        self,
        message: str,
        *,
        error_cd: str | None = None,
        envelope: Any = None,
    ) -> None:
        super().__init__(message)
        self.error_cd = error_cd
        self.envelope = envelope


class FilingApiError(FilingClientError):
    """Unexpected HTTP / transport failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class TaxpayerSession:
    """Verified taxpayer access token + expiry metadata."""

    access_token: str
    token_expires_at: datetime
    session_expires_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LogoutResult:
    """Outcome of Logout — never raises for known GSTN TEC4002."""

    ok: bool
    status_cd: str | None = None
    error_cd: str | None = None
    error_message: str | None = None
    envelope: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReturnStatusInfo:
    """Parsed dual-status Return Status (or nested status on any envelope)."""

    outer_status_cd: str | None
    gstn_status_cd: str | None
    action: str | None = None
    form_typ: str | None = None
    error_cd: str | None = None
    error_message: str | None = None
    error_report: Any = None

    @property
    def is_success(self) -> bool:
        return self.gstn_status_cd == GSTN_STATUS_PROCESSED

    @property
    def is_failed(self) -> bool:
        return self.gstn_status_cd in GSTN_STATUS_FAILURES

    @property
    def is_pending(self) -> bool:
        if self.gstn_status_cd is None:
            return True
        if self.is_success or self.is_failed:
            return False
        return True


@dataclass
class FilingApiResult:
    """Generic success wrapper for Save / Proceed / Status / Summary / File."""

    envelope: dict[str, Any]
    reference_id: str | None = None
    ack_number: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    # Populated for Return Status (and any response that carries an inner status).
    return_status: ReturnStatusInfo | None = None


def period_to_year_month(period: str) -> tuple[str, str]:
    """``YYYY-MM`` → (``YYYY``, ``MM``)."""
    p = (period or "").strip()
    if len(p) != 7 or p[4] != "-" or not (p[:4].isdigit() and p[5:].isdigit()):
        raise ValueError(f"period must be YYYY-MM; got {period!r}")
    return p[:4], p[5:]


def period_to_fp(period: str) -> str:
    """``YYYY-MM`` → GSTN ``fp`` / ``ret_period`` ``MMYYYY``."""
    year, month = period_to_year_month(period)
    return f"{month}{year}"


def ms_to_datetime(ms: Any) -> datetime | None:
    if ms is None or ms == "":
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def build_save_body(
    save_payload: Mapping[str, Any],
    *,
    gstin: str,
    period: str,
    gt: float = 0.0,
    cur_gt: float = 0.0,
) -> dict[str, Any]:
    """Merge orchestrator ``save_payload`` with Save envelope fields."""
    from app.filing.gstr1_filing_mapper import _gstn_finalize_amounts

    body = dict(save_payload)
    body.setdefault("gstin", gstin.strip().upper())
    body.setdefault("fp", period_to_fp(period))
    body.setdefault("gt", float(gt))
    body.setdefault("cur_gt", float(cur_gt))
    return _gstn_finalize_amounts(body)


def _gstn_error(data: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    """Outer-envelope GSTN failure (``data.status_cd == "0"`` + ``error``).

    Does **not** interpret inner Return Status codes (``P``/``ER``/``PE``/``REC``);
    those live under ``data.data.status_cd`` and are handled by
    :func:`parse_return_status`.
    """
    if not isinstance(data, dict):
        return None, None
    err = data.get("error")
    if isinstance(err, dict):
        cd = err.get("error_cd") or err.get("code")
        msg = err.get("message") or err.get("msg")
        if cd or msg:
            return (
                str(cd).strip() if cd else None,
                str(msg).strip() if msg else "GSTN business error",
            )
    status_cd = str(data.get("status_cd", "")).strip()
    if status_cd and status_cd not in {"1"}:
        return status_cd, f"GSTN status_cd={status_cd}"
    return None, None


def _nested_payload(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    return inner if isinstance(inner, dict) else {}


def _error_from_report(report: Any) -> tuple[str | None, str | None]:
    """Pull first ``error_cd`` / ``error_msg`` from a Status ``error_report``."""
    if not isinstance(report, dict):
        return None, None
    cd = report.get("error_cd")
    msg = report.get("error_msg") or report.get("message")
    if cd or msg:
        return (
            str(cd).strip() if cd else None,
            str(msg).strip() if msg else None,
        )
    for value in report.values():
        if isinstance(value, list):
            for item in value:
                nested_cd, nested_msg = _error_from_report(item)
                if nested_cd or nested_msg:
                    return nested_cd, nested_msg
        elif isinstance(value, dict):
            nested_cd, nested_msg = _error_from_report(value)
            if nested_cd or nested_msg:
                return nested_cd, nested_msg
    return None, None


def parse_return_status(envelope: Mapping[str, Any] | None) -> ReturnStatusInfo:
    """Parse outer + inner ``status_cd`` from a Sandbox taxpayer envelope.

    Outer ``"1"`` alone is never treated as data acceptance. Inner codes:
    ``P`` success, ``ER``/``PE`` failure, ``REC`` (or unknown) still pending.
    """
    if not isinstance(envelope, dict):
        return ReturnStatusInfo(outer_status_cd=None, gstn_status_cd=None)
    data = envelope.get("data")
    if not isinstance(data, dict):
        return ReturnStatusInfo(outer_status_cd=None, gstn_status_cd=None)

    outer = str(data.get("status_cd", "")).strip() or None
    nested = _nested_payload(data)
    gstn = str(nested.get("status_cd", "")).strip() or None
    action = str(nested.get("action", "")).strip() or None
    form_typ = str(nested.get("form_typ", "")).strip() or None
    report = nested.get("error_report")
    err_cd, err_msg = _error_from_report(report)
    if not err_cd and not err_msg:
        # Some failure envelopes put error beside status_cd at the outer layer.
        err_cd, err_msg = _gstn_error(data)

    return ReturnStatusInfo(
        outer_status_cd=outer,
        gstn_status_cd=gstn,
        action=action,
        form_typ=form_typ,
        error_cd=err_cd,
        error_message=err_msg,
        error_report=report,
    )


def filing_run_status_after_async_poll(
    info: ReturnStatusInfo,
    *,
    on_success: str,
    on_failure: str,
    on_pending: str,
    pending_label: str = "operation",
) -> tuple[str, str | None, str | None]:
    """Map a Return Status poll → ``filing_runs.status`` (+ error fields).

    Shared by GSTR-1 Save and GSTR-3B Offset (and any future async GSTN step).
    Returns ``(status, error_code, error_message)``.
    """
    if info.is_success:
        return on_success, None, None
    if info.is_failed:
        msg = (
            info.error_message
            or f"GSTN {pending_label} status_cd={info.gstn_status_cd}"
        )
        return on_failure, info.error_cd or info.gstn_status_cd, msg
    return on_pending, None, None


def filing_run_status_after_save_poll(
    info: ReturnStatusInfo,
) -> tuple[str, str | None, str | None]:
    """Map a Save Return Status poll → ``saved`` / ``save_failed`` / ``save_pending``."""
    return filing_run_status_after_async_poll(
        info,
        on_success="saved",
        on_failure="save_failed",
        on_pending="save_pending",
        pending_label="save",
    )


def filing_run_status_after_offset_poll(
    info: ReturnStatusInfo,
) -> tuple[str, str | None, str | None]:
    """Map an Offset Return Status poll → ``offset_complete`` / ``offset_failed`` / ``offset_pending``."""
    return filing_run_status_after_async_poll(
        info,
        on_success="offset_complete",
        on_failure="offset_failed",
        on_pending="offset_pending",
        pending_label="offset",
    )


def _raise_if_inner_gstn_failure(
    envelope: Mapping[str, Any],
    *,
    context: str,
) -> None:
    """If nested payload carries ``ER``/``PE``, raise — do not trust outer ``1``."""
    info = parse_return_status(envelope)
    if not info.is_failed:
        return
    raise FilingGstnError(
        info.error_message
        or f"{context}: GSTN inner status_cd={info.gstn_status_cd}",
        error_cd=info.error_cd or info.gstn_status_cd,
        envelope=dict(envelope),
    )


def _gstin_from_save_body(save_body: Mapping[str, Any]) -> str:
    raw = save_body.get("gstin") if isinstance(save_body, Mapping) else None
    g = str(raw or "").strip().upper()
    if not g:
        raise FilingClientError("GSTR-3B save_body missing gstin (required for Offset gate)")
    return g


class SandboxFilingClient:
    """HTTP client for Sandbox taxpayer session + GSTR-1 / GSTR-3B filing APIs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = (api_key or os.environ.get("SANDBOX_API_KEY") or "").strip()
        self._api_secret = (
            api_secret or os.environ.get("SANDBOX_API_SECRET") or ""
        ).strip()
        if not self._api_key:
            raise FilingAuthError("SANDBOX_API_KEY is not set")
        if not self._api_secret:
            raise FilingAuthError("SANDBOX_API_SECRET is not set")
        self._base_url = (
            base_url
            or os.environ.get("SANDBOX_BASE_URL")
            or _DEFAULT_BASE_URL
        ).rstrip("/")
        self._api_version = (
            api_version
            or os.environ.get("SANDBOX_API_VERSION")
            or _DEFAULT_API_VERSION
        )
        self._timeout = timeout
        self._http = httpx.Client(timeout=timeout)
        self._platform_jwt: str | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SandboxFilingClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ auth
    def authenticate_platform(self, *, force: bool = False) -> str:
        """``POST /authenticate`` → platform JWT (not the taxpayer token)."""
        if self._platform_jwt and not force:
            return self._platform_jwt
        headers = {
            "x-api-key": self._api_key,
            "x-api-secret": self._api_secret,
            "x-api-version": self._api_version,
            "Content-Type": "application/json",
        }
        logger.info("Filing client POST /authenticate")
        try:
            resp = self._http.post(f"{self._base_url}/authenticate", headers=headers)
        except httpx.HTTPError as exc:
            raise FilingApiError(safe_httpx_error_text(exc)) from exc
        if resp.status_code != 200:
            raise FilingAuthError(
                f"Platform authenticate failed HTTP {resp.status_code}"
            )
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        token = None
        if isinstance(data, dict):
            token = data.get("access_token")
        if not token and isinstance(body, dict):
            token = body.get("access_token")
        if not token:
            raise FilingAuthError("authenticate response missing access_token")
        self._platform_jwt = str(token)
        return self._platform_jwt

    def generate_otp(self, *, username: str, gstin: str) -> dict[str, Any]:
        """``POST /gst/compliance/tax-payer/otp``."""
        jwt = self.authenticate_platform()
        return self._request(
            "POST",
            "/gst/compliance/tax-payer/otp",
            authorization=jwt,
            json_body={"username": username.strip(), "gstin": gstin.strip().upper()},
            extra_headers={"x-source": "primary"},
            require_gstn_success=True,
        )

    def verify_otp(
        self,
        *,
        username: str,
        gstin: str,
        otp: str,
    ) -> TaxpayerSession:
        """``POST /gst/compliance/tax-payer/otp/verify?otp=``."""
        jwt = self.authenticate_platform()
        envelope = self._request(
            "POST",
            "/gst/compliance/tax-payer/otp/verify",
            authorization=jwt,
            params={"otp": otp.strip()},
            json_body={"username": username.strip(), "gstin": gstin.strip().upper()},
            extra_headers={"x-source": "primary"},
            require_gstn_success=True,
            sensitive_params=True,
        )
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not isinstance(data, dict) or not data.get("access_token"):
            raise FilingGstnError(
                "verify OTP response missing access_token",
                envelope=envelope,
            )
        token_exp = ms_to_datetime(data.get("token_expiry"))
        session_exp = ms_to_datetime(data.get("session_expiry"))
        if token_exp is None:
            raise FilingGstnError(
                "verify OTP response missing token_expiry",
                envelope=envelope,
            )
        return TaxpayerSession(
            access_token=str(data["access_token"]),
            token_expires_at=token_exp,
            session_expires_at=session_exp,
            raw=data,
        )

    def refresh_session(self, taxpayer_token: str) -> TaxpayerSession:
        """``POST /gst/compliance/tax-payer/session/refresh``."""
        envelope = self._request(
            "POST",
            "/gst/compliance/tax-payer/session/refresh",
            authorization=taxpayer_token,
            require_gstn_success=True,
        )
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not isinstance(data, dict) or not data.get("access_token"):
            raise FilingGstnError(
                "refresh response missing access_token",
                envelope=envelope,
            )
        token_exp = ms_to_datetime(data.get("token_expiry"))
        session_exp = ms_to_datetime(data.get("session_expiry"))
        if token_exp is None:
            raise FilingGstnError(
                "refresh response missing token_expiry",
                envelope=envelope,
            )
        return TaxpayerSession(
            access_token=str(data["access_token"]),
            token_expires_at=token_exp,
            session_expires_at=session_exp,
            raw=data,
        )

    def logout(self, taxpayer_token: str) -> LogoutResult:
        """``POST /gst/compliance/tax-payer/logout`` — never raises on TEC4002.

        Callers must still mark local ``filing_sessions`` as ``logged_out`` and
        rely on ``token_expires_at`` as the real session safety net.
        """
        try:
            envelope = self._request(
                "POST",
                "/gst/compliance/tax-payer/logout",
                authorization=taxpayer_token,
                require_gstn_success=False,
            )
        except FilingClientError as exc:
            logger.warning("Filing logout transport/API error (non-fatal): %s", exc)
            return LogoutResult(ok=False, error_message=str(exc))

        data = envelope.get("data") if isinstance(envelope, dict) else None
        status_cd = None
        if isinstance(data, dict):
            status_cd = str(data.get("status_cd", "")).strip() or None
        err_cd, err_msg = _gstn_error(data if isinstance(data, dict) else None)
        if status_cd == "1" and not err_cd:
            return LogoutResult(ok=True, status_cd=status_cd, envelope=envelope)

        logger.warning(
            "Filing logout GSTN non-success (non-fatal): error_cd=%s message=%s",
            err_cd,
            err_msg,
        )
        return LogoutResult(
            ok=False,
            status_cd=status_cd,
            error_cd=err_cd,
            error_message=err_msg,
            envelope=envelope if isinstance(envelope, dict) else {},
        )

    # ----------------------------------------------------------- GSTR-1 chain
    def save_gstr1(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST .../gstrs/gstr-1/{year}/{month}``.

        Outer ``status_cd == "1"`` + ``reference_id`` only means the Save was
        *accepted for processing*. Call :meth:`get_return_status` (or
        :meth:`wait_for_return_status`) until inner ``status_cd == "P"`` before
        treating the Save as successful.
        """
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-1/{year}/{month}"
        envelope = self._request(
            "POST",
            path,
            authorization=taxpayer_token,
            json_body=dict(save_body),
            require_gstn_success=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="Save GSTR-1")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        ref = nested.get("reference_id")
        return FilingApiResult(
            envelope=envelope,
            reference_id=str(ref) if ref else None,
            data=nested,
            return_status=parse_return_status(envelope),
        )

    def get_return_status(
        self,
        taxpayer_token: str,
        *,
        period: str,
        reference_id: str,
    ) -> FilingApiResult:
        """``GET .../gstrs/{year}/{month}/status``.

        Outer ``status_cd`` may be ``"1"`` even when inner GSTN status is
        ``ER``/``PE``. Callers must inspect :attr:`FilingApiResult.return_status`.
        This method does **not** raise on inner ``ER``/``PE`` so the filing
        run can be marked ``save_failed`` with the error payload intact.
        """
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/{year}/{month}/status"
        envelope = self._request(
            "GET",
            path,
            authorization=taxpayer_token,
            params={"reference_id": reference_id},
            require_gstn_success=True,
        )
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        info = parse_return_status(envelope)
        return FilingApiResult(
            envelope=envelope,
            data=nested or (data if isinstance(data, dict) else {}),
            return_status=info,
        )

    def wait_for_return_status(
        self,
        taxpayer_token: str,
        *,
        period: str,
        reference_id: str,
        poll_interval_sec: float = 2.0,
        max_attempts: int = 30,
    ) -> FilingApiResult:
        """Poll Return Status until inner status is terminal (``P`` / ``ER`` / ``PE``)."""
        last: FilingApiResult | None = None
        for attempt in range(max_attempts):
            last = self.get_return_status(
                taxpayer_token,
                period=period,
                reference_id=reference_id,
            )
            info = last.return_status
            if info and (info.is_success or info.is_failed):
                return last
            if attempt + 1 < max_attempts and poll_interval_sec > 0:
                time.sleep(poll_interval_sec)
        if last is None:
            raise FilingApiError("Return Status poll produced no response")
        return last

    def proceed_to_file(
        self,
        taxpayer_token: str,
        *,
        period: str,
        is_nil: str = "N",
        gstr: str = "gstr-1",
    ) -> FilingApiResult:
        """``POST .../gstrs/{gstr}/{year}/{month}/new-proceed?is_nil=``.

        Like Save: outer ``"1"`` + ``reference_id`` is acceptance for
        processing; poll Return Status for inner ``P`` before relying on it.
        """
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/{gstr}/{year}/{month}/new-proceed"
        envelope = self._request(
            "POST",
            path,
            authorization=taxpayer_token,
            params={"is_nil": is_nil},
            require_gstn_success=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="Proceed to file")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        ref = nested.get("reference_id")
        return FilingApiResult(
            envelope=envelope,
            reference_id=str(ref) if ref else None,
            data=nested,
            return_status=parse_return_status(envelope),
        )

    def get_gstr1_summary(
        self,
        taxpayer_token: str,
        *,
        period: str,
        summary_type: str = "long",
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-1/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-1/{year}/{month}"
        params = {"summary_type": summary_type} if summary_type else None
        envelope = self._request(
            "GET",
            path,
            authorization=taxpayer_token,
            params=params,
            require_gstn_success=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="GSTR-1 summary")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        return FilingApiResult(
            envelope=envelope,
            data=nested or (data if isinstance(data, dict) else {}),
            return_status=parse_return_status(envelope),
        )

    def generate_evc_otp(
        self,
        taxpayer_token: str,
        *,
        pan: str,
        gstr: str = "gstr-1",
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/evc/otp?gstr=`` body ``{pan}``."""
        envelope = self._request(
            "POST",
            "/gst/compliance/tax-payer/evc/otp",
            authorization=taxpayer_token,
            params={"gstr": gstr},
            json_body={"pan": pan.strip().upper()},
            require_gstn_success=True,
            redact_body=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="EVC OTP")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        return FilingApiResult(
            envelope=envelope,
            data=data if isinstance(data, dict) else {},
            return_status=parse_return_status(envelope),
        )

    def file_gstr1(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        otp: str | None = None,
        signature: str | None = None,
        signing_method: str = "evc",
        file_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST .../gstr-1/{year}/{month}/file`` with EVC or DSC."""
        method = (signing_method or "evc").strip().lower()
        if method == "evc":
            if not otp or not otp.strip():
                raise FilingClientError("EVC filing requires an OTP")
            params = {"pan": pan.strip().upper(), "otp": otp.strip()}
            body_payload = dict(file_body)
        elif method == "dsc":
            if not signature or not signature.strip():
                raise FilingClientError("DSC filing requires a PKCS7 signature string")
            params = {"pan": pan.strip().upper()}
            body_payload = dict(file_body)
            body_payload["pkcs7_signature"] = signature.strip()
        else:
            raise FilingClientError(f"Unsupported signing_method {signing_method!r}; must be 'evc' or 'dsc'")

        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-1/{year}/{month}/file"
        envelope = self._request(
            "POST",
            path,
            authorization=taxpayer_token,
            params=params,
            json_body=body_payload,
            require_gstn_success=True,
            sensitive_params=True,
            redact_body=(method == "dsc"),
        )
        _raise_if_inner_gstn_failure(envelope, context="File GSTR-1")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        ack = nested.get("ack_num") or nested.get("ack_number")
        return FilingApiResult(
            envelope=envelope,
            ack_number=str(ack) if ack else None,
            data=nested,
            return_status=parse_return_status(envelope),
        )

    # ----------------------------------------------------------- GSTR-1A chain
    def save_gstr1a(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST .../gstrs/gstr-1a/{year}/{month}``.

        Outer status_cd == "1" + reference_id means the Save was accepted for processing.
        """
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-1a/{year}/{month}"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body=dict(save_body),
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="Save GSTR-1A")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            ref = nested.get("reference_id") or (data.get("reference_id") if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                reference_id=str(ref) if ref else None,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-1A Save endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "Use GSTN Offline Tool JSON Export for official upload.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def get_gstr1a_summary(
        self,
        taxpayer_token: str,
        *,
        period: str,
        summary_type: str = "long",
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-1a/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-1a/{year}/{month}"
        params = {"summary_type": summary_type} if summary_type else None
        try:
            envelope = self._request(
                "GET",
                path,
                authorization=taxpayer_token,
                params=params,
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="GSTR-1A summary")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-1A Summary endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}).",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def file_gstr1a(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        otp: str | None = None,
        signature: str | None = None,
        signing_method: str = "evc",
        file_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST .../gstrs/gstr-1a/{year}/{month}/file`` with EVC or DSC."""
        method = (signing_method or "evc").strip().lower()
        if method == "evc":
            if not otp or not otp.strip():
                raise FilingClientError("EVC filing requires an OTP")
            params = {"pan": pan.strip().upper(), "otp": otp.strip()}
            body_payload = dict(file_body)
        elif method == "dsc":
            if not signature or not signature.strip():
                raise FilingClientError("DSC filing requires a PKCS7 signature string")
            params = {"pan": pan.strip().upper()}
            body_payload = dict(file_body)
            body_payload["pkcs7_signature"] = signature.strip()
        else:
            raise FilingClientError(f"Unsupported signing_method {signing_method!r}; must be 'evc' or 'dsc'")

        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-1a/{year}/{month}/file"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                params=params,
                json_body=body_payload,
                require_gstn_success=True,
                sensitive_params=True,
                redact_body=(method == "dsc"),
            )
            _raise_if_inner_gstn_failure(envelope, context="File GSTR-1A")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            ack = nested.get("ack_num") or nested.get("ack_number")
            return FilingApiResult(
                envelope=envelope,
                ack_number=str(ack) if ack else None,
                data=nested,
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-1A File endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "File using GSTN Portal after uploading offline JSON.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    # ----------------------------------------------------------- GSTR-3B chain
    def get_gstr3b_details(
        self,
        taxpayer_token: str,
        *,
        period: str,
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-3b/{year}/{month}``.

        After a successful Offset, re-fetch to obtain ``tx_pmt`` (required for File).
        """
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-3b/{year}/{month}"
        envelope = self._request(
            "GET",
            path,
            authorization=taxpayer_token,
            require_gstn_success=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="Get GSTR-3B Details")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        # Details payload may sit at data.data or directly under data.
        details = nested if nested else (data if isinstance(data, dict) else {})
        return FilingApiResult(
            envelope=envelope,
            data=details if isinstance(details, dict) else {},
            return_status=parse_return_status(envelope),
        )

    def get_ledger_balance(
        self,
        taxpayer_token: str,
        *,
        period: str,
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/ledgers/bal/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/ledgers/bal/{year}/{month}"
        envelope = self._request(
            "GET",
            path,
            authorization=taxpayer_token,
            require_gstn_success=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="Get ledger balance")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        return FilingApiResult(
            envelope=envelope,
            data=nested or (data if isinstance(data, dict) else {}),
            return_status=parse_return_status(envelope),
        )

    def save_gstr3b(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
        sb,
    ) -> FilingApiResult:
        """``POST .../gstrs/gstr-3b/{year}/{month}``.

        Calls :func:`assert_gstr3b_save_allowed` **before** the HTTP request so
        a period that already completed Offset cannot Save again (any run_id).

        Outer ``status_cd == "1"`` + ``reference_id`` only means accepted for
        processing — poll :meth:`wait_for_return_status` for inner ``P``.
        """
        from app.filing.filing_store import assert_gstr3b_save_allowed

        gstin = _gstin_from_save_body(save_body)
        assert_gstr3b_save_allowed(sb, gstin=gstin, period=period)

        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-3b/{year}/{month}"
        envelope = self._request(
            "POST",
            path,
            authorization=taxpayer_token,
            json_body=dict(save_body),
            require_gstn_success=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="Save GSTR-3B")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        ref = nested.get("reference_id")
        return FilingApiResult(
            envelope=envelope,
            reference_id=str(ref) if ref else None,
            data=nested,
            return_status=parse_return_status(envelope),
        )

    def offset_gstr3b_liability(
        self,
        taxpayer_token: str,
        *,
        period: str,
        gstin: str,
        offset_body: Mapping[str, Any],
        sb,
    ) -> FilingApiResult:
        """``POST .../gstr-3b/{year}/{month}/offset-liability``.

        Calls :func:`assert_gstr3b_offset_allowed` **before** the HTTP request.
        Outer success / \"Payment of tax successfully done\" is **not** enough —
        poll Return Status for inner ``P`` before marking ``offset_complete``.

        ``RT-3BAS1070`` (partial/excess) raises :class:`FilingGstnError` and does
        **not** set the permanent Offset gate.
        """
        from app.filing.filing_store import assert_gstr3b_offset_allowed

        assert_gstr3b_offset_allowed(
            sb, gstin=gstin.strip().upper(), period=period,
        )

        year, month = period_to_year_month(period)
        path = (
            f"/gst/compliance/tax-payer/gstrs/gstr-3b/{year}/{month}/offset-liability"
        )
        envelope = self._request(
            "POST",
            path,
            authorization=taxpayer_token,
            json_body=dict(offset_body),
            require_gstn_success=True,
        )
        _raise_if_inner_gstn_failure(envelope, context="Offset GSTR-3B liability")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        ref = nested.get("reference_id") if nested else None
        if not ref and isinstance(data, dict):
            # Some envelopes put reference_id beside Message under data.data
            ref = data.get("reference_id")
        return FilingApiResult(
            envelope=envelope,
            reference_id=str(ref) if ref else None,
            data=nested or (data if isinstance(data, dict) else {}),
            return_status=parse_return_status(envelope),
        )

    def generate_evc_otp_gstr3b(
        self,
        taxpayer_token: str,
        *,
        pan: str,
    ) -> FilingApiResult:
        """EVC OTP for GSTR-3B (``?gstr=gstr-3b``)."""
        return self.generate_evc_otp(
            taxpayer_token, pan=pan, gstr="gstr-3b",
        )

    def file_gstr3b(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        otp: str | None = None,
        signature: str | None = None,
        signing_method: str = "evc",
        file_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST .../gstr-3b/{year}/{month}/file`` with EVC or DSC.

        ``file_body`` must include post-Offset ``tx_pmt`` from Get Details.
        """
        method = (signing_method or "evc").strip().lower()
        if method == "evc":
            if not otp or not otp.strip():
                raise FilingClientError("EVC filing requires an OTP")
            params = {"pan": pan.strip().upper(), "otp": otp.strip()}
            body_payload = dict(file_body)
        elif method == "dsc":
            if not signature or not signature.strip():
                raise FilingClientError("DSC filing requires a PKCS7 signature string")
            params = {"pan": pan.strip().upper()}
            body_payload = dict(file_body)
            body_payload["pkcs7_signature"] = signature.strip()
        else:
            raise FilingClientError(f"Unsupported signing_method {signing_method!r}; must be 'evc' or 'dsc'")

        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-3b/{year}/{month}/file"
        envelope = self._request(
            "POST",
            path,
            authorization=taxpayer_token,
            params=params,
            json_body=body_payload,
            require_gstn_success=True,
            sensitive_params=True,
            redact_body=(method == "dsc"),
        )
        _raise_if_inner_gstn_failure(envelope, context="File GSTR-3B")
        data = envelope.get("data") if isinstance(envelope, dict) else None
        nested = _nested_payload(data if isinstance(data, dict) else None)
        ack = nested.get("ack_num") or nested.get("ack_number")
        return FilingApiResult(
            envelope=envelope,
            ack_number=str(ack) if ack else None,
            data=nested,
            return_status=parse_return_status(envelope),
        )

    # ----------------------------------------------------------- GSTR-7 chain
    def save_gstr7(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-7/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-7/{year}/{month}"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body=dict(save_body),
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="Save GSTR-7")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-7 Save endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "Use GSTN Offline Tool JSON Export for official upload.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def get_gstr7_summary(
        self,
        taxpayer_token: str,
        *,
        period: str,
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-7/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-7/{year}/{month}"
        try:
            envelope = self._request(
                "GET",
                path,
                authorization=taxpayer_token,
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="GSTR-7 summary")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-7 Summary endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}).",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def file_gstr7(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        otp: str | None = None,
        signature: str | None = None,
        signing_method: str = "evc",
        file_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST .../gstrs/gstr-7/{year}/{month}/file`` with EVC or DSC."""
        method = (signing_method or "evc").strip().lower()
        if method == "evc":
            if not otp or not otp.strip():
                raise FilingClientError("EVC filing requires an OTP")
            params = {"pan": pan.strip().upper(), "otp": otp.strip()}
            body_payload = dict(file_body)
        elif method == "dsc":
            if not signature or not signature.strip():
                raise FilingClientError("DSC filing requires a PKCS7 signature string")
            params = {"pan": pan.strip().upper()}
            body_payload = dict(file_body)
            body_payload["pkcs7_signature"] = signature.strip()
        else:
            raise FilingClientError(f"Unsupported signing_method {signing_method!r}; must be 'evc' or 'dsc'")

        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-7/{year}/{month}/file"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                params=params,
                json_body=body_payload,
                require_gstn_success=True,
                sensitive_params=True,
                redact_body=(method == "dsc"),
            )
            _raise_if_inner_gstn_failure(envelope, context="File GSTR-7")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            ack = nested.get("ack_num") or nested.get("ack_number")
            return FilingApiResult(
                envelope=envelope,
                ack_number=str(ack) if ack else None,
                data=nested,
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-7 File endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "File using GSTN Portal after uploading offline JSON.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    # ----------------------------------------------------------- GSTR-8 chain
    def save_gstr8(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-8/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-8/{year}/{month}"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body=dict(save_body),
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="Save GSTR-8")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-8 Save endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "Use GSTN Offline Tool JSON Export for official upload.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def get_gstr8_summary(
        self,
        taxpayer_token: str,
        *,
        period: str,
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-8/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-8/{year}/{month}"
        try:
            envelope = self._request(
                "GET",
                path,
                authorization=taxpayer_token,
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="GSTR-8 summary")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-8 Summary endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}).",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def file_gstr8(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        otp: str | None = None,
        signature: str | None = None,
        signing_method: str = "evc",
        file_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST .../gstrs/gstr-8/{year}/{month}/file`` with EVC or DSC."""
        method = (signing_method or "evc").strip().lower()
        if method == "evc":
            if not otp or not otp.strip():
                raise FilingClientError("EVC filing requires an OTP")
            params = {"pan": pan.strip().upper(), "otp": otp.strip()}
            body_payload = dict(file_body)
        elif method == "dsc":
            if not signature or not signature.strip():
                raise FilingClientError("DSC filing requires a PKCS7 signature string")
            params = {"pan": pan.strip().upper()}
            body_payload = dict(file_body)
            body_payload["pkcs7_signature"] = signature.strip()
        else:
            raise FilingClientError(f"Unsupported signing_method {signing_method!r}; must be 'evc' or 'dsc'")

        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-8/{year}/{month}/file"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                params=params,
                json_body=body_payload,
                require_gstn_success=True,
                sensitive_params=True,
                redact_body=(method == "dsc"),
            )
            _raise_if_inner_gstn_failure(envelope, context="File GSTR-8")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            ack = nested.get("ack_num") or nested.get("ack_number")
            return FilingApiResult(
                envelope=envelope,
                ack_number=str(ack) if ack else None,
                data=nested,
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-8 File endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "File using GSTN Portal after uploading offline JSON.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    # ----------------------------------------------------------- GSTR-6 chain
    def save_gstr6(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-6/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-6/{year}/{month}"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body=dict(save_body),
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="Save GSTR-6")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-6 Save endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "Use GSTN Offline Tool JSON Export for official upload.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def get_gstr6_summary(
        self,
        taxpayer_token: str,
        *,
        period: str,
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-6/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-6/{year}/{month}"
        try:
            envelope = self._request(
                "GET",
                path,
                authorization=taxpayer_token,
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="GSTR-6 summary")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-6 Summary endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}).",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def file_gstr6(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        signing_method: str = "evc",
        otp: str | None = None,
        pkcs7_signature: str | None = None,
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-6/{year}/{month}/file``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-6/{year}/{month}/file"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body={"pan": pan, "signing_method": signing_method, "otp": otp, "pkcs7_signature": pkcs7_signature},
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="File GSTR-6")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            ack = nested.get("ack_num") or nested.get("ack_number")
            return FilingApiResult(
                envelope=envelope,
                ack_number=str(ack) if ack else None,
                data=nested,
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-6 File endpoint is unsupported by current GSTN API (HTTP {exc.status_code}). "
                    "Upload via GST Portal Offline Utility.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    # ----------------------------------------------------------- GSTR-5 chain
    def save_gstr5(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-5/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-5/{year}/{month}"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body=dict(save_body),
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="Save GSTR-5")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-5 Save endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "Use GSTN Offline Tool JSON Export for official upload.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def get_gstr5_summary(
        self,
        taxpayer_token: str,
        *,
        period: str,
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-5/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-5/{year}/{month}"
        try:
            envelope = self._request(
                "GET",
                path,
                authorization=taxpayer_token,
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="GSTR-5 summary")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-5 Summary endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}).",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def file_gstr5(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        signing_method: str = "evc",
        otp: str | None = None,
        pkcs7_signature: str | None = None,
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-5/{year}/{month}/file``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-5/{year}/{month}/file"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body={"pan": pan, "signing_method": signing_method, "otp": otp, "pkcs7_signature": pkcs7_signature},
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="File GSTR-5")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            ack = nested.get("ack_num") or nested.get("ack_number")
            return FilingApiResult(
                envelope=envelope,
                ack_number=str(ack) if ack else None,
                data=nested,
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-5 File endpoint is unsupported by current GSTN API (HTTP {exc.status_code}). "
                    "Upload via GST Portal Offline Utility.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    # ---------------------------------------------------------- GSTR-5A chain
    def save_gstr5a(
        self,
        taxpayer_token: str,
        *,
        period: str,
        save_body: Mapping[str, Any],
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-5a/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-5a/{year}/{month}"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body=dict(save_body),
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="Save GSTR-5A")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-5A Save endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}). "
                    "Use GSTN Offline Tool JSON Export for official upload.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def get_gstr5a_summary(
        self,
        taxpayer_token: str,
        *,
        period: str,
    ) -> FilingApiResult:
        """``GET /gst/compliance/tax-payer/gstrs/gstr-5a/{year}/{month}``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-5a/{year}/{month}"
        try:
            envelope = self._request(
                "GET",
                path,
                authorization=taxpayer_token,
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="GSTR-5A summary")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            return FilingApiResult(
                envelope=envelope,
                data=nested or (data if isinstance(data, dict) else {}),
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-5A Summary endpoint is unsupported by the current GSTN/GSP API environment (HTTP {exc.status_code}).",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    def file_gstr5a(
        self,
        taxpayer_token: str,
        *,
        period: str,
        pan: str,
        signing_method: str = "evc",
        otp: str | None = None,
        pkcs7_signature: str | None = None,
    ) -> FilingApiResult:
        """``POST /gst/compliance/tax-payer/gstrs/gstr-5a/{year}/{month}/file``."""
        year, month = period_to_year_month(period)
        path = f"/gst/compliance/tax-payer/gstrs/gstr-5a/{year}/{month}/file"
        try:
            envelope = self._request(
                "POST",
                path,
                authorization=taxpayer_token,
                json_body={"pan": pan, "signing_method": signing_method, "otp": otp, "pkcs7_signature": pkcs7_signature},
                require_gstn_success=True,
            )
            _raise_if_inner_gstn_failure(envelope, context="File GSTR-5A")
            data = envelope.get("data") if isinstance(envelope, dict) else None
            nested = _nested_payload(data if isinstance(data, dict) else None)
            ack = nested.get("ack_num") or nested.get("ack_number")
            return FilingApiResult(
                envelope=envelope,
                ack_number=str(ack) if ack else None,
                data=nested,
                return_status=parse_return_status(envelope),
            )
        except FilingApiError as exc:
            if exc.status_code in (404, 405, 501):
                raise FilingGstnError(
                    f"GSTR-5A File endpoint is unsupported by current GSTN API (HTTP {exc.status_code}). "
                    "Upload via GST Portal Offline Utility.",
                    error_cd="UNSUPPORTED_BY_GSTN_API",
                ) from exc
            raise

    # -------------------------------------------------------------- internals
    def _headers(
        self,
        authorization: str,
        *,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        h = {
            "authorization": authorization,
            "x-api-key": self._api_key,
            "x-api-version": self._api_version,
            "Content-Type": "application/json",
        }
        if extra:
            h.update(dict(extra))
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        authorization: str,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
        require_gstn_success: bool = True,
        sensitive_params: bool = False,
        redact_body: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = self._headers(authorization, extra=extra_headers)
        log_params = (
            scrub_query_params(params) if sensitive_params else dict(params or {})
        )
        log_url = scrub_url(url) if sensitive_params else url
        if redact_body:
            logger.info(
                "Filing %s %s params=%s body=[REDACTED]",
                method,
                log_url,
                log_params,
            )
        else:
            logger.info(
                "Filing %s %s params=%s body_keys=%s",
                method,
                log_url,
                log_params,
                sorted(json_body.keys()) if json_body else [],
            )

        for attempt in range(3):
            try:
                resp = self._http.request(
                    method,
                    url,
                    headers=headers,
                    params=dict(params or {}),
                    json=dict(json_body) if json_body is not None else None,
                )
                if resp.status_code == 429 and attempt < 2:
                    retry_after = float(resp.headers.get("Retry-After", (attempt + 1) * 1.5))
                    logger.warning("Filing rate-limited (HTTP 429). Retrying in %.1fs...", retry_after)
                    time.sleep(retry_after)
                    continue
                break
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise FilingApiError(safe_httpx_error_text(exc)) from exc
                time.sleep((attempt + 1) * 1.0)

        logger.info(
            "Filing response status=%s url=%s",
            resp.status_code,
            scrub_url(str(resp.request.url)) if sensitive_params else path,
        )

        if resp.status_code in (401, 403):
            # Sandbox platform often returns bare 401/403 for bad/expired
            # taxpayer JWT (distinct from GSTN AUTH/TEC codes inside HTTP 200).
            body_snip = (resp.text or "").strip().replace("\n", " ")[:240]
            detail = f"HTTP {resp.status_code} on {path}"
            if body_snip:
                detail = f"{detail}: {body_snip}"
            raise FilingAuthError(detail)
        if resp.status_code != 200:

            raise FilingApiError(
                f"HTTP {resp.status_code} on {path}: {resp.text[:300]}",
                status_code=resp.status_code,
            )

        try:
            envelope = resp.json()
        except Exception as exc:
            raise FilingApiError(f"Invalid JSON from {path}: {exc}") from exc
        if not isinstance(envelope, dict):
            raise FilingApiError(f"Unexpected envelope type from {path}")

        data = envelope.get("data")
        if require_gstn_success:
            err_cd, err_msg = _gstn_error(data if isinstance(data, dict) else None)
            if err_msg:
                raise FilingGstnError(
                    err_msg,
                    error_cd=err_cd,
                    envelope=envelope,
                )
        return envelope


def get_filing_client() -> SandboxFilingClient:
    """Factory using env credentials."""
    return SandboxFilingClient()
