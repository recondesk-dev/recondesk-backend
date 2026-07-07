#!/usr/bin/env python3
"""Verify R2 objects exist for completed import-wizard runs.

Usage (from recondesk-backend/):
    python3 app/scripts/verify_import_r2_keys.py
    python3 app/scripts/verify_import_r2_keys.py --json missing_r2_keys.json

Checks reconciliation_import_runs where status = 'complete' and each file's
*_deleted_at is null. Uses head_object (no download).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings  # noqa: E402
from app.database import get_supabase  # noqa: E402


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _head_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound", "403"):
            return False
        raise


def _fetch_complete_runs() -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("reconciliation_import_runs")
        .select(
            "id, client_id, period, status, created_at, updated_at, "
            "gstr2b_r2_key, gstr2b_file_name, gstr2b_uploaded_at, gstr2b_deleted_at, "
            "pr_r2_key, pr_file_name, pr_uploaded_at, pr_deleted_at"
        )
        .eq("status", "complete")
        .execute()
    )
    return list(res.data or [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Write full report JSON to this path",
    )
    args = parser.parse_args()

    if not settings.R2_BUCKET_NAME or not settings.R2_ACCESS_KEY_ID:
        print("ERROR: R2 credentials / bucket not configured.", file=sys.stderr)
        return 1

    rows = _fetch_complete_runs()
    client = _r2_client()
    bucket = settings.R2_BUCKET_NAME

    checked_gstr2b = 0
    checked_pr = 0
    missing_gstr2b = 0
    missing_pr = 0
    affected: list[dict[str, Any]] = []

    for row in rows:
        run_id = str(row.get("id") or "")
        issues: list[dict[str, Any]] = []

        gstr_key = (row.get("gstr2b_r2_key") or "").strip()
        if gstr_key and not row.get("gstr2b_deleted_at"):
            checked_gstr2b += 1
            if not _head_exists(client, bucket, gstr_key):
                missing_gstr2b += 1
                issues.append(
                    {
                        "file_type": "gstr2b",
                        "r2_key": gstr_key,
                        "file_name": row.get("gstr2b_file_name"),
                        "uploaded_at": row.get("gstr2b_uploaded_at"),
                    }
                )

        pr_key = (row.get("pr_r2_key") or "").strip()
        if pr_key and not row.get("pr_deleted_at"):
            checked_pr += 1
            if not _head_exists(client, bucket, pr_key):
                missing_pr += 1
                issues.append(
                    {
                        "file_type": "pr",
                        "r2_key": pr_key,
                        "file_name": row.get("pr_file_name"),
                        "uploaded_at": row.get("pr_uploaded_at"),
                    }
                )

        if issues:
            affected.append(
                {
                    "run_id": run_id,
                    "client_id": row.get("client_id"),
                    "period": row.get("period"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    "missing": issues,
                }
            )

    report = {
        "summary": {
            "complete_runs_total": len(rows),
            "runs_with_missing_objects": len(affected),
            "gstr2b_keys_checked": checked_gstr2b,
            "gstr2b_keys_missing": missing_gstr2b,
            "pr_keys_checked": checked_pr,
            "pr_keys_missing": missing_pr,
        },
        "affected_runs": affected,
    }

    print("=== Import wizard R2 key verification (status=complete) ===")
    print(json.dumps(report["summary"], indent=2))
    print()

    if affected:
        print(f"Runs with missing R2 objects ({len(affected)}):")
        for entry in affected:
            missing_types = ", ".join(m["file_type"] for m in entry["missing"])
            print(f"  {entry['run_id']}  period={entry.get('period')}  missing=[{missing_types}]")
            for m in entry["missing"]:
                print(f"    - {m['file_type']}: {m['r2_key']}")
    else:
        print("All checked keys exist in R2.")

    if args.json:
        out = Path(args.json)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nFull report written to {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
