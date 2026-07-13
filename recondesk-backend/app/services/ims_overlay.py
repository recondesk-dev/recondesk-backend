"""IMS status overlay onto GSTR matcher rows.

Fetches taxpayer IMS invoices via SandboxGSTClient and maps them onto GSTR
records by ``(supplier_gstin, normalized_invoice_number)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.services.matcher import normalize_invoice
from app.services.sandbox_gst_client import (
    IMS_STATUSES,
    IMSInvoice,
    IMSInvoiceCountResponse,
    SandboxClientError,
    make_sandbox_client,
)

_log = logging.getLogger(__name__)

# Sections used for reconcile overlay (exclude nothing cheap — ecom is fine).
OVERLAY_SECTIONS: tuple[str, ...] = (
    "B2B",
    "B2BA",
    "CN",
    "CNA",
    "DN",
    "DNA",
    "ECOM",
    "ECOMA",
)

DEFAULT_IMS_STATUS = "no_action_taken"

ImsStatusKey = tuple[str, str]  # (supplier_gstin_upper, invoice_number_normalized)


@dataclass
class ImsOverlayResult:
    """Result of an IMS fetch used by the HTTP route and reconcile worker."""

    counts: dict[str, dict[str, int]]
    status_counts: dict[str, int]
    invoices_fetched: int
    status_map: dict[ImsStatusKey, str]
    total_by_status: dict[str, int]

    @property
    def status_map_size(self) -> int:
        return len(self.status_map)


def ims_composite_key(supplier_gstin: str | None, invoice_number: str | None) -> ImsStatusKey:
    """Canonical overlay lookup key."""
    gstin = (supplier_gstin or "").strip().upper()
    inv = normalize_invoice(invoice_number)
    return (gstin, inv)


def build_ims_status_map(
    invoices: Iterable[IMSInvoice],
    *,
    return_period: str | None = None,
) -> dict[ImsStatusKey, str]:
    """Build ``(supplier_gstin, invoice_norm) → ims_status``.

    When ``return_period`` is set (MMYYYY), only invoices whose ``rtnprd``
    matches (or is empty) are included — empty rtnprd is kept so incomplete
    Sandbox payloads still overlay.
    """
    target = (return_period or "").strip()
    out: dict[ImsStatusKey, str] = {}
    for inv in invoices:
        if target:
            rtn = (inv.return_period or "").strip()
            if rtn and rtn != target:
                continue
        key = ims_composite_key(inv.supplier_gstin, inv.invoice_number)
        if not key[0] or not key[1]:
            continue
        status = inv.ims_status if inv.ims_status in IMS_STATUSES else DEFAULT_IMS_STATUS
        # Later sections / duplicates: keep first non-default if present.
        existing = out.get(key)
        if existing is None or (
            existing == DEFAULT_IMS_STATUS and status != DEFAULT_IMS_STATUS
        ):
            out[key] = status
    return out


def fetch_ims_invoices(access_token: str, gstin: str) -> list[IMSInvoice]:
    """Fetch IMS invoices for all overlay sections (soft-skip per section)."""
    client = make_sandbox_client(access_token=access_token)
    invoices: list[IMSInvoice] = []
    for section in OVERLAY_SECTIONS:
        try:
            resp = client.get_invoices(gstin=gstin, section=section)
            invoices.extend(resp.invoices)
        except SandboxClientError as exc:
            _log.warning(
                "IMS section fetch failed gstin=%s section=%s err=%s",
                gstin,
                section,
                exc,
            )
        except Exception as exc:
            _log.warning(
                "IMS section fetch unexpected error gstin=%s section=%s err=%s",
                gstin,
                section,
                exc,
            )
    return invoices


def fetch_ims_overlay(
    access_token: str,
    gstin: str,
    year: int,
    month: int,
) -> ImsOverlayResult:
    """Fetch invoice counts + list and build a composite status map."""
    client = make_sandbox_client(access_token=access_token)
    count_resp: IMSInvoiceCountResponse = client.get_invoice_count(
        gstin=gstin, year=year, month=month
    )
    invoices = fetch_ims_invoices(access_token, gstin)
    rtnprd = f"{month:02d}{year}"
    status_map = build_ims_status_map(invoices, return_period=rtnprd)
    return ImsOverlayResult(
        counts=count_resp.counts,
        status_counts=_status_counts_from_map(status_map),
        invoices_fetched=len(invoices),
        status_map=status_map,
        total_by_status=count_resp.total_by_status(),
    )


def apply_ims_status_to_matcher_rows(
    gstr_records: list[dict[str, Any]],
    status_map: dict[ImsStatusKey, str],
) -> int:
    """Mutate matcher rows in place with ``ims_status``. Returns hit count."""
    hits = 0
    for rec in gstr_records:
        inv = (
            rec.get("invoice_number")
            or rec.get("invoice_number_normalized")
            or ""
        )
        key = ims_composite_key(rec.get("supplier_gstin"), str(inv))
        if key in status_map:
            rec["ims_status"] = status_map[key]
            hits += 1
        else:
            rec["ims_status"] = rec.get("ims_status") or DEFAULT_IMS_STATUS
    return hits


def apply_ims_status_to_record_data(
    raw_by_id: dict[str, dict[str, Any]],
    matcher_rows: list[dict[str, Any]],
) -> None:
    """Mirror matcher ``ims_status`` onto ``gstr_raw_by_id`` record_data blobs."""
    for rec in matcher_rows:
        rid = str(rec.get("id") or "")
        if not rid or rid not in raw_by_id:
            continue
        rd = raw_by_id[rid]
        if isinstance(rd, dict):
            rd["ims_status"] = rec.get("ims_status") or DEFAULT_IMS_STATUS


def _status_counts_from_map(status_map: dict[ImsStatusKey, str]) -> dict[str, int]:
    counts = {s: 0 for s in sorted(IMS_STATUSES)}
    for status in status_map.values():
        counts[status] = counts.get(status, 0) + 1
    return counts


def _parse_token_expiry(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def try_fetch_ims_status_map_for_client(
    sb: Any,
    client_gstin_id: str,
    *,
    year: int,
    month: int,
) -> Optional[dict[ImsStatusKey, str]]:
    """Worker helper: load GSTN token and fetch IMS map, or return None on soft-fail."""
    cid = (client_gstin_id or "").strip()
    if not cid:
        return None
    try:
        res = (
            sb.table("client_gstins")
            .select("id, gstin, gstn_access_token, gstn_token_expiry")
            .eq("id", cid)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        _log.warning("IMS overlay: client_gstins load failed id=%s err=%s", cid, exc)
        return None

    rows = res.data or []
    if not rows:
        _log.info("IMS overlay: no client_gstins row id=%s", cid)
        return None

    row = rows[0]
    access_token = row.get("gstn_access_token")
    gstin = str(row.get("gstin") or "").strip()
    if not access_token or not gstin:
        _log.info(
            "IMS overlay: skipped id=%s has_token=%s has_gstin=%s",
            cid,
            bool(access_token),
            bool(gstin),
        )
        return None

    expiry = _parse_token_expiry(row.get("gstn_token_expiry"))
    if expiry is not None and expiry <= datetime.now(timezone.utc):
        _log.info("IMS overlay: token expired id=%s expiry=%s", cid, expiry.isoformat())
        return None

    try:
        result = fetch_ims_overlay(str(access_token), gstin, year, month)
        _log.info(
            "IMS overlay fetched id=%s gstin=%s invoices=%d map_size=%d",
            cid,
            gstin,
            result.invoices_fetched,
            result.status_map_size,
        )
        return result.status_map
    except Exception as exc:
        _log.warning(
            "IMS overlay fetch failed id=%s gstin=%s err=%s",
            cid,
            gstin,
            exc,
        )
        return None
