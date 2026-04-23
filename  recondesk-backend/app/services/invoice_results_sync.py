"""Sync `invoice_results` for Rule 37 from reconciliation payload; resolution counts."""

from __future__ import annotations

from supabase import Client

from app.services import reconciliation_outcomes as ro
from app.services.reconciliation_outcomes import RULE37_CONCERNS


def sync_rule37_invoice_results(sb: Client, run_id: str) -> None:
    """Ensure `invoice_results` rows exist for every PR line that needs Rule 37 follow-up."""
    p = ro.load_payload(sb, run_id)
    if not p:
        return
    comp = p.get("compliance") or {}
    for row in comp.get("rule37") or []:
        if (row.get("status") or "") not in RULE37_CONCERNS:
            continue
        pid = str(row.get("pr_id", "")).strip()
        if not pid:
            continue
        ex = (
            sb.table("invoice_results")
            .select("id")
            .eq("run_id", run_id)
            .eq("pr_id", pid)
            .limit(1)
            .execute()
        )
        if ex.data:
            sb.table("invoice_results").update({"rule37_flag": True}).eq(
                "id", ex.data[0]["id"]
            ).execute()
        else:
            sb.table("invoice_results").insert(
                {
                    "run_id": run_id,
                    "pr_id": pid,
                    "rule37_flag": True,
                }
            ).execute()


def count_unresolved_rule37(sb: Client, run_id: str) -> tuple[int, int, int]:
    """Returns (need, have, unresolved) for finalize pre-check.

    *need* = rows in ``invoice_results`` with ``rule37_flag`` true.
    *have* = ``rule37_resolutions`` for this run.
    *unresolved* = max(0, need - have).
    """
    sync_rule37_invoice_results(sb, run_id)
    n1 = (
        sb.table("invoice_results")
        .select("id", count="exact")
        .eq("run_id", run_id)
        .eq("rule37_flag", True)
        .limit(0)
        .execute()
    )
    n2 = (
        sb.table("rule37_resolutions")
        .select("id", count="exact")
        .eq("run_id", run_id)
        .limit(0)
        .execute()
    )
    need = int(n1.count or 0)
    have = int(n2.count or 0)
    return need, have, max(0, need - have)
