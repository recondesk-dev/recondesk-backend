"""
Fix historical reconciliation runs affected by the Jan 2000 ('012000' / '2000-01') alt-parser bug.

This script scans for reconciliation_run rows where period is '2000-01' (or '2000-01-01' or '012000'),
finds the true CA-selected period from reconciliation_import_runs, and updates:
  1. reconciliation_run.period
  2. gstr_records.period
  3. pr_records.period

Run from recondesk-backend/:
    python3 scripts/fix_jan_2000_runs.py
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger(__name__)


def fix_jan_2000_runs() -> None:
    sb = get_supabase()

    _log.info("Querying for reconciliation_run rows with period '2000-01'...")
    res = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, created_at")
        .in_("period", ["2000-01", "2000-01-01", "012000"])
        .execute()
    )

    bad_runs = res.data or []
    if not bad_runs:
        _log.info("No runs found with Jan 2000 period. Database is clean!")
        return

    _log.info("Found %d run(s) with Jan 2000 period. Repairing...", len(bad_runs))

    for run in bad_runs:
        run_id = str(run["id"])
        _log.info("Inspecting run_id=%s (current period=%s)...", run_id, run["period"])

        wiz_res = (
            sb.table("reconciliation_import_runs")
            .select("period")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        correct_period = None
        if wiz_res.data and wiz_res.data[0].get("period"):
            raw_p = str(wiz_res.data[0]["period"]).strip()
            correct_period = raw_p[:7] if len(raw_p) >= 7 else raw_p

        if not correct_period or correct_period in ("2000-01", "2000-01-01", "012000"):
            _log.warning(
                "Could not recover period from reconciliation_import_runs for run_id=%s. Skipping automated update.",
                run_id,
            )
            continue

        _log.info("Repairing run_id=%s -> new period=%s", run_id, correct_period)

        sb.table("reconciliation_run").update({"period": correct_period}).eq("id", run_id).execute()
        sb.table("gstr_records").update({"period": correct_period}).eq("run_id", run_id).execute()
        sb.table("pr_records").update({"period": correct_period}).eq("run_id", run_id).execute()

        _log.info("Successfully updated run_id=%s to period %s", run_id, correct_period)

    _log.info("Repair complete.")


if __name__ == "__main__":
    fix_jan_2000_runs()
