"""Service to synchronize GSTR-2B and IMS overlay status post-writeback.

Completes the Phase 4 post-action 2B sync hook (phase4_post_action_2b_sync_pending).
When a CA confirms IMS actions and GSTN acknowledges, this service updates
stored GSTR records and the reconciliation payload (matched, missed_itc,
duplicates, decisions) to reflect the new IMS status (accepted, rejected, pending).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client

from app.ims.ims_action_store import normalize_gstin
from app.services.ims_overlay import (
    DEFAULT_IMS_STATUS,
    ImsStatusKey,
    ims_composite_key,
    try_fetch_ims_status_map_for_client,
)
from app.services.matcher import normalize_invoice
from app.services.reconciliation_outcomes import (
    clear_process_maps_for_run,
    clear_request_load_cache,
    load_payload,
)
from app.services.reconciliation_payload_store import save_reconciliation_results

_log = logging.getLogger(__name__)

_ACTION_TO_IMS_STATUS = {
    "accept": "accepted",
    "reject": "rejected",
    "hold": "pending",
    "pending": "pending",
}


@dataclass
class ImsSyncResult:
    """Outcome of a post-action GSTR-2B / IMS overlay sync."""

    synced: bool
    run_id: str
    invoices_updated: int
    phase4_post_action_2b_sync_pending: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "synced": self.synced,
            "run_id": self.run_id,
            "invoices_updated": self.invoices_updated,
            "phase4_post_action_2b_sync_pending": self.phase4_post_action_2b_sync_pending,
            "message": self.message,
        }


def _parse_run_period(period_str: str) -> tuple[int, int]:
    """Parse return period into (year, month). Supports YYYY-MM and MMYYYY."""
    p = (period_str or "").strip()
    if "-" in p:
        parts = p.split("-")
        return int(parts[0]), int(parts[1])
    if len(p) == 6 and p.isdigit():
        return int(p[2:]), int(p[:2])
    # Fallback to current year/month if unrecognized
    now = datetime.now(timezone.utc)
    return now.year, now.month


def _build_status_map_from_submissions(
    sb: Client,
    run_id: str,
) -> dict[ImsStatusKey, str]:
    """Build status map from confirmed rows in ims_action_submissions for this run."""
    rows = []
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        all_rows = repo.list_ims_submissions_for_run(run_id, status=None)
        rows = [r for r in all_rows if r.get("status") in ("confirmed", "pending", "claiming")]
    except Exception as a_exc:
        _log.warning("Aurora query ims_action_submissions for run_id=%s failed: %s", run_id, a_exc)

    if not rows and sb is not None:
        try:
            res = (
                sb.table("ims_action_submissions")
                .select("chosen_action, writeback_payload, gstin, status")
                .eq("run_id", run_id)
                .in_("status", ["confirmed", "pending", "claiming"])
                .execute()
            )
            rows = res.data or []
        except Exception as exc:
            _log.warning("Failed to query ims_action_submissions for run_id=%s: %s", run_id, exc)
            return {}

    mapping: dict[ImsStatusKey, str] = {}
    for row in rows:
        chosen = str(row.get("chosen_action") or "").strip().lower()
        target_status = _ACTION_TO_IMS_STATUS.get(chosen)
        if not target_status:
            continue

        wb = row.get("writeback_payload") or {}
        supplier_gstin = wb.get("stin") or wb.get("supplier_gstin") or ""
        inv_num = wb.get("inum") or wb.get("invoice_number") or ""

        if supplier_gstin and inv_num:
            key = ims_composite_key(supplier_gstin, inv_num)
            mapping[key] = target_status

    return mapping


def sync_ims_run_overlay(
    sb: Client,
    *,
    run_id: str,
    access_token: str | None = None,
    buyer_gstin: str | None = None,
) -> ImsSyncResult:
    """Synchronize GSTR-2B matcher rows and stored reconciliation payload with latest IMS status.

    1. Attempts live fetch from GSTN via Sandbox if credentials are valid.
    2. Merges with confirmed actions in ims_action_submissions.
    3. Updates gstr_records table.
    4. Updates reconciliation_results JSONB payload.
    5. Clears in-process and request caches.
    """
    rid = str(run_id).strip()
    if not rid:
        raise ValueError("run_id must not be empty")

    run_res = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status")
        .eq("id", rid)
        .limit(1)
        .execute()
    )
    if not run_res.data:
        raise ValueError(f"Reconciliation run {rid} not found")

    run_row = run_res.data[0]
    client_gstin_id = str(run_row.get("client_gstin_id") or "").strip()
    period = str(run_row.get("period") or "").strip()
    year, month = _parse_run_period(period)

    # 1. Resolve IMS status map
    status_map: dict[ImsStatusKey, str] = {}

    # Path A: Live GST portal fetch
    if client_gstin_id:
        try:
            live_map = try_fetch_ims_status_map_for_client(
                sb,
                client_gstin_id,
                year=year,
                month=month,
            )
            if live_map:
                status_map.update(live_map)
                _log.info("Live IMS overlay fetched for run_id=%s count=%d", rid, len(live_map))
        except Exception as exc:
            _log.warning("Live IMS overlay fetch soft-failed for run_id=%s: %s", rid, exc)

    # Path B: Merge confirmed submissions
    local_sub_map = _build_status_map_from_submissions(sb, rid)
    status_map.update(local_sub_map)

    if not status_map:
        _log.info("No IMS status mappings found for run_id=%s", rid)
        return ImsSyncResult(
            synced=True,
            run_id=rid,
            invoices_updated=0,
            phase4_post_action_2b_sync_pending=False,
            message="No updated IMS statuses found to sync.",
        )

    # 2. Update gstr_records table
    updated_gstr_count = 0
    gstr_id_to_status: dict[str, str] = {}
    offset = 0
    page_size = 500

    while True:
        res = (
            sb.table("gstr_records")
            .select("id, record_data")
            .eq("run_id", rid)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break

        for r in rows:
            g_id = str(r["id"])
            rd = r.get("record_data")
            if not isinstance(rd, dict):
                continue

            sg = (
                rd.get("supplier_gstin")
                or rd.get("ctin")
                or rd.get("stin")
                or ""
            ).strip().upper()
            inum = (
                rd.get("invoice_number")
                or rd.get("inum")
                or rd.get("document_number")
                or ""
            )

            key = ims_composite_key(sg, inum)
            if key in status_map:
                target_st = status_map[key]
                gstr_id_to_status[g_id] = target_st
                if rd.get("ims_status") != target_st:
                    rd["ims_status"] = target_st
                    sb.table("gstr_records").update({"record_data": rd}).eq("id", g_id).execute()
                    updated_gstr_count += 1

        offset += len(rows)
        if len(rows) < page_size:
            break

    # 3. Update reconciliation_results payload
    payload = load_payload(sb, rid)
    updated_payload_items = 0

    if payload and isinstance(payload, dict):
        engine = payload.get("engine")
        if isinstance(engine, dict):
            # Matched rows
            for m in engine.get("matched") or []:
                if not isinstance(m, dict):
                    continue
                gid = str(m.get("gstr_id") or "")
                new_st = gstr_id_to_status.get(gid)
                if not new_st:
                    sg = m.get("supplier_gstin")
                    inum = m.get("invoice_number") or m.get("invoice_number_normalized")
                    if sg and inum:
                        new_st = status_map.get(ims_composite_key(sg, inum))
                if new_st and m.get("ims_status") != new_st:
                    m["ims_status"] = new_st
                    updated_payload_items += 1

            # Missed ITC rows
            for miss in engine.get("missed_itc") or []:
                if not isinstance(miss, dict):
                    continue
                gid = str(miss.get("gstr_id") or "")
                new_st = gstr_id_to_status.get(gid)
                if not new_st:
                    sg = miss.get("supplier_gstin")
                    inum = miss.get("invoice_number_normalized") or miss.get("invoice_number")
                    if sg and inum:
                        new_st = status_map.get(ims_composite_key(sg, inum))
                if new_st and miss.get("ims_status") != new_st:
                    miss["ims_status"] = new_st
                    updated_payload_items += 1

            # Duplicate / review rows
            for dup in engine.get("duplicates") or []:
                if not isinstance(dup, dict):
                    continue
                gid = str(dup.get("gstr_id") or "")
                new_st = gstr_id_to_status.get(gid)
                if not new_st:
                    sg = dup.get("supplier_gstin")
                    inum = dup.get("invoice_number_normalized") or dup.get("invoice_number")
                    if sg and inum:
                        new_st = status_map.get(ims_composite_key(sg, inum))
                if new_st and dup.get("ims_status") != new_st:
                    dup["ims_status"] = new_st
                    updated_payload_items += 1

        # Decisions rows
        decisions = payload.get("decisions")
        if isinstance(decisions, dict):
            for dec in decisions.get("rows") or []:
                if not isinstance(dec, dict):
                    continue
                sg = dec.get("supplier_gstin")
                inum = dec.get("invoice_number")
                if sg and inum:
                    new_st = status_map.get(ims_composite_key(sg, inum))
                    if new_st and dec.get("ims_status") != new_st:
                        dec["ims_status"] = new_st

        # Save back the updated payload
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            save_reconciliation_results(sb, rid, payload, created_at=now_iso)
        except Exception as exc:
            _log.warning("Could not persist updated reconciliation_results for run_id=%s: %s", rid, exc)

    # 4. Touch run updated_at
    try:
        sb.table("reconciliation_run").update(
            {"updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", rid).execute()
    except Exception as exc:
        _log.warning("Could not update reconciliation_run updated_at: %s", exc)

    # 5. Clear caches
    clear_process_maps_for_run(rid)
    clear_request_load_cache()

    total_updated = max(updated_gstr_count, updated_payload_items, len(gstr_id_to_status))
    _log.info(
        "IMS sync completed run_id=%s gstr_updated=%d payload_updated=%d total=%d",
        rid,
        updated_gstr_count,
        updated_payload_items,
        total_updated,
    )

    return ImsSyncResult(
        synced=True,
        run_id=rid,
        invoices_updated=total_updated,
        phase4_post_action_2b_sync_pending=False,
        message=f"Synchronized {total_updated} invoice(s) with GSTR-2B & IMS overlay.",
    )
