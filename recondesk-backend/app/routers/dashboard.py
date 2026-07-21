"""Dashboard aggregate endpoints: `/api/dashboard`."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends

from app.auth import get_current_active_user
from app.constants import RunStatus
from app.database import get_supabase, get_user_profile
from app.services.firm_access import list_accessible_client_gstin_ids
from app.utils.redis_cache import cache_get, cache_set

router = APIRouter()
_log = logging.getLogger(__name__)

_CHUNK = 120
_RUNS_CAP = 500
_ATTENTION_LIMIT = 5
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

_IMPORTING_STATUSES = frozenset(
    {
        "UPLOADING",
        "QUEUED",
        "GSTR_IMPORT_COMPLETE",
        "PURCHASE_IMPORT_COMPLETE",
        "DRAFT",
        "GSTR_UPLOADED",
        "PR_UPLOADED",
    }
)
_MATCHING_STATUSES = frozenset({"MATCHING", "PROCESSING", "READY"})


def _format_period_label(period: str) -> str:
    p = (period or "").strip()
    if len(p) == 7 and p[4] == "-":
        try:
            y = p[:4]
            mo = max(1, min(12, int(p[5:7]))) - 1
            return f"{_MONTHS[mo]} {y}"
        except ValueError:
            return p
    return p


def _map_ui_status(raw: str) -> str:
    u = (raw or "").strip().upper()
    if u == "COMPLETED":
        return "COMPLETE"
    if u == "FINAL":
        return "FINALIZED"
    if u == "FAILED":
        return "FAILED"
    if u in _MATCHING_STATUSES:
        return "MATCHING"
    if u == "PENDING":
        return "PENDING"
    if u in _IMPORTING_STATUSES:
        return "IMPORTING"
    return "PENDING"


def _paise_to_rupee(paise: Any) -> Optional[float]:
    if paise is None:
        return None
    try:
        n = float(paise)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return round(n) / 100.0


def _money_paise_from_row(
    row: dict[str, Any], top: Any, summary_keys: tuple[str, ...]
) -> Optional[int]:
    if isinstance(top, (int, float)) and not isinstance(top, bool) and top != 0:
        return int(top)
    rs = row.get("run_summary")
    if isinstance(rs, dict):
        for k in summary_keys:
            v = rs.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
    if isinstance(top, (int, float)) and not isinstance(top, bool):
        return int(top)
    return None


def _matched_itc_paise(rs: Any) -> Optional[int]:
    if not isinstance(rs, dict):
        return None
    for k in ("matched_itc_paise", "net_claimable_itc_paise", "total_gstr_itc_paise"):
        v = rs.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return None


def _infer_compliance_risk(
    missed_rupee: Optional[float],
    wrongful_rupee: Optional[float],
    ui_status: str,
) -> Optional[str]:
    if ui_status not in ("COMPLETE", "FINALIZED"):
        return None
    wr = wrongful_rupee or 0.0
    mi = missed_rupee or 0.0
    if wr >= 500_000:
        return "CRITICAL"
    if wr >= 100_000 or mi >= 2_000_000:
        return "HIGH"
    if mi >= 400_000:
        return "MEDIUM"
    return "LOW"


def _priority_score(
    ui_status: Optional[str],
    missed_itc: Optional[float],
    compliance_risk: Optional[str],
) -> int:
    if ui_status is None:
        return 10
    if ui_status == "FAILED":
        return 95
    if ui_status == "FINALIZED":
        return 0
    score = 0.0
    score += min(((missed_itc or 0.0) / 100_000.0) * 50.0, 50.0)
    risk_map = {"LOW": 0, "MEDIUM": 10, "HIGH": 20, "CRITICAL": 30}
    score += risk_map.get(compliance_risk or "LOW", 0)
    status_map = {
        "COMPLETE": 20,
        "PENDING": 10,
        "IMPORTING": 5,
        "MATCHING": 5,
    }
    score += status_map.get(ui_status, 0)
    return int(round(score))


def _firm_owner_id(sb, uid: str) -> str:
    prof = get_user_profile(uid) or {}
    role = (prof.get("role") or "staff").lower()
    if role == "admin":
        return uid
    # Staff: resolve via any assigned client, else fall back to uid
    try:
        res = (
            sb.table("client_gstins")
            .select("firm_owner_id")
            .eq("assigned_to", uid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if res.data:
            owner = str(res.data[0].get("firm_owner_id") or "").strip()
            if owner:
                return owner
    except Exception:
        _log.exception("dashboard firm owner lookup failed for %s", uid)
    return uid


def _count_team_members(sb, uid: str) -> int:
    owner_id = _firm_owner_id(sb, uid)
    ids: set[str] = set()
    try:
        res = (
            sb.table("team_members")
            .select("member_user_id")
            .eq("firm_owner_id", owner_id)
            .eq("is_active", True)
            .not_.is_("member_user_id", "null")
            .execute()
        )
        for row in res.data or []:
            mid = str(row.get("member_user_id") or "").strip()
            if mid:
                ids.add(mid)
    except Exception:
        _log.exception("dashboard team count failed")
    ids.add(uid)
    return len(ids)


def _list_slim_clients(sb, client_ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(client_ids), _CHUNK):
        chunk = client_ids[i : i + _CHUNK]
        try:
            res = (
                sb.table("client_gstins")
                .select("id, trade_name, gstin, legal_name")
                .in_("id", chunk)
                .eq("is_active", True)
                .execute()
            )
            out.extend(res.data or [])
        except Exception:
            _log.exception("dashboard clients chunk failed")
            raise
    return out


def _list_slim_runs(sb, client_ids: list[str], cap: int) -> list[dict[str, Any]]:
    """Fetch recent runs without matched-ITC payload backfill."""
    rows_out: list[dict[str, Any]] = []
    n_chunks = max(1, (len(client_ids) + _CHUNK - 1) // _CHUNK)
    per_chunk_cap = min(1000, max(cap, cap * 3 // n_chunks))
    for i in range(0, len(client_ids), _CHUNK):
        chunk = client_ids[i : i + _CHUNK]
        try:
            res = (
                sb.table("reconciliation_run")
                .select(
                    "id, client_gstin_id, period, status, created_at, "
                    "itc_at_risk, wrongful_itc, run_summary"
                )
                .in_("client_gstin_id", chunk)
                .order("created_at", desc=True)
                .limit(per_chunk_cap)
                .execute()
            )
            rows_out.extend(res.data or [])
        except Exception:
            _log.exception("dashboard runs chunk failed")
            raise
    rows_out.sort(
        key=lambda r: str(r.get("created_at") or ""),
        reverse=True,
    )
    return rows_out[:cap]


def _build_summary(
    clients: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    team_members: int,
) -> dict[str, Any]:
    pending_this_month = 0
    total_itc_protected = 0.0
    itc_protected_has_data = False

    for r in runs:
        ui = _map_ui_status(str(r.get("status") or ""))
        if ui in ("PENDING", "IMPORTING", "MATCHING"):
            pending_this_month += 1
        if ui == "FINALIZED":
            paise = _matched_itc_paise(r.get("run_summary"))
            if paise is not None:
                itc_protected_has_data = True
                rupee = _paise_to_rupee(paise)
                if rupee is not None:
                    total_itc_protected += rupee

    latest_by_client: dict[str, dict[str, Any]] = {}
    for r in runs:
        cid = str(r.get("client_gstin_id") or "").strip()
        if not cid:
            continue
        prev = latest_by_client.get(cid)
        if not prev or str(r.get("created_at") or "") > str(prev.get("created_at") or ""):
            latest_by_client[cid] = r

    failed_client_count = 0
    complete_ready_count = 0
    finalized_count = 0
    itc_at_risk = 0.0
    attention_candidates: list[dict[str, Any]] = []

    for c in clients:
        cid = str(c.get("id") or "").strip()
        trade = (
            str(c.get("trade_name") or c.get("legal_name") or c.get("gstin") or "Client")
            .strip()
        )
        lr = latest_by_client.get(cid)
        ui_status: Optional[str] = None
        missed_rupee: Optional[float] = None
        wrongful_rupee: Optional[float] = None
        compliance_risk: Optional[str] = None
        period_label: Optional[str] = None
        run_id: Optional[str] = None

        if lr:
            ui_status = _map_ui_status(str(lr.get("status") or ""))
            missed_paise = _money_paise_from_row(
                lr, lr.get("itc_at_risk"), ("itc_at_risk", "missed_itc_paise")
            )
            wrongful_paise = _money_paise_from_row(
                lr, lr.get("wrongful_itc"), ("wrongful_itc",)
            )
            missed_rupee = _paise_to_rupee(missed_paise)
            wrongful_rupee = _paise_to_rupee(wrongful_paise)
            compliance_risk = _infer_compliance_risk(
                missed_rupee, wrongful_rupee, ui_status
            )
            period_label = _format_period_label(str(lr.get("period") or ""))
            run_id = str(lr.get("id") or "").strip() or None

            if ui_status == "FAILED":
                failed_client_count += 1
            elif ui_status == "COMPLETE":
                complete_ready_count += 1
            elif ui_status == "FINALIZED":
                finalized_count += 1

            if missed_rupee is not None:
                itc_at_risk += missed_rupee

        score = _priority_score(ui_status, missed_rupee, compliance_risk)
        include = (
            ui_status is None
            or ui_status in ("FAILED", "COMPLETE", "PENDING")
        )
        if include:
            attention_candidates.append(
                {
                    "client_id": cid,
                    "trade_name": trade,
                    "gstin": str(c.get("gstin") or ""),
                    "run_id": run_id,
                    "status": ui_status,
                    "period": period_label,
                    "missed_itc": missed_rupee,
                    "compliance_risk": compliance_risk,
                    "priority_score": score,
                }
            )

    attention_candidates.sort(key=lambda x: int(x["priority_score"]), reverse=True)
    attention = attention_candidates[:_ATTENTION_LIMIT]

    total_clients = len(clients)
    show_all_finalized = (
        total_clients > 0
        and failed_client_count == 0
        and complete_ready_count == 0
        and finalized_count == total_clients
    )

    return {
        "total_clients": total_clients,
        "pending_this_month": pending_this_month,
        "ready_for_review": complete_ready_count,
        "failed_client_count": failed_client_count,
        "show_all_finalized_banner": show_all_finalized,
        "total_itc_protected": total_itc_protected,
        "itc_protected_has_data": itc_protected_has_data,
        "itc_at_risk": itc_at_risk,
        "team_members": team_members,
        "attention": attention,
    }


@router.get("/summary")
async def dashboard_summary(
    current_user: dict = Depends(get_current_active_user),
):
    """Lightweight portfolio snapshot for Quick Stats + Needs Attention.

    Never backfills matched ITC from full payloads — uses stored run_summary only.
    """
    user_id = str(current_user.get("id", "")).strip()
    cache_key = f"cache:dashboard:summary:v1:{user_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    sb = get_supabase()
    accessible = sorted(list_accessible_client_gstin_ids(sb, current_user))
    team_members = _count_team_members(sb, user_id)

    if not accessible:
        payload = _build_summary([], [], team_members)
        cache_set(cache_key, payload, ttl_seconds=30)
        return payload

    clients = _list_slim_clients(sb, accessible)
    # Preserve accessibility order stability by id set filter (inactive already filtered)
    client_ids = [str(c["id"]) for c in clients if c.get("id")]
    runs = _list_slim_runs(sb, client_ids, _RUNS_CAP) if client_ids else []
    payload = _build_summary(clients, runs, team_members)
    cache_set(cache_key, payload, ttl_seconds=30)
    return payload
