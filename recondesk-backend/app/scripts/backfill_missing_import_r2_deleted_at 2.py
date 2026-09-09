#!/usr/bin/env python3
"""Backfill *_deleted_at when R2 import objects are already gone.

For reconciliation_import_runs rows in the selected status(es), if a gstr2b/pr
R2 key is present, *_deleted_at is null, and head_object confirms the object
is missing, set the corresponding *_deleted_at timestamp so deleted_at is the
source of truth for "does this R2 object still exist."

Defaults to status=complete (legacy Manage Data / post-parse orphans).
Use --status cancelled for cancel_run orphans that deleted R2 without stamping
deleted_at. --status error covers pre-Jul-7 parse-delete orphans on failed runs.

Usage (from recondesk-backend/):
    python3 app/scripts/backfill_missing_import_r2_deleted_at.py --dry-run
    python3 app/scripts/backfill_missing_import_r2_deleted_at.py --status cancelled
    python3 app/scripts/backfill_missing_import_r2_deleted_at.py --status cancelled --status error
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings  # noqa: E402
from app.database import get_supabase  # noqa: E402
from app.scripts.verify_import_r2_keys import (  # noqa: E402
    _head_exists,
    _r2_client,
)

_SELECT = (
    "id, client_id, period, status, created_at, updated_at, "
    "gstr2b_r2_key, gstr2b_file_name, gstr2b_uploaded_at, gstr2b_deleted_at, "
    "pr_r2_key, pr_file_name, pr_uploaded_at, pr_deleted_at"
)


def _fetch_runs(statuses: list[str]) -> list[dict[str, Any]]:
    sb = get_supabase()
    rows: list[dict[str, Any]] = []
    for status in statuses:
        res = (
            sb.table("reconciliation_import_runs")
            .select(_SELECT)
            .eq("status", status)
            .execute()
        )
        rows.extend(res.data or [])
    return rows


def _deleted_at_value(row: dict[str, Any]) -> str:
    raw = row.get("updated_at")
    if raw:
        return str(raw)
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned updates without writing to the database",
    )
    parser.add_argument(
        "--status",
        action="append",
        dest="statuses",
        metavar="STATUS",
        help=(
            "Import-run status to scan (repeatable). "
            "Default: complete. Examples: cancelled, error"
        ),
    )
    args = parser.parse_args()
    statuses = args.statuses or ["complete"]

    if not settings.R2_BUCKET_NAME or not settings.R2_ACCESS_KEY_ID:
        print("ERROR: R2 credentials / bucket not configured.", file=sys.stderr)
        return 1

    rows = _fetch_runs(statuses)
    client = _r2_client()
    bucket = settings.R2_BUCKET_NAME
    sb = get_supabase()

    gstr2b_updates = 0
    pr_updates = 0

    print(f"Scanning status={statuses!r} ({len(rows)} run(s))…")

    for row in rows:
        run_id = str(row.get("id") or "")
        patch: dict[str, str] = {}
        deleted_at = _deleted_at_value(row)

        gstr_key = (row.get("gstr2b_r2_key") or "").strip()
        if gstr_key and not row.get("gstr2b_deleted_at"):
            if not _head_exists(client, bucket, gstr_key):
                patch["gstr2b_deleted_at"] = deleted_at

        pr_key = (row.get("pr_r2_key") or "").strip()
        if pr_key and not row.get("pr_deleted_at"):
            if not _head_exists(client, bucket, pr_key):
                patch["pr_deleted_at"] = deleted_at

        if not patch:
            continue

        if "gstr2b_deleted_at" in patch:
            gstr2b_updates += 1
        if "pr_deleted_at" in patch:
            pr_updates += 1

        label = ", ".join(patch.keys())
        print(
            f"{'[dry-run] ' if args.dry_run else ''}"
            f"{run_id} status={row.get('status')}: set {label} = {deleted_at}"
        )

        if not args.dry_run:
            sb.table("reconciliation_import_runs").update(patch).eq("id", run_id).execute()

    print()
    print(
        f"{'Would update' if args.dry_run else 'Updated'} "
        f"gstr2b_deleted_at on {gstr2b_updates} run(s), "
        f"pr_deleted_at on {pr_updates} run(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
