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


def _fetch_tracking_row(
    client_gstin_id: UUID,
    invoice_number: str,
    supplier_gstin: str,
) -> dict | None:
    supabase = get_supabase()
    result = (
        supabase.table("invoice_tracking")
        .select("*")
        .eq("client_gstin_id", str(client_gstin_id))
        .eq("invoice_number", invoice_number)
        .eq("supplier_gstin", supplier_gstin)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


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
    """
    supabase = get_supabase()
    upserted = 0
    resolved = 0
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

        try:
            existing = _fetch_tracking_row(
                client_gstin_id, str(invoice_number), str(supplier_gstin)
            )

            if is_unmatched:
                if existing:
                    new_count = int(existing["consecutive_unmatched_runs"]) + 1
                    supabase.table("invoice_tracking").update(
                        {
                            "last_seen_run_id": str(run_id),
                            "consecutive_unmatched_runs": new_count,
                            "last_match_status": match_status,
                            "is_resolved": False,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ).eq("id", existing["id"]).execute()

                    if new_count >= CHRONIC_RISK_THRESHOLD:
                        chronic_risks.append(
                            {
                                "invoice_number": invoice_number,
                                "supplier_gstin": supplier_gstin,
                                "consecutive_unmatched_runs": new_count,
                            }
                        )
                else:
                    supabase.table("invoice_tracking").insert(
                        {
                            "client_gstin_id": str(client_gstin_id),
                            "invoice_number": invoice_number,
                            "supplier_gstin": supplier_gstin,
                            "taxable_amount": int(taxable_amount),
                            "first_seen_run_id": str(run_id),
                            "last_seen_run_id": str(run_id),
                            "consecutive_unmatched_runs": 1,
                            "last_match_status": match_status,
                            "is_resolved": False,
                        }
                    ).execute()

                upserted += 1

            elif is_matched and existing and not existing.get("is_resolved"):
                supabase.table("invoice_tracking").update(
                    {
                        "last_seen_run_id": str(run_id),
                        "last_match_status": match_status,
                        "is_resolved": True,
                        "consecutive_unmatched_runs": 0,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", existing["id"]).execute()
                resolved += 1

        except Exception as e:
            logger.error("carry_forward error for %s: %s", invoice_number, e)
            continue

    logger.info(
        "carry_forward run_id=%s: upserted=%d resolved=%d chronic=%d",
        run_id,
        upserted,
        resolved,
        len(chronic_risks),
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
