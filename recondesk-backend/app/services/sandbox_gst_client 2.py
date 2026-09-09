"""Sandbox.co.in GST API client.

Authenticated client for fetching:
- IMS (Invoice Management System) invoice status via GET /gst/compliance/tax-payer/invoices
- IMS invoice counts via GET /gst/compliance/tax-payer/invoices/count
- IMS save invoice status via POST /gst/compliance/tax-payer/invoices/status/save
- IMS check status via GET /gst/compliance/tax-payer/invoices/status
- GSTR-2B document via GET /gst/compliance/tax-payer/gstrs/gstr-2b/:year/:month

Design goals
------------
- Single source of truth for the Sandbox base URL and auth headers.
- All errors are translated into typed exceptions or clean sentinel values —
  callers never need to inspect raw HTTP status codes.
- The GSTR-2B method unwraps the Sandbox envelope and returns a dict that is
  directly accepted by the existing ``parse_gstr2b`` parser (no duplication).
- The IMS method returns a lightweight ``IMSResponse`` dataclass; helpers on
  that class translate the raw payload into the canonical per-invoice status
  dict used by the reconciliation pipeline.
- The RET2B1023 "not filed" error code is treated as a clean sentinel
  (``Gstr2bNotFiledError``) rather than a crash, so the frontend can display
  "GSTR-2B not available" gracefully.

Environment variables
---------------
SANDBOX_API_KEY   — required, never hardcode.
SANDBOX_BASE_URL  — optional override; defaults to https://api.sandbox.co.in
SANDBOX_API_VERSION — optional override; defaults to 1.0.0
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://api.sandbox.co.in"
_DEFAULT_API_VERSION = "1.0.0"

# Sandbox error codes we handle explicitly.
_ERR_GSTR2B_NOT_FILED = "RET2B1023"      # GSTR-2B not yet filed for the period.
_ERR_GSTR2B_PROCESSING = "RET2B1024"     # Still being generated (status_cd == 3).

# Valid section values for the IMS invoices endpoint.
IMS_SECTIONS = frozenset({"B2B", "B2BA", "CN", "CNA", "DN", "DNA", "ECOM", "ECOMA"})

# Valid status filter values.
IMS_STATUSES = frozenset({"accepted", "rejected", "pending", "no_action_taken"})

# Valid action values for the save-invoice-status endpoint.
# These map to GSTN action codes: A = accept, R = reject, P = pending.
IMS_ACTIONS = frozenset({"accept", "reject", "pending"})
_ACTION_CODE_MAP: dict[str, str] = {
    "accept": "A",
    "reject": "R",
    "pending": "P",
}

# Mapping from Sandbox "action" field → canonical IMS status string.
# Sandbox IMS API uses these action codes to convey the taxpayer's IMS decision.
# "A" = Accepted, "R" = Rejected, "P" = Pending, "" / None = No action taken.
_ACTION_TO_STATUS: dict[str, str] = {
    "A": "accepted",
    "R": "rejected",
    "P": "pending",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SandboxClientError(Exception):
    """Base class for all Sandbox client errors."""


class SandboxAuthError(SandboxClientError):
    """Authentication failed — check SANDBOX_API_KEY in environment."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        super().__init__(
            f"Sandbox API authentication failed (HTTP {status_code}). "
            f"Verify SANDBOX_API_KEY is correct. Detail: {detail}"
        )


class SandboxRateLimitError(SandboxClientError):
    """Sandbox rate limit hit (HTTP 429)."""

    def __init__(self, retry_after: Optional[str] = None) -> None:
        self.retry_after = retry_after
        msg = "Sandbox API rate limit exceeded."
        if retry_after:
            msg += f" Retry after {retry_after}s."
        super().__init__(msg)


class SandboxApiError(SandboxClientError):
    """Unexpected API error (non-200 status or error body)."""

    def __init__(self, status_code: int, body: Any = None) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(
            f"Sandbox API returned HTTP {status_code}. Body: {body!r}"
        )


class Gstr2bNotFiledError(SandboxClientError):
    """GSTR-2B has not been filed for the requested period (RET2B1023).

    This is NOT an error in the application — the supplier simply hasn't filed
    yet.  The frontend should display a "GSTR-2B not available" message.
    """

    def __init__(self, gstin: str, year: int, month: int) -> None:
        self.gstin = gstin
        self.year = year
        self.month = month
        super().__init__(
            f"GSTR-2B not filed yet for GSTIN={gstin} period={year}-{month:02d}."
        )


class Gstr2bStillProcessingError(SandboxClientError):
    """GSTR-2B is still being generated (status_cd == 3 / RET2B1024).

    Callers should retry after a delay, paginating with file_number.
    """

    def __init__(self, gstin: str, year: int, month: int, file_number: Optional[int] = None) -> None:
        self.gstin = gstin
        self.year = year
        self.month = month
        self.file_number = file_number
        super().__init__(
            f"GSTR-2B still processing for GSTIN={gstin} period={year}-{month:02d}. "
            f"file_number={file_number}"
        )


# ---------------------------------------------------------------------------
# IMS response model
# ---------------------------------------------------------------------------

@dataclass
class IMSInvoice:
    """Normalised representation of a single IMS invoice entry."""

    invoice_number: str
    invoice_date: str                 # raw string from API, e.g. "05-11-2024"
    supplier_gstin: str               # stin field
    taxable_value: float              # txval
    invoice_value: float              # val
    igst: float                       # iamt
    cgst: float                       # camt
    sgst: float                       # samt
    cess: float                       # cess
    section: str                      # e.g. "B2B", "CN"
    ims_status: str                   # accepted / rejected / pending / no_action_taken
    return_period: str                # rtnprd raw string from API
    source_form: str                  # srcform, e.g. "R1"
    source_filing_status: str         # srcfilstatus
    pos: str                          # place of supply
    is_pending_action_blocked: bool   # ispendactblocked == "Y"
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class IMSResponse:
    """Container for all IMS invoices returned by one API call."""

    invoices: list = field(default_factory=list)
    raw_payload: dict = field(default_factory=dict, repr=False)

    # ---- convenience aggregations ----------------------------------------

    def by_status(self) -> dict:
        """Group invoices by IMS status."""
        groups: dict = {
            "accepted": [],
            "rejected": [],
            "pending": [],
            "no_action_taken": [],
        }
        for inv in self.invoices:
            groups.setdefault(inv.ims_status, []).append(inv)
        return groups

    def status_counts(self) -> dict:
        """Return count per IMS status bucket."""
        return {k: len(v) for k, v in self.by_status().items()}

    def as_invoice_status_map(self) -> dict:
        """Return a mapping of normalized_invoice_number → ims_status.

        This is the format consumed by the reconciliation pipeline when
        overlaying IMS status onto match results.  Invoice numbers are
        upper-cased and stripped for consistent lookup.
        """
        return {
            inv.invoice_number.strip().upper(): inv.ims_status
            for inv in self.invoices
        }


# ---------------------------------------------------------------------------
# IMS invoice count response model
# ---------------------------------------------------------------------------

@dataclass
class IMSInvoiceCountResponse:
    """Container for invoice counts by section and status.

    ``counts`` is a dict of section → {status → count}, e.g.::

        {
            "b2b": {"accept": 5, "pending": 3, "reject": 1, "noaction": 12},
            "b2ba": {"accept": 0, "pending": 0, "reject": 0, "noaction": 0},
            ...
        }
    """

    counts: dict[str, dict[str, int]]
    raw_payload: dict = field(default_factory=dict, repr=False)

    def total_by_status(self) -> dict[str, int]:
        """Aggregate counts across all sections, grouped by status."""
        totals: dict[str, int] = {}
        for section_counts in self.counts.values():
            for status, count in section_counts.items():
                totals[status] = totals.get(status, 0) + count
        return totals

    def total(self) -> int:
        """Return the grand total invoice count across all sections and statuses."""
        return sum(
            count
            for section_counts in self.counts.values()
            for count in section_counts.values()
        )


# ---------------------------------------------------------------------------
# IMS save-status response model
# ---------------------------------------------------------------------------

@dataclass
class IMSSaveStatusResponse:
    """Response from the save-invoice-status endpoint.

    The save operation is asynchronous — ``reference_id`` must be polled
    via ``check_invoice_status()`` to determine the final outcome.
    """

    reference_id: str
    transaction_id: str
    raw_payload: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# IMS check-status response model
# ---------------------------------------------------------------------------

@dataclass
class IMSCheckStatusResponse:
    """Result of polling an async save/reset invoice-status action.

    Attributes
    ----------
    status_cd:
        Processing status code — "P" (processed), "PE" (processed with errors),
        "ER" (error / schema validation failure), "IP" (in progress).
    trans_type_cd:
        Transaction type — "SAV" for save, "RST" for reset.
    processed_count:
        Number of invoices successfully processed.
    error_count:
        Number of invoices that failed.
    error_report:
        Per-section error details (if any).
    error_code:
        Top-level error code from GSTN (empty string if none).
    error_message:
        Top-level error message from GSTN (empty string if none).
    """

    status_cd: str
    trans_type_cd: str
    processed_count: int
    error_count: int
    error_report: dict = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    raw_payload: dict = field(default_factory=dict, repr=False)

    @property
    def is_complete(self) -> bool:
        """Return True if the operation has finished (success or failure)."""
        return self.status_cd in ("P", "PE", "ER")

    @property
    def has_errors(self) -> bool:
        """Return True if errors were reported."""
        return self.status_cd in ("PE", "ER") or self.error_count > 0


# ---------------------------------------------------------------------------
# GSTR-2B response model
# ---------------------------------------------------------------------------

@dataclass
class Gstr2bResponse:
    """Thin wrapper around the GSTR-2B payload.

    ``gstn_payload`` is the dict that should be passed directly to
    ``parse_gstr2b`` — it already conforms to the GSTN GSTR-2B JSON schema
    that the parser expects (the Sandbox envelope has been stripped).
    """

    gstn_payload: dict          # ready for parse_gstr2b()
    period_year: int
    period_month: int
    gstin: str
    raw_payload: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_ims_status(action: Optional[str]) -> str:
    """Map a Sandbox IMS ``action`` code to a canonical status string."""
    if not action:
        return "no_action_taken"
    return _ACTION_TO_STATUS.get(action.upper(), "no_action_taken")


def _parse_ims_section(
    section_key: str,
    entries: list,
) -> list:
    """Parse a single section (b2b / cn / dn / …) from the IMS data payload."""
    result = []
    section_label = section_key.upper()

    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("IMS: skipping non-dict entry in section %s", section_key)
            continue

        inv_number = str(entry.get("inum") or "").strip()
        if not inv_number:
            logger.warning("IMS: skipping entry with missing inum in section %s", section_key)
            continue

        # Prefer explicit ims_status if Sandbox includes it; fall back to
        # deriving it from the "action" field.
        raw_status = entry.get("ims_status")
        if raw_status and raw_status in IMS_STATUSES:
            status = raw_status
        else:
            status = _normalize_ims_status(entry.get("action"))

        result.append(
            IMSInvoice(
                invoice_number=inv_number,
                invoice_date=str(entry.get("idt") or ""),
                supplier_gstin=str(entry.get("stin") or ""),
                taxable_value=float(entry.get("txval") or 0),
                invoice_value=float(entry.get("val") or 0),
                igst=float(entry.get("iamt") or 0),
                cgst=float(entry.get("camt") or 0),
                sgst=float(entry.get("samt") or 0),
                cess=float(entry.get("cess") or 0),
                section=section_label,
                ims_status=status,
                return_period=str(entry.get("rtnprd") or ""),
                source_form=str(entry.get("srcform") or ""),
                source_filing_status=str(entry.get("srcfilstatus") or ""),
                pos=str(entry.get("pos") or ""),
                is_pending_action_blocked=str(entry.get("ispendactblocked") or "N").upper() == "Y",
                raw=entry,
            )
        )
    return result


def _unwrap_sandbox_envelope(raw: dict) -> dict:
    """Extract the inner payload from the Sandbox API response envelope.

    Sandbox wraps all responses in::

        {
            "code": 200,
            "data": { <actual payload> },
            "timestamp": ...,
            "transaction_id": "..."
        }

    Raises ``SandboxApiError`` if the outer structure is unexpected.
    """
    if not isinstance(raw, dict):
        raise SandboxApiError(0, "Response is not a JSON object")
    if raw.get("code") not in (200, "200"):
        raise SandboxApiError(int(raw.get("code", 0)), raw)
    data = raw.get("data")
    if data is None:
        raise SandboxApiError(200, "Response missing 'data' key")
    return data


def _check_status_cd(inner: dict, gstin: str, year: int, month: int, file_number: Optional[int]) -> None:
    """Raise appropriate exceptions based on GSTN status_cd inside the response.

    status_cd meanings (GSTN convention):
        "1" — Data available.
        "2" — No data available (GSTR-2B not filed or period empty).
        "3" — Data being generated; caller should retry with file_number.
    """
    status_cd = str(inner.get("status_cd", "1"))
    if status_cd == "2":
        raise Gstr2bNotFiledError(gstin, year, month)
    if status_cd == "3":
        raise Gstr2bStillProcessingError(gstin, year, month, file_number)


def _build_required_headers(api_key: str, access_token: Optional[str], api_version: str) -> dict:
    """Assemble Sandbox request headers."""
    headers: dict = {
        "x-api-key": api_key,
        "x-api-version": api_version,
        "Accept": "application/json",
    }
    if access_token:
        headers["authorization"] = access_token
    return headers


# ---------------------------------------------------------------------------
# Main client class
# ---------------------------------------------------------------------------

class SandboxGSTClient:
    """Authenticated HTTP client for the Sandbox.co.in GST API.

    Instantiate once and reuse.  The client is synchronous (uses ``httpx``
    sync transport) to match the existing service layer.

    Parameters
    ----------
    api_key:
        Sandbox API key. Defaults to ``SANDBOX_API_KEY`` env var.
    access_token:
        JWT access token obtained from the Sandbox /authenticate endpoint.
        Required for taxpayer-level endpoints (IMS, GSTR-2B).
        Defaults to ``SANDBOX_ACCESS_TOKEN`` env var if set.
    base_url:
        Override the base URL. Defaults to ``SANDBOX_BASE_URL`` env var or
        ``https://api.sandbox.co.in``.
    api_version:
        Override the x-api-version header. Defaults to
        ``SANDBOX_API_VERSION`` env var or ``1.0.0``.
    timeout:
        HTTP timeout in seconds. Default: 30.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
        api_version: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("SANDBOX_API_KEY") or ""
        if not self._api_key:
            raise SandboxAuthError(0, "SANDBOX_API_KEY not set in environment")

        self._access_token: Optional[str] = (
            access_token or os.environ.get("SANDBOX_ACCESS_TOKEN") or None
        )
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
        self._http = httpx.Client(timeout=self._timeout)

    # ---- lifecycle -------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> "SandboxGSTClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ---- internal HTTP ---------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """Execute GET request and return parsed JSON body.

        Translates HTTP errors into typed exceptions.
        """
        url = f"{self._base_url}{path}"
        headers = _build_required_headers(
            self._api_key, self._access_token, self._api_version
        )
        logger.debug("SandboxGST GET %s params=%s", url, params)

        try:
            resp = self._http.get(url, headers=headers, params=params or {})
        except httpx.TimeoutException as exc:
            raise SandboxClientError(
                f"Request timed out after {self._timeout}s: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise SandboxClientError(f"Network error: {exc}") from exc

        logger.debug("SandboxGST response: status=%s url=%s", resp.status_code, url)

        if resp.status_code in (401, 403):
            raise SandboxAuthError(resp.status_code, resp.text[:200])
        if resp.status_code == 429:
            raise SandboxRateLimitError(resp.headers.get("Retry-After"))
        if resp.status_code != 200:
            raise SandboxApiError(resp.status_code, resp.text[:500])

        try:
            return resp.json()
        except Exception as exc:
            raise SandboxApiError(resp.status_code, f"Invalid JSON: {exc}") from exc

    def _post(self, path: str, json_body: dict) -> dict:
        """Execute POST request and return parsed JSON body.

        Translates HTTP errors into typed exceptions.  Logs the full
        request and response for audit purposes (write operations).
        """
        url = f"{self._base_url}{path}"
        headers = _build_required_headers(
            self._api_key, self._access_token, self._api_version
        )
        headers["Content-Type"] = "application/json"

        logger.info("SandboxGST POST %s body=%r", url, json_body)

        try:
            resp = self._http.post(url, headers=headers, json=json_body)
        except httpx.TimeoutException as exc:
            raise SandboxClientError(
                f"Request timed out after {self._timeout}s: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise SandboxClientError(f"Network error: {exc}") from exc

        logger.info(
            "SandboxGST POST response: status=%s url=%s body=%s",
            resp.status_code,
            url,
            resp.text[:2000],
        )

        if resp.status_code in (401, 403):
            raise SandboxAuthError(resp.status_code, resp.text[:200])
        if resp.status_code == 429:
            raise SandboxRateLimitError(resp.headers.get("Retry-After"))
        if resp.status_code != 200:
            raise SandboxApiError(resp.status_code, resp.text[:500])

        try:
            return resp.json()
        except Exception as exc:
            raise SandboxApiError(resp.status_code, f"Invalid JSON: {exc}") from exc

    # ---- public methods --------------------------------------------------

    def get_invoice_count(
        self,
        gstin: str,
        year: int,
        month: int,
    ) -> IMSInvoiceCountResponse:
        """Fetch IMS invoice counts by section and status.

        Calls ``GET /gst/compliance/tax-payer/invoices/count``.

        Parameters
        ----------
        gstin:
            The buyer's GSTIN.
        year:
            4-digit return year (e.g. 2024).
        month:
            1–12 return month.

        Returns
        -------
        IMSInvoiceCountResponse
            Counts grouped by section (b2b, b2ba, …) and status
            (accept, pending, reject, noaction).

        Raises
        ------
        SandboxAuthError, SandboxRateLimitError, SandboxApiError
        """
        params: dict = {
            "gstin": gstin,
            "ret_period": f"{month:02d}{year}",
        }

        logger.info(
            "SandboxGST: fetching IMS invoice count gstin=%s year=%d month=%02d",
            gstin,
            year,
            month,
        )

        raw = self._get("/gst/compliance/tax-payer/invoices/count", params=params)
        inner = _unwrap_sandbox_envelope(raw)

        # inner structure: {"data": {"b2b": {"accept": N, ...}, ...}, "status_cd": "1"}
        count_data = inner.get("data") if isinstance(inner, dict) and "data" in inner else inner

        counts: dict[str, dict[str, int]] = {}
        if isinstance(count_data, dict):
            for section_key, status_map in count_data.items():
                if isinstance(status_map, dict):
                    counts[section_key] = {
                        k: int(v) for k, v in status_map.items()
                        if isinstance(v, (int, float, str))
                    }

        logger.info(
            "SandboxGST: IMS invoice count fetched gstin=%s sections=%s",
            gstin,
            list(counts.keys()),
        )
        return IMSInvoiceCountResponse(counts=counts, raw_payload=raw)

    def get_invoices(
        self,
        gstin: str,
        section: str,
        status: Optional[str] = None,
    ) -> IMSResponse:
        """Fetch IMS invoice list for a taxpayer.

        Parameters
        ----------
        gstin:
            The buyer's GSTIN.
        section:
            One of: B2B, B2BA, CN, CNA, DN, DNA, ECOM, ECOMA.
        status:
            Optional filter: accepted | rejected | pending | no_action_taken.
            If omitted, all statuses are returned.

        Returns
        -------
        IMSResponse
            Parsed IMS data with convenience aggregation methods.

        Raises
        ------
        SandboxAuthError, SandboxRateLimitError, SandboxApiError
        """
        section_upper = section.upper()
        if section_upper not in IMS_SECTIONS:
            raise ValueError(
                f"Invalid section '{section}'. Must be one of: {sorted(IMS_SECTIONS)}"
            )
        if status is not None and status not in IMS_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {sorted(IMS_STATUSES)}"
            )

        params: dict = {"section": section_upper}
        if status:
            params["status"] = status

        logger.info(
            "SandboxGST: fetching IMS invoices gstin=%s section=%s status=%s",
            gstin,
            section_upper,
            status or "all",
        )

        raw = self._get("/gst/compliance/tax-payer/invoices", params=params)
        inner = _unwrap_sandbox_envelope(raw)

        # inner may be {"data": {...sections...}, "status_cd": "1"}
        # or directly the sections dict depending on Sandbox plan/version.
        sections_data = inner.get("data") if isinstance(inner, dict) and "data" in inner else inner

        invoices = []
        if isinstance(sections_data, dict):
            section_key_map = {
                "B2B": "b2b",
                "B2BA": "b2ba",
                "CN": "cn",
                "CNA": "cna",
                "DN": "dn",
                "DNA": "dna",
                "ECOM": "ecom",
                "ECOMA": "ecoma",
            }
            target_key = section_key_map.get(section_upper, section_upper.lower())
            entries = sections_data.get(target_key, [])
            if isinstance(entries, list):
                invoices = _parse_ims_section(target_key, entries)
            else:
                logger.warning(
                    "IMS section '%s' is not a list: %s", target_key, type(entries)
                )

        logger.info(
            "SandboxGST: IMS fetched %d invoices gstin=%s section=%s",
            len(invoices),
            gstin,
            section_upper,
        )
        return IMSResponse(invoices=invoices, raw_payload=raw)

    def save_invoice_status(
        self,
        gstin: str,
        invoice_data: dict[str, list[dict]],
        action: str,
        remarks: Optional[str] = None,
    ) -> IMSSaveStatusResponse:
        """Save (accept/reject/pending) status for one or more invoices.

        Calls ``POST /gst/compliance/tax-payer/invoices/status/save``.

        This is a **write operation** — the full request and response are logged
        at INFO level for audit purposes.  The operation is asynchronous;
        use the returned ``reference_id`` with ``check_invoice_status()``
        to poll for completion.

        Parameters
        ----------
        gstin:
            The buyer/recipient GSTIN (rtin field in the request).
        invoice_data:
            Invoice payload organized by section, e.g.::

                {
                    "b2b": [
                        {
                            "stin": "24MAYAS0100J1JD",
                            "inum": "INV-001",
                            "inv_typ": "R",
                            "srcform": "R1",
                            "rtnprd": "112024",
                            "idt": "05-11-2024",
                            "val": 1000,
                            "pos": "24",
                            "txval": 100,
                            "iamt": 0,
                            "camt": 9,
                            "samt": 9,
                            "cess": 0,
                            "prev_status": "N",
                        }
                    ]
                }

            The ``action`` and optional ``remarks`` will be injected into
            each invoice entry automatically.
        action:
            One of: ``"accept"``, ``"reject"``, ``"pending"``.
        remarks:
            Optional remark string, visible on the supplier's dashboard
            for reject/pending actions.

        Returns
        -------
        IMSSaveStatusResponse
            Contains ``reference_id`` for polling via ``check_invoice_status()``.

        Raises
        ------
        ValueError
            If ``action`` is not one of the valid IMS actions.
        SandboxAuthError, SandboxRateLimitError, SandboxApiError
        """
        action_lower = action.lower()
        if action_lower not in IMS_ACTIONS:
            raise ValueError(
                f"Invalid action '{action}'. Must be one of: {sorted(IMS_ACTIONS)}"
            )

        action_code = _ACTION_CODE_MAP[action_lower]

        # Inject the action code (and optional remarks) into every invoice entry.
        enriched_data: dict[str, list[dict]] = {}
        for section_key, entries in invoice_data.items():
            enriched_entries = []
            for entry in entries:
                enriched_entry = {**entry, "action": action_code}
                if remarks is not None:
                    enriched_entry["remarks"] = remarks
                enriched_entries.append(enriched_entry)
            enriched_data[section_key] = enriched_entries

        body: dict = {
            "rtin": gstin,
            "reqtyp": "SAVE",
            "invdata": enriched_data,
        }

        logger.info(
            "SandboxGST: saving IMS invoice status gstin=%s action=%s sections=%s",
            gstin,
            action_lower,
            list(enriched_data.keys()),
        )

        raw = self._post("/gst/compliance/tax-payer/invoices/status/save", json_body=body)
        inner = _unwrap_sandbox_envelope(raw)

        # inner: {"data": {"reference_id": "..."}, "status_cd": "1"}
        data = inner.get("data", inner) if isinstance(inner, dict) else inner
        reference_id = ""
        if isinstance(data, dict):
            reference_id = str(data.get("reference_id", ""))

        if not reference_id:
            raise SandboxApiError(
                200,
                f"Save-status response missing 'reference_id': {raw!r}",
            )

        transaction_id = str(raw.get("transaction_id", ""))

        logger.info(
            "SandboxGST: IMS save-status initiated gstin=%s reference_id=%s",
            gstin,
            reference_id,
        )
        return IMSSaveStatusResponse(
            reference_id=reference_id,
            transaction_id=transaction_id,
            raw_payload=raw,
        )

    def check_invoice_status(
        self,
        reference_id: str,
    ) -> IMSCheckStatusResponse:
        """Poll the async result of a save/reset invoice-status action.

        Calls ``GET /gst/compliance/tax-payer/invoices/status``.

        Parameters
        ----------
        reference_id:
            The ``reference_id`` returned by ``save_invoice_status()``.

        Returns
        -------
        IMSCheckStatusResponse
            Contains processing status, counts, and any per-invoice errors.
            Check ``.is_complete`` to know whether polling should continue.

        Raises
        ------
        SandboxAuthError, SandboxRateLimitError, SandboxApiError
        """
        params: dict = {"reference_id": reference_id}

        logger.info(
            "SandboxGST: checking IMS invoice status reference_id=%s",
            reference_id,
        )

        raw = self._get("/gst/compliance/tax-payer/invoices/status", params=params)
        inner = _unwrap_sandbox_envelope(raw)

        # inner: {"data": {"status_cd": "P", "proc_cnt": "8", ...}, "status_cd": "1"}
        data = inner.get("data", inner) if isinstance(inner, dict) else inner
        if not isinstance(data, dict):
            data = {}

        result = IMSCheckStatusResponse(
            status_cd=str(data.get("status_cd", "")),
            trans_type_cd=str(data.get("transTypCd", "")),
            processed_count=int(data.get("proc_cnt", 0)),
            error_count=int(data.get("err_cnt", 0)),
            error_report=data.get("error_report", {}),
            error_code=str(data.get("err_cd", "")),
            error_message=str(data.get("err_msg", "")),
            raw_payload=raw,
        )

        logger.info(
            "SandboxGST: IMS status check reference_id=%s status=%s processed=%d errors=%d",
            reference_id,
            result.status_cd,
            result.processed_count,
            result.error_count,
        )
        return result

    def get_gstr2b(
        self,
        gstin: str,
        year: int,
        month: int,
        file_number: Optional[int] = None,
    ) -> Gstr2bResponse:
        """Fetch GSTR-2B document for a taxpayer.

        Parameters
        ----------
        gstin:
            Buyer's GSTIN.
        year:
            4-digit return year (e.g. 2024).
        month:
            1–12 return month.
        file_number:
            Pagination token for when status_cd == 3 (data still generating).

        Returns
        -------
        Gstr2bResponse
            ``gstn_payload`` on the response can be passed directly to
            ``parse_gstr2b()``.

        Raises
        ------
        Gstr2bNotFiledError
            When GSTR-2B has not been filed for the period (RET2B1023).
        Gstr2bStillProcessingError
            When the document is still being generated (status_cd == 3).
        SandboxAuthError, SandboxRateLimitError, SandboxApiError
        """
        path = f"/gst/compliance/tax-payer/gstrs/gstr-2b/{year}/{month:02d}"
        params: dict = {}
        if file_number is not None:
            params["file_number"] = file_number

        logger.info(
            "SandboxGST: fetching GSTR-2B gstin=%s year=%d month=%02d file_number=%s",
            gstin,
            year,
            month,
            file_number,
        )

        raw = self._get(path, params=params or None)
        inner = _unwrap_sandbox_envelope(raw)

        # Check GSTN status codes before parsing.
        _check_status_cd(inner, gstin, year, month, file_number)

        # Extract the GSTN-format payload.  Sandbox nests it under data.data.
        gstn_data = inner.get("data") if isinstance(inner, dict) else inner

        if not isinstance(gstn_data, dict):
            raise SandboxApiError(200, f"Unexpected GSTR-2B payload structure: {type(gstn_data)}")

        # The GSTN payload (from Sandbox) looks like:
        #   { "gstin": "...", "rtnprd": "...", "b2b": [...], ... }
        # Our parse_gstr2b() expects:
        #   { "data": { "gstin": "...", "rtnprd": "...", "b2b": [...] } }
        # Wrap it correctly if the "data" key is not already present.
        if "data" in gstn_data and isinstance(gstn_data["data"], dict):
            # Already in the parse_gstr2b-compatible shape.
            gstn_payload = gstn_data
        else:
            gstn_payload = {"data": gstn_data}

        # Ensure the buyer GSTIN is present in the inner data dict.
        inner_data = gstn_payload.get("data", {})
        if not inner_data.get("gstin"):
            inner_data["gstin"] = gstin

        logger.info(
            "SandboxGST: GSTR-2B fetched gstin=%s year=%d month=%02d",
            gstin,
            year,
            month,
        )
        return Gstr2bResponse(
            gstn_payload=gstn_payload,
            period_year=year,
            period_month=month,
            gstin=gstin,
            raw_payload=raw,
        )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_sandbox_client(**kwargs: Any) -> SandboxGSTClient:
    """Create a ``SandboxGSTClient`` from environment variables.

    All keyword arguments are forwarded to ``SandboxGSTClient.__init__``.
    Intended for use in FastAPI dependency injection or script entry points.

    Raises ``SandboxAuthError`` immediately if ``SANDBOX_API_KEY`` is not set.
    """
    return SandboxGSTClient(**kwargs)
