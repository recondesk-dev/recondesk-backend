"""Seed a per-user demo client + reconciled run for the first-login product tour.

Idempotent: if an active ``is_demo`` client already exists for the firm owner,
returns that client (and its latest completed run when present) without
re-seeding.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database import get_supabase
from app.parsers.gstr2b_parser import parse_gstr2b
from app.parsers.purchase_register_parser import parse_purchase_register

_log = logging.getLogger(__name__)

DEMO_DATA_DIR = Path(__file__).resolve().parent.parent / "demo_data"
DEMO_GSTIN = "27DEMOC0001A1ZJ"
DEMO_TRADE_NAME = "Demo Client - Sample Reconciliation"
DEMO_PERIOD = "2026-04"


def _bulk_insert(sb, table: str, rows: list[dict[str, Any]], chunk: int = 200) -> None:
    for i in range(0, len(rows), chunk):
        sb.table(table).insert(rows[i : i + chunk]).execute()


def _load_manifest() -> dict[str, Any]:
    path = DEMO_DATA_DIR / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _find_demo_client(sb, firm_owner_id: str) -> dict[str, Any] | None:
    try:
        res = (
            sb.table("client_gstins")
            .select("*")
            .eq("firm_owner_id", firm_owner_id)
            .eq("is_demo", True)
            .eq("is_active", True)
            .order("added_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        # Column may not exist until migration is applied — fall back by trade name.
        _log.warning("is_demo query failed (%s); falling back to trade_name", exc)
        res = (
            sb.table("client_gstins")
            .select("*")
            .eq("firm_owner_id", firm_owner_id)
            .eq("trade_name", DEMO_TRADE_NAME)
            .eq("is_active", True)
            .order("added_at", desc=True)
            .limit(1)
            .execute()
        )
    if res.data:
        return res.data[0]
    return None


def _latest_demo_run(sb, client_id: str) -> dict[str, Any] | None:
    res = (
        sb.table("reconciliation_run")
        .select("id, status, period, client_gstin_id, created_at")
        .eq("client_gstin_id", client_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    rows = list(res.data or [])
    for row in rows:
        st = str(row.get("status") or "").strip().upper()
        if st in ("COMPLETED", "COMPLETE", "FINAL", "FINALIZED"):
            return row
    return rows[0] if rows else None


def _create_demo_client(sb, firm_owner_id: str) -> dict[str, Any]:
    manifest = _load_manifest()
    gstin = str(manifest.get("buyer_gstin") or DEMO_GSTIN).strip().upper()
    trade = str(manifest.get("trade_name") or DEMO_TRADE_NAME)
    legal = str(manifest.get("legal_name") or trade)
    now = datetime.now(timezone.utc).isoformat()
    client_id = str(uuid4())
    ins: dict[str, Any] = {
        "id": client_id,
        "gstin": gstin,
        "trade_name": trade,
        "legal_name": legal,
        "state_code": gstin[:2],
        "firm_owner_id": firm_owner_id,
        "is_active": True,
        "is_demo": True,
        "added_at": now,
    }
    try:
        sb.table("client_gstins").insert(ins).execute()
    except Exception as exc:  # noqa: BLE001
        # Migration not applied yet — retry without is_demo.
        if "is_demo" in str(exc).lower():
            ins.pop("is_demo", None)
            sb.table("client_gstins").insert(ins).execute()
        else:
            raise
    out = (
        sb.table("client_gstins")
        .select("*")
        .eq("id", client_id)
        .single()
        .execute()
    )
    return out.data


def _seed_and_reconcile(sb, firm_owner_id: str, client: dict[str, Any]) -> dict[str, Any]:
    """Parse bundled demo files, insert records, run the matching engine."""
    from app.worker.reconciliation_task import execute_reconciliation
    from app.worker.tasks import _json_safe as tasks_json_safe

    manifest = _load_manifest()
    period = str(manifest.get("period") or DEMO_PERIOD)[:7]
    client_id = str(client["id"])
    gstin = str(client.get("gstin") or DEMO_GSTIN)

    gstr_path = DEMO_DATA_DIR / str(manifest.get("gstr_file") or "demo_gstr_2b.json")
    pr_path = DEMO_DATA_DIR / str(manifest.get("pr_file") or "demo_purchase_register.xlsx")
    gstr_body = gstr_path.read_bytes()
    pr_body = pr_path.read_bytes()

    gstr_payload = json.loads(gstr_body.decode("utf-8"))
    # Ensure buyer GSTIN matches the demo client (parser uses file gstin).
    if isinstance(gstr_payload.get("data"), dict):
        gstr_payload["data"]["gstin"] = gstin

    parsed_gstr = parse_gstr2b(gstr_payload)
    gstr_records = list(parsed_gstr.get("records") or [])
    if not gstr_records:
        raise RuntimeError("demo GSTR-2B parse returned zero records")

    parsed_pr = parse_purchase_register(pr_body, pr_path.name)
    if not parsed_pr.get("success"):
        errs = "; ".join(parsed_pr.get("errors") or ["parse failed"])
        raise RuntimeError(f"demo purchase register parse failed: {errs}")
    pr_records = list(parsed_pr.get("records") or [])
    if not pr_records:
        raise RuntimeError("demo purchase register parse returned zero records")

    run_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    run_row: dict[str, Any] = {
        "id": run_id,
        "client_gstin_id": client_id,
        "period": period,
        "status": "importing",
        "progress_percent": 10,
        "gstr_records_imported": len(gstr_records),
        "pr_records_imported": len(pr_records),
        "status_message": "Seeding demo data…",
        "created_at": now,
        "updated_at": now,
    }
    # Prefer firm_owner_id when the column exists on reconciliation_run.
    try:
        run_row["firm_owner_id"] = firm_owner_id
        sb.table("reconciliation_run").insert(run_row).execute()
    except Exception as exc:  # noqa: BLE001
        if "firm_owner_id" in str(exc).lower():
            run_row.pop("firm_owner_id", None)
            sb.table("reconciliation_run").insert(run_row).execute()
        else:
            raise

    gstr_rows = [
        {
            "run_id": run_id,
            "client_gstin_id": client_id,
            "period": period,
            "record_data": tasks_json_safe(rec),
        }
        for rec in gstr_records
    ]
    pr_rows = [
        {
            "run_id": run_id,
            "client_gstin_id": client_id,
            "period": period,
            "record_data": tasks_json_safe(rec),
        }
        for rec in pr_records
    ]
    _bulk_insert(sb, "gstr_records", gstr_rows)
    _bulk_insert(sb, "pr_records", pr_rows)

    sb.table("reconciliation_run").update(
        {
            "status": "MATCHING",
            "progress_percent": 40,
            "status_message": "Matching demo invoices…",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", run_id).execute()

    # Run engine in-process (Celery apply / direct call).
    try:
        execute_reconciliation(run_id)
    except TypeError:
        # Bound Celery task — call via apply for eager/sync workers.
        execute_reconciliation.apply(args=[run_id])

    run_out = (
        sb.table("reconciliation_run")
        .select("id, status, period, client_gstin_id, created_at")
        .eq("id", run_id)
        .single()
        .execute()
    )
    return run_out.data


def get_demo_status(user_id: str) -> dict[str, Any] | None:
    """Return demo client + latest run without creating anything."""
    sb = get_supabase()
    uid = str(user_id).strip()
    client = _find_demo_client(sb, uid)
    if not client:
        return None
    run = _latest_demo_run(sb, str(client["id"]))
    manifest = _load_manifest()
    return {
        "client_id": str(client["id"]),
        "run_id": str(run["id"]) if run else None,
        "client": client,
        "run": run,
        "created": False,
        "scenarios": dict(manifest.get("scenarios") or {}),
    }


def ensure_demo_client_for_user(user_id: str, *, force_reseed: bool = False) -> dict[str, Any]:
    """Create demo client + reconciled run if missing. Safe to call repeatedly.

    Returns:
        {
          "client_id": str,
          "run_id": str | None,
          "client": dict,
          "run": dict | None,
          "created": bool,
          "scenarios": {...},
        }
    """
    sb = get_supabase()
    uid = str(user_id).strip()
    if not uid:
        raise ValueError("user_id is required")

    manifest = _load_manifest()
    scenarios = dict(manifest.get("scenarios") or {})

    existing = _find_demo_client(sb, uid)
    if existing and not force_reseed:
        run = _latest_demo_run(sb, str(existing["id"]))
        if run is None:
            _log.info("Demo client %s has no run — seeding reconciliation", existing["id"])
            run = _seed_and_reconcile(sb, uid, existing)
            return {
                "client_id": str(existing["id"]),
                "run_id": str(run["id"]) if run else None,
                "client": existing,
                "run": run,
                "created": True,
                "scenarios": scenarios,
            }
        return {
            "client_id": str(existing["id"]),
            "run_id": str(run["id"]) if run else None,
            "client": existing,
            "run": run,
            "created": False,
            "scenarios": scenarios,
        }

    client = _create_demo_client(sb, uid)
    run = _seed_and_reconcile(sb, uid, client)
    _log.info(
        "Seeded demo client=%s run=%s for user=%s",
        client.get("id"),
        run.get("id") if run else None,
        uid,
    )
    return {
        "client_id": str(client["id"]),
        "run_id": str(run["id"]) if run else None,
        "client": client,
        "run": run,
        "created": True,
        "scenarios": scenarios,
    }
