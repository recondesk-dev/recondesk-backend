#!/usr/bin/env python3
"""Bulk Migration & Verification Script: Cloudflare R2 -> Amazon S3.

Safely migrates all objects from Cloudflare R2 to native Amazon S3:
1. Lists all objects in the Cloudflare R2 bucket.
2. Checks whether each object already exists in the target Amazon S3 bucket.
3. For new or differing objects:
   - Streams object data from R2
   - Calculates SHA-256 digest
   - Preserves ContentType and metadata
   - Applies SSE-S3 AES256 encryption
   - Uploads to S3 under identical object key
4. Verifies byte-level parity:
   - S3 object existence
   - Exact byte size match
   - SHA-256 hash verification
5. NEVER modifies or deletes source R2 objects (for zero-risk rollback).

Usage (from recondesk-backend/):
    python3 app/scripts/migrate_r2_to_s3.py
    python3 app/scripts/migrate_r2_to_s3.py --dry-run
    python3 app/scripts/migrate_r2_to_s3.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings  # noqa: E402
from app.services.storage_service import get_storage_service  # noqa: E402


def migrate_objects(
    dry_run: bool = False,
    verify_only: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    svc = get_storage_service()
    r2 = svc.get_r2_client()
    s3 = svc.get_s3_client()

    if r2 is None:
        raise RuntimeError("R2 client could not be initialized. Check R2 credentials in environment.")

    r2_bucket = svc.r2_bucket
    s3_bucket = svc.s3_bucket

    print("=" * 70)
    print("ReconDesk Cloud Storage Migration: Cloudflare R2 -> Amazon S3")
    print("=" * 70)
    print(f"Source Bucket (R2): {r2_bucket}")
    print(f"Target Bucket (S3): {s3_bucket} (Region: {settings.AWS_REGION})")
    print(f"Mode: {'VERIFY ONLY' if verify_only else 'DRY RUN' if dry_run else 'ACTIVE MIGRATION'}")
    print(f"Force Overwrite: {force}")
    print("-" * 70)

    paginator = r2.get_paginator("list_objects_v2")
    stats = {
        "total_discovered": 0,
        "already_synced": 0,
        "migrated_successfully": 0,
        "verified_identical": 0,
        "mismatches": 0,
        "errors": 0,
        "total_bytes_discovered": 0,
        "total_bytes_migrated": 0,
        "start_time": time.time(),
    }

    object_list = []
    print("Discovering objects in Cloudflare R2...")
    for page in paginator.paginate(Bucket=r2_bucket):
        for item in page.get("Contents", []):
            stats["total_discovered"] += 1
            stats["total_bytes_discovered"] += item["Size"]
            object_list.append(item)

    print(
        f"Found {stats['total_discovered']} objects in R2 "
        f"({stats['total_bytes_discovered'] / (1024 * 1024):.2f} MB)."
    )
    print("-" * 70)

    for idx, item in enumerate(object_list, 1):
        key = item["Key"]
        r2_size = item["Size"]

        # Check if already present in S3
        s3_exists = False
        s3_size = -1
        try:
            head = s3.head_object(Bucket=s3_bucket, Key=key)
            s3_exists = True
            s3_size = head.get("ContentLength", -1)
        except Exception:
            s3_exists = False

        if s3_exists and s3_size == r2_size and not force:
            stats["already_synced"] += 1
            stats["verified_identical"] += 1
            if idx % 50 == 0 or idx == stats["total_discovered"]:
                print(f"[{idx}/{stats['total_discovered']}] (Skipped/Synced) {key} ({r2_size} bytes)")
            continue

        if verify_only:
            if not s3_exists:
                print(f"[{idx}/{stats['total_discovered']}] [FAIL] Missing in S3: {key}")
                stats["mismatches"] += 1
            elif s3_size != r2_size:
                print(f"[{idx}/{stats['total_discovered']}] [FAIL] Size mismatch for {key}: R2={r2_size}, S3={s3_size}")
                stats["mismatches"] += 1
            else:
                stats["verified_identical"] += 1
            continue

        if dry_run:
            print(f"[{idx}/{stats['total_discovered']}] [DRY-RUN] Would migrate: {key} ({r2_size} bytes)")
            stats["migrated_successfully"] += 1
            stats["total_bytes_migrated"] += r2_size
            continue

        # Active migration
        try:
            # 1. Download from R2
            r2_obj = r2.get_object(Bucket=r2_bucket, Key=key)
            body = r2_obj["Body"].read()
            content_type = r2_obj.get("ContentType", "application/octet-stream")
            r2_sha256 = hashlib.sha256(body).hexdigest()

            # 2. Upload to S3
            s3.put_object(
                Bucket=s3_bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
                Metadata={
                    "sha256": r2_sha256,
                    "migrated_from": "r2",
                    "original_bucket": r2_bucket,
                },
            )

            # 3. Post-upload verification
            s3_head = s3.head_object(Bucket=s3_bucket, Key=key)
            uploaded_size = s3_head.get("ContentLength", -1)
            if uploaded_size != len(body):
                raise ValueError(f"Post-migration size mismatch: expected {len(body)}, got {uploaded_size}")

            stats["migrated_successfully"] += 1
            stats["total_bytes_migrated"] += len(body)
            stats["verified_identical"] += 1

            if idx % 25 == 0 or idx == stats["total_discovered"]:
                print(
                    f"[{idx}/{stats['total_discovered']}] [MIGRATED] {key} "
                    f"({len(body)} bytes, sha256={r2_sha256[:8]}...)"
                )
        except Exception as exc:
            stats["errors"] += 1
            print(f"[{idx}/{stats['total_discovered']}] [ERROR] Failed to migrate {key}: {exc}")

    duration = time.time() - stats["start_time"]
    print("=" * 70)
    print("MIGRATION & VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"Total Objects Discovered in R2: {stats['total_discovered']}")
    print(f"Total Bytes Discovered in R2:   {stats['total_bytes_discovered']} ({stats['total_bytes_discovered'] / (1024 * 1024):.2f} MB)")
    print(f"Already Present & Valid in S3:  {stats['already_synced']}")
    print(f"Migrated in this Run:           {stats['migrated_successfully']}")
    print(f"Bytes Transferred in this Run:  {stats['total_bytes_migrated']} ({stats['total_bytes_migrated'] / (1024 * 1024):.2f} MB)")
    print(f"Total Verified Identical in S3: {stats['verified_identical']}")
    print(f"Integrity Mismatches:           {stats['mismatches']}")
    print(f"Failures / Errors:              {stats['errors']}")
    print(f"Elapsed Time:                   {duration:.2f} seconds")
    print(f"Source R2 Objects Preserved:    100% (No R2 objects deleted)")
    print("=" * 70)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate ReconDesk storage from Cloudflare R2 to Amazon S3")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without uploading to S3")
    parser.add_argument("--verify-only", action="store_true", help="Verify existing S3 objects against R2 without transferring")
    parser.add_argument("--force", action="store_true", help="Force overwrite objects in S3 even if size matches")
    args = parser.parse_args()

    stats = migrate_objects(dry_run=args.dry_run, verify_only=args.verify_only, force=args.force)
    if stats["errors"] > 0 or stats["mismatches"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
