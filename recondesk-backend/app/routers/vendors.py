"""Firm-scoped vendor compliance scorecard API."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_active_user
from app.database import get_supabase, get_user_profile
from app.services.firm_access import list_accessible_client_gstin_ids
from app.services.normalizer import NormalizationError, normalize_gstin
from app.services.supplier_compliance_scorecard import SIGNAL_NOTES
from app.utils.audit import resolve_firm_id

_log = logging.getLogger(__name__)
router = APIRouter()

_SORT_COLS = frozenset(
    {
        "risk_score",
        "clients_touched_count",
        "mismatch_rate",
        "rule37_open_count",
        "late_filing_rate",
        "supplier_gstin_normalized",
        "total_invoices",
        "last_updated_at",
    }
)


def _firm_owner_id(sb, current_user: dict) -> str:
    fid = resolve_firm_id(sb, current_user)
    if fid:
        return fid
    uid = str(current_user.get("id") or "").strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing user id"
        )
    profile = get_user_profile(uid) or {}
    role = str(profile.get("role") or "").strip().lower()
    if role == "admin":
        return uid
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="could not resolve firm for user",
    )


def _is_admin(current_user: dict) -> bool:
    uid = str(current_user.get("id") or "").strip()
    profile = get_user_profile(uid) or {}
    return str(profile.get("role") or "").strip().lower() == "admin"


def _serialize_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "supplier_gstin": str(row.get("supplier_gstin_normalized") or "").strip(),
        "supplier_trade_name": str(row.get("supplier_trade_name") or "").strip(),
        "clients_touched_count": int(row.get("clients_touched_count") or 0),
        "client_gstin_ids": list(row.get("client_gstin_ids") or []),
        "total_invoices": int(row.get("total_invoices") or 0),
        "mismatch_invoice_count": int(row.get("mismatch_invoice_count") or 0),
        "mismatch_rate": float(row.get("mismatch_rate") or 0),
        "rule37_open_count": int(row.get("rule37_open_count") or 0),
        "rule37_at_risk_paise": int(row.get("rule37_at_risk_paise") or 0),
        "section_17_5_count": int(row.get("section_17_5_count") or 0),
        "late_filing_count": int(row.get("late_filing_count") or 0),
        "late_filing_rate": float(row.get("late_filing_rate") or 0),
        "pr_only_count": int(row.get("pr_only_count") or 0),
        "quarterly_filer_flag": bool(row.get("quarterly_filer_flag")),
        "risk_score": int(row.get("risk_score") or 0),
        "last_updated_at": row.get("last_updated_at"),
    }


from app.repositories.vendor_compliance import get_vendor_compliance_repository


@router.get("/scorecard")
async def list_vendor_scorecard(
    current_user: dict = Depends(get_current_active_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("risk_score"),
    order: str = Query("desc"),
    q: Optional[str] = Query(None, description="Supplier GSTIN prefix filter"),
):
    sb = get_supabase()
    firm_id = _firm_owner_id(sb, current_user)
    sort_col = sort if sort in _SORT_COLS else "risk_score"
    desc = str(order or "desc").lower() != "asc"
    prefix = str(q).strip().upper() if q and str(q).strip() else None

    # Aurora PRIMARY
    repo = get_vendor_compliance_repository()
    if repo is not None:
        try:
            client_filter = None
            if not _is_admin(current_user):
                allowed = list_accessible_client_gstin_ids(sb, current_user)
                if not allowed:
                    return {
                        "items": [],
                        "total": 0,
                        "limit": limit,
                        "offset": offset,
                        "signal_notes": SIGNAL_NOTES,
                    }
                client_filter = {str(x) for x in allowed}

            rows, total = repo.list_supplier_compliance_summary(
                firm_owner_id=firm_id,
                limit=limit,
                offset=offset,
                sort_by=sort_col,
                desc=desc,
                prefix=prefix,
                client_ids_filter=client_filter,
            )
            return {
                "items": [_serialize_summary(x) for x in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
                "signal_notes": SIGNAL_NOTES,
            }
        except Exception as exc:
            _log.warning("Aurora list_supplier_compliance_summary failed, falling back to Supabase: %s", exc)

    # Supabase FALLBACK
    query = (
        sb.table("supplier_compliance_summary")
        .select("*", count="exact")
        .eq("firm_owner_id", firm_id)
    )
    if prefix:
        query = query.ilike("supplier_gstin_normalized", f"{prefix}%")

    if not _is_admin(current_user):
        allowed = list_accessible_client_gstin_ids(sb, current_user)
        if not allowed:
            return {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "signal_notes": SIGNAL_NOTES,
            }
        raw = query.order(sort_col, desc=desc).limit(2000).execute()
        items = []
        for row in raw.data or []:
            cids = {str(x) for x in (row.get("client_gstin_ids") or [])}
            if cids & allowed:
                items.append(_serialize_summary(row))
        total = len(items)
        page = items[offset : offset + limit]
        return {
            "items": page,
            "total": total,
            "limit": limit,
            "offset": offset,
            "signal_notes": SIGNAL_NOTES,
        }

    r = (
        query.order(sort_col, desc=desc)
        .range(offset, offset + limit - 1)
        .execute()
    )
    items = [_serialize_summary(x) for x in (r.data or [])]
    total = int(r.count or len(items))
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "signal_notes": SIGNAL_NOTES,
    }


@router.get("/scorecard/{supplier_gstin}")
async def get_vendor_scorecard_detail(
    supplier_gstin: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    firm_id = _firm_owner_id(sb, current_user)
    try:
        gstin = normalize_gstin(supplier_gstin)
    except NormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid supplier GSTIN: {exc.reason}",
        ) from exc

    row = None
    repo = get_vendor_compliance_repository()
    if repo is not None:
        try:
            row = repo.get_supplier_compliance_summary(
                firm_owner_id=firm_id, supplier_gstin_normalized=gstin
            )
        except Exception as exc:
            _log.warning("Aurora get_supplier_compliance_summary failed, falling back to Supabase: %s", exc)

    if row is None:
        r = (
            sb.table("supplier_compliance_summary")
            .select("*")
            .eq("firm_owner_id", firm_id)
            .eq("supplier_gstin_normalized", gstin)
            .limit(1)
            .execute()
        )
        if not r.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="supplier not found"
            )
        row = r.data[0]
    client_ids = [str(x) for x in (row.get("client_gstin_ids") or [])]

    if not _is_admin(current_user):
        allowed = list_accessible_client_gstin_ids(sb, current_user)
        if not (set(client_ids) & allowed):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="supplier not found"
            )

    clients_out: list[dict[str, Any]] = []
    if client_ids:
        for i in range(0, len(client_ids), 100):
            chunk = client_ids[i : i + 100]
            cr = (
                sb.table("client_gstins")
                .select("id, gstin, trade_name, legal_name")
                .in_("id", chunk)
                .execute()
            )
            for c in cr.data or []:
                clients_out.append(
                    {
                        "client_gstin_id": str(c.get("id") or ""),
                        "gstin": str(c.get("gstin") or "").strip(),
                        "trade_name": str(
                            c.get("trade_name") or c.get("legal_name") or ""
                        ).strip(),
                    }
                )

    return {
        "supplier": _serialize_summary(row),
        "clients": clients_out,
        "signal_notes": SIGNAL_NOTES,
    }
