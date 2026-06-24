"""
Cross-run carry-forward service.

After each reconciliation run completes, call ``update_invoice_tracking()``
to persist unmatched invoice state across runs.

Key logic:
- If an invoice is unmatched/missed_itc: upsert into invoice_tracking,
  increment consecutive_unmatched_runs
- If an invoice is now matched: mark is_resolved=True, reset counter
- Consecutive unmatched runs >= 3 → flag as chronic ITC risk

Run the following in the Supabase SQL editor (not applied via Alembic):

    create table if not exists invoice_tracking (
        id uuid primary key default gen_random_uuid(),
        client_gstin_id uuid not null references client_gstins(id) on delete cascade,
        invoice_number text not null,
        supplier_gstin text not null,
        taxable_amount bigint not null,
        first_seen_run_id uuid not null references reconciliation_run(id),
        last_seen_run_id uuid not null references reconciliation_run(id),
        consecutive_unmatched_runs int not null default 1,
        last_match_status text not null,
        is_resolved boolean not null default false,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
    );

    create unique index if not exists idx_invoice_tracking_unique
        on invoice_tracking(client_gstin_id, invoice_number, supplier_gstin);

    create index if not exists idx_invoice_tracking_client
        on invoice_tracking(client_gstin_id);

    create index if not exists idx_invoice_tracking_unresolved
        on invoice_tracking(client_gstin_id, is_resolved)
        where is_resolved = false;
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from app.database import get_supabase

logger = logging.getLogger(__name__)

CHRONIC_RISK_THRESHOLD = 3  # consecutive unmatched runs before flagging

# PR ``record_data.match_status`` values written by reconciliation_task.
_UNMATCHED_STATUSES = frozenset(
    {"missed_itc", "unmatched", "probable", "missing_in_2b"}
)
_MATCHED_STATUSES = frozenset({"matched", "wrongful_claim"})

# How many rows to fetch / upsert per DB round-trip.
_PAGE_SIZE = 1000
_UPSERT_BATCH = 200


def _bulk_fetch_tracking_rows(
    supabase,
    client_gstin_id: UUID,
) -> dict[tuple[str, str], dict]:
    """Fetch ALL existing tracking rows for this client in one paginated read.

    Returns a dict keyed by (invoice_number, supplier_gstin).
    This replaces the previous per-row SELECT that caused N+1 timeouts.
    """
    index: dict[tuple[str, str], dict] = {}
    offset = 0
    while True:
        result = (
            supabase.table("invoice_tracking")
            .select(
                "id, invoice_number, supplier_gstin, "
                "consecutive_unmatched_runs, is_resolved"
            )
            .eq("client_gstin_id", str(client_gstin_id))
            .order("id")
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            key = (str(row["invoice_number"]), str(row["supplier_gstin"]))
            index[key] = row
        if len(rows) < _PAGE_SIZE:
            break
        offset += len(rows)
    return index


def _batched_upsert(supabase, table: str, rows: list[dict], on_conflict: str) -> None:
    for i in range(0, len(rows), _UPSERT_BATCH):
        chunk = rows[i : i + _UPSERT_BATCH]
        try:
            supabase.table(table).upsert(chunk, on_conflict=on_conflict).execute()
        except Exception as exc:
            logger.error(
                "carry_forward batched upsert into %s failed (batch %d, size %d): %s",
                table, i // _UPSERT_BATCH, len(chunk), exc,
            )


async def update_invoice_tracking(
    client_gstin_id: UUID,
    run_id: UUID,
    pr_records: list[dict],
) -> dict:
    """
    Called at end of reconciliation_task.py after all records are written.

    pr_records: list of dicts with keys:
        invoice_number, supplier_gstin, taxable_amount, match_status
        (match_status from record_data JSONB)

    Returns summary: {upserted, resolved, chronic_risks}

    Performance: O(1) bulk fetch + O(ceil(n/200)) batched upserts instead
    of the previous O(n) per-row SELECT + individual INSERT/UPDATE.
    """
    supabase = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. Bulk-fetch all existing tracking rows for this client ──────────────
    existing_index = _bulk_fetch_tracking_rows(supabase, client_gstin_id)
    logger.info(
        "carry_forward run_id=%s: fetched %d existing tracking rows for client=%s",
        run_id, len(existing_index), client_gstin_id,
    )

    # ── 2. Classify each PR record in Python (zero extra DB queries) ──────────
    rows_to_insert: list[dict] = []
    rows_to_update: list[dict] = []
    chronic_risks: list[dict] = []

    for row in pr_records:
        invoice_number = row.get("invoice_number")
        supplier_gstin = row.get("supplier_gstin") or row.get("gstin")
        taxable_amount = row.get("taxable_amount")
        match_status = row.get("match_status")

        if not all([invoice_number, supplier_gstin, taxable_amount, match_status]):
            continue

        is_unmatched = match_status in _UNMATCHED_STATUSES
        is_matched = match_status in _MATCHED_STATUSES

        key = (str(invoice_number), str(supplier_gstin))
        existing = existing_index.get(key)

        try:
            if is_unmatched:
                if existing:
                    new_count = int(existing["consecutive_unmatched_runs"]) + 1
                    rows_to_update.append(
                        {
                            "id": existing["id"],
                            "last_seen_run_id": str(run_id),
                            "consecutive_unmatched_runs": new_count,
                            "last_match_status": match_status,
                            "is_resolved": False,
                            "updated_at": now_iso,
                        }
                    )
                    if new_count >= CHRONIC_RISK_THRESHOLD:
                        chronic_risks.append(
                            {
                                "invoice_number": invoice_number,
                                "supplier_gstin": supplier_gstin,
                                "consecutive_unmatched_runs": new_count,
                            }
                        )
                else:
                    rows_to_insert.append(
                        {
                            "client_gstin_id": str(client_gstin_id),
                            "invoice_number": str(invoice_number),
                            "supplier_gstin": str(supplier_gstin),
                            "taxable_amount": int(taxable_amount),
                            "first_seen_run_id": str(run_id),
                            "last_seen_run_id": str(run_id),
                            "consecutive_unmatched_runs": 1,
                            "last_match_status": match_status,
                            "is_resolved": False,
                        }
                    )

            elif is_matched and existing and not existing.get("is_resolved"):
                rows_to_update.append(
                    {
                        "id": existing["id"],
                        "last_seen_run_id": str(run_id),
                        "last_match_status": match_status,
                        "is_resolved": True,
                        "consecutive_unmatched_runs": 0,
                        "updated_at": now_iso,
                    }
                )

        except Exception as exc:
            logger.error(
                "carry_forward classification error for %s: %s", invoice_number, exc
            )
            continue

    # ── 3. Batched writes ─────────────────────────────────────────────────────
    upserted = len(rows_to_insert) + len(
        [r for r in rows_to_update if not r.get("is_resolved")]
    )
    resolved = len([r for r in rows_to_update if r.get("is_resolved")])

    if rows_to_insert:
        _batched_upsert(supabase, "invoice_tracking", rows_to_insert, "id")

    if rows_to_update:
        _batched_upsert(supabase, "invoice_tracking", rows_to_update, "id")

    logger.info(
        "carry_forward run_id=%s: inserts=%d updates=%d resolved=%d chronic=%d",
        run_id, len(rows_to_insert), len(rows_to_update), resolved, len(chronic_risks),
    )
    return {"upserted": upserted, "resolved": resolved, "chronic_risks": chronic_risks}


async def get_chronic_risks(client_gstin_id: UUID) -> list[dict]:
    """
    Returns all unresolved invoices that have been unmatched for
    >= CHRONIC_RISK_THRESHOLD consecutive runs. Used by Results API.
    """
    supabase = get_supabase()
    result = (
        supabase.table("invoice_tracking")
        .select("*")
        .eq("client_gstin_id", str(client_gstin_id))
        .eq("is_resolved", False)
        .gte("consecutive_unmatched_runs", CHRONIC_RISK_THRESHOLD)
        .order("consecutive_unmatched_runs", desc=True)
        .execute()
    )

    return result.data or []
