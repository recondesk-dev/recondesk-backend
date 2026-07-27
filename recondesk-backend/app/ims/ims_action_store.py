"""Persistence for IMS writeback idempotency.

``filing_runs`` is one row per GSTR Save/File period — not per IMS invoice.
This table mirrors the ``rule37_actions`` unique-key pattern:
``UNIQUE (invoice_id, period, gstin)``.

Concurrency: ``try_claim_submission`` is the gate before Sandbox save.
It uses Postgres ``INSERT … ON CONFLICT DO NOTHING RETURNING`` (via RPC),
not PostgREST ``.upsert()`` (which is DO UPDATE and cannot claim safely).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import uuid4

TABLE = "ims_action_submissions"
CLAIM_RPC = "claim_ims_action_submission"

# Statuses that block a second Sandbox save for the same invoice/period/gstin.
# ``claiming`` is held from atomic claim until save+poll settles (or fails).
NON_FAILED_STATUSES: frozenset[str] = frozenset(
    {"claiming", "pending", "confirmed", "unclear"}
)

_log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_period(period: str) -> str:
    """Accept YYYY-MM or YYYY-MM-DD → YYYY-MM."""
    p = (period or "").strip()
    if len(p) >= 7 and p[4] == "-":
        return p[:7]
    raise ValueError(f"period must be YYYY-MM, got {period!r}")


def normalize_gstin(gstin: str) -> str:
    return (gstin or "").strip().upper()


class ImsActionStore(Protocol):
    def find_non_failed(
        self,
        *,
        invoice_id: str,
        period: str,
        gstin: str,
    ) -> dict[str, Any] | None: ...

    def try_claim_submission(
        self,
        *,
        invoice_id: str,
        period: str,
        gstin: str,
        chosen_action: str,
        recommended_action: str | None = None,
        submit_mode: str = "confirm_recommendation",
        run_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def upsert_submission(self, row: dict[str, Any]) -> dict[str, Any]: ...


class InMemoryImsActionStore:
    """Test double — dict keyed by (invoice_id, period, gstin).

    ``try_claim_submission`` is guarded by a lock so concurrent tests exercise
    the same single-winner semantics as the Postgres RPC.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def find_non_failed(
        self,
        *,
        invoice_id: str,
        period: str,
        gstin: str,
    ) -> dict[str, Any] | None:
        key = (invoice_id, normalize_period(period), normalize_gstin(gstin))
        with self._lock:
            row = self.rows.get(key)
            if row is None:
                return None
            if row.get("status") in NON_FAILED_STATUSES:
                return dict(row)
            return None

    def try_claim_submission(
        self,
        *,
        invoice_id: str,
        period: str,
        gstin: str,
        chosen_action: str,
        recommended_action: str | None = None,
        submit_mode: str = "confirm_recommendation",
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        key = (invoice_id, normalize_period(period), normalize_gstin(gstin))
        with self._lock:
            existing = self.rows.get(key)
            now = _now_iso()
            if existing is None:
                row = {
                    "id": f"mem-{uuid4()}",
                    "invoice_id": key[0],
                    "period": key[1],
                    "gstin": key[2],
                    "chosen_action": chosen_action,
                    "recommended_action": recommended_action,
                    "submit_mode": submit_mode or "confirm_recommendation",
                    "status": "claiming",
                    "run_id": run_id,
                    "created_at": now,
                    "updated_at": now,
                }
                self.rows[key] = row
                return dict(row)
            if existing.get("status") == "failed":
                # Atomic reclaim of failed only (mirrors RPC second branch).
                row = {
                    **existing,
                    "chosen_action": chosen_action,
                    "recommended_action": recommended_action,
                    "submit_mode": submit_mode or "confirm_recommendation",
                    "status": "claiming",
                    "run_id": run_id or existing.get("run_id"),
                    "reference_id": None,
                    "transaction_id": None,
                    "status_cd": None,
                    "error_code": None,
                    "error_message": None,
                    "raw_poll": None,
                    "updated_at": now,
                }
                self.rows[key] = row
                return dict(row)
            # Non-failed owner already exists — claim lost.
            return None

    def upsert_submission(self, row: dict[str, Any]) -> dict[str, Any]:
        key = (
            str(row["invoice_id"]),
            normalize_period(str(row["period"])),
            normalize_gstin(str(row["gstin"])),
        )
        with self._lock:
            existing = self.rows.get(key, {})
            merged = {**existing, **row}
            merged["invoice_id"] = key[0]
            merged["period"] = key[1]
            merged["gstin"] = key[2]
            merged["updated_at"] = _now_iso()
            if "created_at" not in merged:
                merged["created_at"] = merged["updated_at"]
            if "id" not in merged:
                merged["id"] = f"mem-{key[0]}"
            self.rows[key] = merged
            return dict(merged)


class SupabaseImsActionStore:
    def __init__(self, sb: Any) -> None:
        self._sb = sb

    def find_non_failed(
        self,
        *,
        invoice_id: str,
        period: str,
        gstin: str,
    ) -> dict[str, Any] | None:
        p = normalize_period(period)
        g = normalize_gstin(gstin)
        res = (
            self._sb.table(TABLE)
            .select("*")
            .eq("invoice_id", invoice_id)
            .eq("period", p)
            .eq("gstin", g)
            .in_("status", sorted(NON_FAILED_STATUSES))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def try_claim_submission(
        self,
        *,
        invoice_id: str,
        period: str,
        gstin: str,
        chosen_action: str,
        recommended_action: str | None = None,
        submit_mode: str = "confirm_recommendation",
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomic claim via RPC (INSERT DO NOTHING, else reclaim failed).

        Returns the claimed row if this caller won; ``None`` if another
        non-failed submission already owns (invoice_id, period, gstin).
        """
        payload = {
            "p_invoice_id": invoice_id,
            "p_gstin": normalize_gstin(gstin),
            "p_period": normalize_period(period),
            "p_chosen_action": chosen_action,
            "p_recommended_action": recommended_action,
            "p_submit_mode": submit_mode or "confirm_recommendation",
            "p_run_id": run_id,
        }
        res = self._sb.rpc(CLAIM_RPC, payload).execute()
        rows = res.data or []
        if isinstance(rows, dict):
            # Some clients return a single object.
            return rows
        if not rows:
            return None
        return rows[0]

    def upsert_submission(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            **row,
            "period": normalize_period(str(row["period"])),
            "gstin": normalize_gstin(str(row["gstin"])),
            "updated_at": _now_iso(),
        }
        res = (
            self._sb.table(TABLE)
            .upsert(payload, on_conflict="invoice_id,period,gstin")
            .execute()
        )
        data = res.data or []
        if data:
            return data[0]
        found = (
            self._sb.table(TABLE)
            .select("*")
            .eq("invoice_id", payload["invoice_id"])
            .eq("period", payload["period"])
            .eq("gstin", payload["gstin"])
            .limit(1)
            .execute()
        )
        if found.data:
            return found.data[0]
        _log.warning(
            "ims_action_submissions upsert returned no row: %s",
            payload.get("invoice_id"),
        )
        return payload
