"""Clone imported GSTR/PR rows and re-run matching on a fresh run_id.

Used to verify populate_review_decisions() after deploy.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_supabase

SOURCE_RUN_ID = "94b44c44-b076-487d-8043-d8a3c5c313f5"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _copy_records(sb, table: str, source_id: str, new_id: str, client_gstin_id: str, period: str) -> int:
    copied = 0
    offset = 0
    page_size = 500
    while True:
        batch = (
            sb.table(table)
            .select("client_gstin_id, period, record_data")
            .eq("run_id", source_id)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = batch.data or []
        if not rows:
            break
        inserts = [
            {
                "id": str(uuid.uuid4()),
                "run_id": new_id,
                "client_gstin_id": client_gstin_id,
                "period": period,
                "record_data": row["record_data"],
            }
            for row in rows
        ]
        sb.table(table).insert(inserts).execute()
        copied += len(inserts)
        if len(rows) < page_size:
            break
        offset += page_size
    return copied


def main() -> int:
    source_id = (sys.argv[1] if len(sys.argv) > 1 else SOURCE_RUN_ID).strip()
    sb = get_supabase()
    src = (
        sb.table("reconciliation_run")
        .select(
            "id, client_gstin_id, period, gstr_records_imported, pr_records_imported"
        )
        .eq("id", source_id)
        .single()
        .execute()
    ).data
    if not src:
        print(f"Source run not found: {source_id}", file=sys.stderr)
        return 1

    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    client_gstin_id = str(src["client_gstin_id"])
    period = str(src["period"])

    sb.table("reconciliation_run").insert(
        {
            "id": new_id,
            "client_gstin_id": client_gstin_id,
            "period": period,
            "status": "MATCHING",
            "progress_percent": 0,
            "status_message": "Verification re-run queued",
            "gstr_records_imported": int(src.get("gstr_records_imported") or 0),
            "pr_records_imported": int(src.get("pr_records_imported") or 0),
            "created_at": now,
            "updated_at": now,
        }
    ).execute()

    gstr_n = _copy_records(sb, "gstr_records", source_id, new_id, client_gstin_id, period)
    pr_n = _copy_records(sb, "pr_records", source_id, new_id, client_gstin_id, period)
    print(f"Created run {new_id} from source {source_id} (gstr={gstr_n}, pr={pr_n})")

    cmd = (
        "import logging; "
        "logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s'); "
        f"import sys; sys.path.insert(0, {str(BACKEND_ROOT)!r}); "
        f"from app.worker.reconciliation_task import execute_reconciliation; "
        f"execute_reconciliation({new_id!r})"
    )
    print("Running execute_reconciliation in subprocess…")
    subprocess.check_call([sys.executable, "-c", cmd], cwd=str(BACKEND_ROOT))

    run = (
        sb.table("reconciliation_run")
        .select("id, status, created_at, status_message")
        .eq("id", new_id)
        .limit(1)
        .execute()
    )
    print("reconciliation_run:", json.dumps(run.data, default=str))
    print(f"NEW_RUN_ID={new_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
