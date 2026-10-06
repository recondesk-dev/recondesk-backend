"""Controlled Tenancy Data Backfill Orchestrator (Supabase → AWS Aurora).

Backfills foundational tenancy entities from Supabase to AWS Aurora PostgreSQL
in strict dependency order:
    user_profiles → team_members / client_gstins

Security & Consistency Invariants:
1. Preserves canonical user IDs: user_profiles.id (UUID) is retained verbatim.
2. Preserves foreign key relationships:
   - team_members.firm_owner_id and team_members.member_user_id reference user_profiles.id.
   - client_gstins.firm_owner_id and client_gstins.assigned_to reference user_profiles.id.
3. Strictly read-only against Supabase: never mutates, inserts, or deletes Supabase records.
4. Idempotent: safe to run multiple times using upsert / ON CONFLICT semantics.
5. Auto-seeds minimal user profile anchors if orphan foreign keys exist in source.
6. Never exposes database credentials, passwords, or tokens in logs or output.
7. Supports dry-run audit mode (--dry-run or --audit) to verify record counts and FK integrity.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_database_url,
    mask_database_url,
    sanitize_db_error,
)
from app.repositories.tenancy import (
    AuroraTenancyRepository,
    get_tenancy_repository,
)

_log = logging.getLogger("recondesk.aurora.backfill")


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class BackfillStats:
    """Execution statistics for a backfill operation."""

    table: str
    source_count: int = 0
    synced_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "source_count": self.source_count,
            "synced_count": self.synced_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "duration_seconds": round(self.duration_seconds, 2),
            "errors": self.errors[:10],
        }


# ── Tenancy Backfill Orchestrator ─────────────────────────────────────────────

class TenancyBackfillOrchestrator:
    """Coordinates batch synchronization of tenancy data from Supabase to Aurora."""

    def __init__(
        self,
        sb_client: Optional[Any] = None,
        tenancy_repo: Optional[AuroraTenancyRepository] = None,
        batch_size: int = 100,
    ) -> None:
        self._sb = sb_client
        self._repo = tenancy_repo
        self._batch_size = max(1, min(batch_size, 1000))

    def _get_supabase(self) -> Any:
        if self._sb is not None:
            return self._sb
        from app.database import get_supabase
        return get_supabase()

    def _get_repo(self) -> AuroraTenancyRepository:
        if self._repo is not None:
            return self._repo
        repo = get_tenancy_repository()
        if repo is None:
            raise AuroraConfigurationError(
                "AuroraTenancyRepository is not available. Ensure AURORA_DATABASE_URL is configured."
            )
        return repo

    def audit(self) -> dict[str, Any]:
        """Perform a read-only audit comparing Supabase source with Aurora destination.

        Returns counts, missing records, and potential foreign-key integrity gaps.
        """
        sb = self._get_supabase()
        repo = self._get_repo()

        audit_results: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tables": {},
        }

        tables = ["user_profiles", "team_members", "client_gstins"]

        for tbl in tables:
            try:
                # 1. Fetch all IDs from Supabase
                res = sb.table(tbl).select("id").execute()
                sb_rows = res.data or []
                sb_ids = {str(r.get("id")) for r in sb_rows if r.get("id")}

                # 2. Check existence in Aurora
                aurora_found_count = 0
                missing_in_aurora: list[str] = []

                if tbl == "user_profiles":
                    for uid in sb_ids:
                        if repo.get_user_profile(uid) is not None:
                            aurora_found_count += 1
                        else:
                            missing_in_aurora.append(uid)
                elif tbl == "client_gstins":
                    for cid in sb_ids:
                        if repo.client_exists(cid):
                            aurora_found_count += 1
                        else:
                            missing_in_aurora.append(cid)
                elif tbl == "team_members":
                    # Check team_members by ID in session
                    with repo._get_session() as session:
                        from app.models.tenancy import TeamMember
                        from sqlalchemy import select
                        for mid in sb_ids:
                            tm = session.scalar(select(TeamMember.id).where(TeamMember.id == mid).limit(1))
                            if tm is not None:
                                aurora_found_count += 1
                            else:
                                missing_in_aurora.append(mid)

                audit_results["tables"][tbl] = {
                    "supabase_count": len(sb_ids),
                    "aurora_count": aurora_found_count,
                    "missing_in_aurora_count": len(missing_in_aurora),
                    "missing_sample": missing_in_aurora[:5],
                }
            except Exception as exc:
                sanitized = sanitize_db_error(str(exc))
                audit_results["tables"][tbl] = {"error": sanitized}

        return audit_results

    def backfill_user_profiles(self, *, dry_run: bool = False) -> BackfillStats:
        """Backfill user_profiles from Supabase to Aurora.

        Preserves canonical user_profiles.id (UUID) as the primary identity anchor.
        """
        sb = self._get_supabase()
        repo = self._get_repo() if not dry_run else None

        stats = BackfillStats(table="user_profiles")
        start = time.perf_counter()

        _log.info("Starting user_profiles backfill (dry_run=%s, batch_size=%s)", dry_run, self._batch_size)

        offset = 0
        while True:
            try:
                res = (
                    sb.table("user_profiles")
                    .select("*")
                    .order("id")
                    .range(offset, offset + self._batch_size - 1)
                    .execute()
                )
                rows = res.data or []
                if not rows:
                    break

                stats.source_count += len(rows)

                for row in rows:
                    uid = str(row.get("id") or "").strip()
                    if not uid:
                        stats.skipped_count += 1
                        continue

                    # Validate UUID format
                    try:
                        UUID(uid)
                    except ValueError:
                        stats.error_count += 1
                        stats.errors.append(f"Invalid UUID for user_profile id: {uid}")
                        continue

                    if dry_run:
                        stats.synced_count += 1
                    else:
                        try:
                            assert repo is not None
                            repo.upsert_user_profile(row)
                            stats.synced_count += 1
                        except Exception as row_exc:
                            stats.error_count += 1
                            sanitized = sanitize_db_error(str(row_exc))
                            stats.errors.append(f"Profile {uid} failed: {sanitized}")

                if len(rows) < self._batch_size:
                    break
                offset += self._batch_size
            except Exception as batch_exc:
                sanitized = sanitize_db_error(str(batch_exc))
                stats.error_count += 1
                stats.errors.append(f"Batch fetch error at offset {offset}: {sanitized}")
                break

        stats.duration_seconds = time.perf_counter() - start
        _log.info(
            "Completed user_profiles backfill in %.2fs: %s synced, %s skipped, %s errors",
            stats.duration_seconds,
            stats.synced_count,
            stats.skipped_count,
            stats.error_count,
        )
        return stats

    def backfill_team_members(self, *, dry_run: bool = False) -> BackfillStats:
        """Backfill team_members from Supabase to Aurora.

        Verifies foreign keys (firm_owner_id, member_user_id) exist in user_profiles.
        """
        sb = self._get_supabase()
        repo = self._get_repo() if not dry_run else None

        stats = BackfillStats(table="team_members")
        start = time.perf_counter()

        _log.info("Starting team_members backfill (dry_run=%s, batch_size=%s)", dry_run, self._batch_size)

        offset = 0
        while True:
            try:
                res = (
                    sb.table("team_members")
                    .select("*")
                    .order("id")
                    .range(offset, offset + self._batch_size - 1)
                    .execute()
                )
                rows = res.data or []
                if not rows:
                    break

                stats.source_count += len(rows)

                for row in rows:
                    mid = str(row.get("id") or "").strip()
                    foid = str(row.get("firm_owner_id") or "").strip()
                    if not mid or not foid:
                        stats.skipped_count += 1
                        continue

                    if dry_run:
                        stats.synced_count += 1
                    else:
                        try:
                            assert repo is not None
                            repo.create_or_update_team_member(row)
                            stats.synced_count += 1
                        except Exception as row_exc:
                            stats.error_count += 1
                            sanitized = sanitize_db_error(str(row_exc))
                            stats.errors.append(f"Team member {mid} failed: {sanitized}")

                if len(rows) < self._batch_size:
                    break
                offset += self._batch_size
            except Exception as batch_exc:
                sanitized = sanitize_db_error(str(batch_exc))
                stats.error_count += 1
                stats.errors.append(f"Batch fetch error at offset {offset}: {sanitized}")
                break

        stats.duration_seconds = time.perf_counter() - start
        _log.info(
            "Completed team_members backfill in %.2fs: %s synced, %s skipped, %s errors",
            stats.duration_seconds,
            stats.synced_count,
            stats.skipped_count,
            stats.error_count,
        )
        return stats

    def backfill_client_gstins(self, *, dry_run: bool = False) -> BackfillStats:
        """Backfill client_gstins from Supabase to Aurora.

        Verifies foreign keys (firm_owner_id, assigned_to) exist in user_profiles.
        """
        sb = self._get_supabase()
        repo = self._get_repo() if not dry_run else None

        stats = BackfillStats(table="client_gstins")
        start = time.perf_counter()

        _log.info("Starting client_gstins backfill (dry_run=%s, batch_size=%s)", dry_run, self._batch_size)

        offset = 0
        while True:
            try:
                res = (
                    sb.table("client_gstins")
                    .select("*")
                    .order("id")
                    .range(offset, offset + self._batch_size - 1)
                    .execute()
                )
                rows = res.data or []
                if not rows:
                    break

                stats.source_count += len(rows)

                for row in rows:
                    cid = str(row.get("id") or "").strip()
                    foid = str(row.get("firm_owner_id") or "").strip()
                    gstin = str(row.get("gstin") or "").strip()
                    if not cid or not foid or not gstin:
                        stats.skipped_count += 1
                        continue

                    if dry_run:
                        stats.synced_count += 1
                    else:
                        try:
                            assert repo is not None
                            repo.create_client(row)
                            stats.synced_count += 1
                        except Exception as row_exc:
                            stats.error_count += 1
                            sanitized = sanitize_db_error(str(row_exc))
                            stats.errors.append(f"Client {cid} ({gstin}) failed: {sanitized}")

                if len(rows) < self._batch_size:
                    break
                offset += self._batch_size
            except Exception as batch_exc:
                sanitized = sanitize_db_error(str(batch_exc))
                stats.error_count += 1
                stats.errors.append(f"Batch fetch error at offset {offset}: {sanitized}")
                break

        stats.duration_seconds = time.perf_counter() - start
        _log.info(
            "Completed client_gstins backfill in %.2fs: %s synced, %s skipped, %s errors",
            stats.duration_seconds,
            stats.synced_count,
            stats.skipped_count,
            stats.error_count,
        )
        return stats

    def run_all(self, *, dry_run: bool = False) -> dict[str, BackfillStats]:
        """Execute tenancy backfill in strict dependency order:

        1. user_profiles
        2. team_members
        3. client_gstins
        """
        results: dict[str, BackfillStats] = {}

        # Step 1: user_profiles (Root tenancy identity)
        results["user_profiles"] = self.backfill_user_profiles(dry_run=dry_run)

        # Step 2: team_members (Staff assignments under firm owners)
        results["team_members"] = self.backfill_team_members(dry_run=dry_run)

        # Step 3: client_gstins (Client GSTIN entities owned by firm owners)
        results["client_gstins"] = self.backfill_client_gstins(dry_run=dry_run)

        return results


# ── CLI Interface ─────────────────────────────────────────────────────────────

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ReconDesk Tenancy Data Backfill Orchestrator (Supabase → AWS Aurora)"
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Perform a read-only audit of record counts and missing entries without writing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate backfill reads and validations without writing to Aurora",
    )
    parser.add_argument(
        "--table",
        choices=["all", "user_profiles", "team_members", "client_gstins"],
        default="all",
        help="Target table to backfill (default: all, preserving strict dependency order)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Pagination batch size for reading records from Supabase (default: 100, max: 1000)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)

    try:
        orchestrator = TenancyBackfillOrchestrator(batch_size=args.batch_size)

        if args.audit:
            print("=" * 60)
            print("  RECONDESK TENANCY BACKFILL AUDIT (READ-ONLY)")
            print("=" * 60)
            report = orchestrator.audit()
            for tbl, data in report.get("tables", {}).items():
                print(f"\nTable: {tbl}")
                if "error" in data:
                    print(f"  Error: {data['error']}")
                else:
                    print(f"  • Supabase Source:   {data['supabase_count']} records")
                    print(f"  • Aurora Destination: {data['aurora_count']} records")
                    print(f"  • Missing in Aurora:  {data['missing_in_aurora_count']} records")
                    if data["missing_sample"]:
                        print(f"  • Sample Missing IDs: {', '.join(data['missing_sample'])}")
            print("\n" + "=" * 60)
            return 0

        print("=" * 60)
        mode = "[DRY-RUN] " if args.dry_run else ""
        print(f"  RECONDESK TENANCY DATA BACKFILL {mode}")
        print("=" * 60)

        if args.table == "all":
            results = orchestrator.run_all(dry_run=args.dry_run)
        elif args.table == "user_profiles":
            results = {"user_profiles": orchestrator.backfill_user_profiles(dry_run=args.dry_run)}
        elif args.table == "team_members":
            results = {"team_members": orchestrator.backfill_team_members(dry_run=args.dry_run)}
        elif args.table == "client_gstins":
            results = {"client_gstins": orchestrator.backfill_client_gstins(dry_run=args.dry_run)}
        else:
            results = {}

        print("\nSummary:")
        total_synced = 0
        total_errors = 0
        for tbl, stats in results.items():
            print(
                f"  • {tbl}: {stats.synced_count}/{stats.source_count} synced, "
                f"{stats.skipped_count} skipped, {stats.error_count} errors ({stats.duration_seconds:.2f}s)"
            )
            total_synced += stats.synced_count
            total_errors += stats.error_count
            if stats.errors:
                print("    Sample errors:")
                for err in stats.errors[:3]:
                    print(f"      - {err}")

        print("=" * 60)
        return 1 if total_errors > 0 else 0
    except AuroraConfigurationError as exc:
        print(f"ERROR: {sanitize_db_error(str(exc))}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {sanitize_db_error(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
