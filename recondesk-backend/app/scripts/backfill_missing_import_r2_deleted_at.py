#!/usr/bin/env python3
"""One-time backfill: mark missing R2 import files as deleted in the DB.

For reconciliation_import_runs rows where status = 'complete' and R2
head_object confirms the gstr2b/pr object is gone, set the corresponding
*_deleted_at timestamp so Manage Data shows the Deleted badge instead of a
broken download link.

Uses the same R2 checks as verify_import_r2_keys.py.

Usage (from recondesk-backend/):
    python3 app/scripts/backfill_missing_import_r2_deleted_at.py --dry-run
    python3 app/scripts/backfill_missing_import_r2_deleted_at.py
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
    _fetch_complete_runs,
    _head_exists,
    _r2_client,
)


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
    args = parser.parse_args()

    if not settings.R2_BUCKET_NAME or not settings.R2_ACCESS_KEY_ID:
        print("ERROR: R2 credentials / bucket not configured.", file=sys.stderr)
        return 1

    rows = _fetch_complete_runs()
    client = _r2_client()
    bucket = settings.R2_BUCKET_NAME
    sb = get_supabase()

    gstr2b_updates = 0
    pr_updates = 0

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
        print(f"{'[dry-run] ' if args.dry_run else ''}{run_id}: set {label} = {deleted_at}")

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
