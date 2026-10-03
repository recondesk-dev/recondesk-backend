"""AWS Aurora Vendor Compliance Repository for ReconDesk — Batch 2C.

Provides safe, typed SQLAlchemy 2.x data-access for:
1. supplier_compliance_summary (Firm-level rollup of supplier compliance metrics)
2. supplier_compliance_by_client (Granular per-client supplier contributions)
3. supplier_followup_audit (Audit trail for generated vendor letters/dispatches)
4. itc_work_items (Operational exception work-item lifecycle management)
5. itc_work_item_events (Immutable timeline events on work items)
6. vendor_followup_logs (Vendor communication dispatch history and portal actions)

Architecture & Invariants:
- Aurora is PRIMARY for all six tables.
- Writes ALWAYS go to Aurora first.
- Strict tenant boundary isolation: all queries scoped by firm_owner_id or client_gstin_id.
- Safe type conversion and normalization for UUIDs, Decimals, ISO datetimes, and JSONB.
- Dialect compatibility: supports PostgreSQL in production and SQLite in testing.
- Reentrant, deadlock-free session management.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, desc as sa_desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.models.vendor_compliance import (
    ITCWorkItem,
    ITCWorkItemEvent,
    SupplierComplianceByClient,
    SupplierComplianceSummary,
    SupplierFollowupAudit,
    VendorFollowupLog,
)

_log = logging.getLogger("recondesk.aurora.vendor_compliance")


# ── Helpers & Type Converters ──────────────────────────────────────────────────

def _is_sqlite(session: Session) -> bool:
    """Return True if session is bound to a SQLite dialect."""
    return "sqlite" in str(session.bind.dialect.name) if session.bind else False


def _parse_uuid(val: Any) -> Optional[UUID]:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val).strip())
    except (ValueError, AttributeError):
        return None


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val is None or isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None
    return None


def _parse_date(val: Any) -> Optional[date]:
    if val is None or isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        s = val.strip()[:10]
        try:
            return date.fromisoformat(s)
        except Exception:
            return None
    return None


def _model_to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    out = {}
    for col in getattr(obj, "__table__", []).columns:
        val = getattr(obj, col.name, None)
        if isinstance(val, UUID):
            out[col.name] = str(val)
        elif isinstance(val, (datetime, date)):
            out[col.name] = val.isoformat()
        elif isinstance(val, Decimal):
            out[col.name] = float(val)
        else:
            out[col.name] = val
    return out


# ── Repository Implementation ──────────────────────────────────────────────────

class AuroraVendorComplianceRepository:
    """Repository for Batch 2C vendor compliance and work-item tables in AWS Aurora."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session]] = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            from app.aurora import get_aurora_sessionmaker
            self._session_factory = get_aurora_sessionmaker()

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. supplier_compliance_summary
    # ═══════════════════════════════════════════════════════════════════════════

    def list_supplier_compliance_summary(
        self,
        firm_owner_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "risk_score",
        desc: bool = True,
        prefix: Optional[str] = None,
        search: Optional[str] = None,
        client_ids_filter: Optional[Set[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List supplier compliance summary rows with filtering and pagination."""
        fid = _parse_uuid(firm_owner_id)
        if not fid:
            return [], 0

        with self._session_factory() as session:
            stmt = select(SupplierComplianceSummary).where(
                SupplierComplianceSummary.firm_owner_id == fid
            )

            if prefix and prefix.strip():
                pfx = prefix.strip().upper() + "%"
                stmt = stmt.where(
                    SupplierComplianceSummary.supplier_gstin_normalized.ilike(pfx)
                )

            if search and search.strip():
                s_term = f"%{search.strip()}%"
                stmt = stmt.where(
                    sa.or_(
                        SupplierComplianceSummary.supplier_gstin_normalized.ilike(s_term),
                        SupplierComplianceSummary.supplier_trade_name.ilike(s_term),
                    )
                )

            # Sort column
            sort_col = getattr(SupplierComplianceSummary, sort_by, SupplierComplianceSummary.risk_score)
            order_expr = sa_desc(sort_col) if desc else sort_col

            # Non-admin filtering by client overlap
            if client_ids_filter is not None:
                # Filter rows in memory or via array overlap if client_ids_filter is specified
                all_rows = session.scalars(stmt.order_by(order_expr).limit(2000)).all()
                filtered = []
                for r in all_rows:
                    cids = {str(x) for x in (r.client_gstin_ids or [])}
                    if cids & client_ids_filter:
                        filtered.append(r.to_dict())
                total = len(filtered)
                page = filtered[offset : offset + limit]
                return page, total

            # Standard count and pagination
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = session.scalar(count_stmt) or 0

            page_stmt = stmt.order_by(order_expr).offset(offset).limit(limit)
            items = [_model_to_dict(x) for x in session.scalars(page_stmt).all()]
            return items, int(total)

    def get_supplier_compliance_summary(
        self,
        firm_owner_id: str,
        supplier_gstin_normalized: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch single supplier compliance summary by firm owner and normalized GSTIN."""
        fid = _parse_uuid(firm_owner_id)
        gstin = str(supplier_gstin_normalized or "").strip().upper()
        if not fid or not gstin:
            return None

        with self._session_factory() as session:
            stmt = select(SupplierComplianceSummary).where(
                SupplierComplianceSummary.firm_owner_id == fid,
                SupplierComplianceSummary.supplier_gstin_normalized == gstin,
            ).limit(1)
            row = session.scalars(stmt).first()
            return _model_to_dict(row) if row else None

    def upsert_supplier_compliance_summary(
        self,
        row: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Upsert a supplier_compliance_summary record keyed on (firm_owner_id, supplier_gstin_normalized)."""
        fid = _parse_uuid(row.get("firm_owner_id"))
        gstin = str(row.get("supplier_gstin_normalized") or "").strip().upper()
        if not fid or not gstin:
            raise ValueError("firm_owner_id and supplier_gstin_normalized are required")

        with self._session_factory() as session:
            stmt = select(SupplierComplianceSummary).where(
                SupplierComplianceSummary.firm_owner_id == fid,
                SupplierComplianceSummary.supplier_gstin_normalized == gstin,
            ).limit(1)
            existing = session.scalars(stmt).first()

            if existing:
                for k, v in row.items():
                    if k in ("id", "firm_owner_id", "supplier_gstin_normalized"):
                        continue
                    if hasattr(existing, k):
                        if k in ("last_updated_at", "created_at"):
                            setattr(existing, k, _parse_datetime(v) or datetime.now(timezone.utc))
                        elif k in ("mismatch_rate", "late_filing_rate"):
                            setattr(existing, k, Decimal(str(v or "0")))
                        elif k in ("clients_touched_count", "total_invoices", "mismatch_invoice_count", "rule37_open_count", "rule37_at_risk_paise", "section_17_5_count", "late_filing_count", "pr_only_count", "risk_score"):
                            setattr(existing, k, int(v or 0))
                        elif k == "client_gstin_ids":
                            setattr(existing, k, [str(x) for x in (v or [])])
                        else:
                            setattr(existing, k, v)
                session.flush()
                res = existing.to_dict()
            else:
                new_id = _parse_uuid(row.get("id"))
                obj = SupplierComplianceSummary(
                    id=new_id,
                    firm_owner_id=fid,
                    supplier_gstin_normalized=gstin,
                    supplier_trade_name=row.get("supplier_trade_name", "") or "",
                    client_gstin_ids=[str(x) for x in (row.get("client_gstin_ids") or [])],
                    clients_touched_count=int(row.get("clients_touched_count") or 0),
                    total_invoices=int(row.get("total_invoices") or 0),
                    mismatch_invoice_count=int(row.get("mismatch_invoice_count") or 0),
                    mismatch_rate=Decimal(str(row.get("mismatch_rate") or "0")),
                    rule37_open_count=int(row.get("rule37_open_count") or 0),
                    rule37_at_risk_paise=int(row.get("rule37_at_risk_paise") or 0),
                    section_17_5_count=int(row.get("section_17_5_count") or 0),
                    late_filing_count=int(row.get("late_filing_count") or 0),
                    late_filing_rate=Decimal(str(row.get("late_filing_rate") or "0")),
                    pr_only_count=int(row.get("pr_only_count") or 0),
                    quarterly_filer_flag=bool(row.get("quarterly_filer_flag")),
                    risk_score=int(row.get("risk_score") or 0),
                    last_updated_at=_parse_datetime(row.get("last_updated_at")) or datetime.now(timezone.utc),
                    created_at=_parse_datetime(row.get("created_at")) or datetime.now(timezone.utc),
                )
                session.add(obj)
                session.flush()
                res = obj.to_dict()

            session.commit()
            return res

    def delete_supplier_compliance_summary(
        self,
        firm_owner_id: str,
        supplier_gstin_normalized: str,
    ) -> bool:
        """Delete supplier compliance summary row for a firm and supplier."""
        fid = _parse_uuid(firm_owner_id)
        gstin = str(supplier_gstin_normalized or "").strip().upper()
        if not fid or not gstin:
            return False

        with self._session_factory() as session:
            stmt = delete(SupplierComplianceSummary).where(
                SupplierComplianceSummary.firm_owner_id == fid,
                SupplierComplianceSummary.supplier_gstin_normalized == gstin,
            )
            res = session.execute(stmt)
            session.commit()
            return (res.rowcount or 0) > 0

    def delete_stale_summary_rows(
        self,
        firm_owner_id: str,
        valid_gstins: Set[str],
    ) -> int:
        """Delete summary rows for a firm that are not in the valid_gstins set."""
        fid = _parse_uuid(firm_owner_id)
        if not fid:
            return 0

        with self._session_factory() as session:
            existing = session.scalars(
                select(SupplierComplianceSummary.supplier_gstin_normalized).where(
                    SupplierComplianceSummary.firm_owner_id == fid
                )
            ).all()
            stale = {str(g).strip().upper() for g in existing} - {g.strip().upper() for g in valid_gstins if g}
            if not stale:
                return 0

            stmt = delete(SupplierComplianceSummary).where(
                SupplierComplianceSummary.firm_owner_id == fid,
                SupplierComplianceSummary.supplier_gstin_normalized.in_(list(stale)),
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount or 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. supplier_compliance_by_client
    # ═══════════════════════════════════════════════════════════════════════════

    def get_by_client_rows_for_supplier(
        self,
        firm_owner_id: str,
        supplier_gstin_normalized: str,
    ) -> List[Dict[str, Any]]:
        """List all granular client rows for a supplier under a firm."""
        fid = _parse_uuid(firm_owner_id)
        gstin = str(supplier_gstin_normalized or "").strip().upper()
        if not fid or not gstin:
            return []

        with self._session_factory() as session:
            stmt = select(SupplierComplianceByClient).where(
                SupplierComplianceByClient.firm_owner_id == fid,
                SupplierComplianceByClient.supplier_gstin_normalized == gstin,
            )
            rows = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in rows]

    def get_prior_supplier_gstins_for_client(
        self,
        firm_owner_id: str,
        client_gstin_id: str,
    ) -> Set[str]:
        """Return the set of supplier GSTINs currently recorded for a client."""
        fid = _parse_uuid(firm_owner_id)
        cid = _parse_uuid(client_gstin_id)
        if not fid or not cid:
            return set()

        with self._session_factory() as session:
            stmt = select(SupplierComplianceByClient.supplier_gstin_normalized).where(
                SupplierComplianceByClient.firm_owner_id == fid,
                SupplierComplianceByClient.client_gstin_id == cid,
            )
            gstins = session.scalars(stmt).all()
            return {str(g).strip().upper() for g in gstins if g}

    def replace_client_contributions(
        self,
        firm_owner_id: str,
        client_gstin_id: str,
        rows: List[Dict[str, Any]],
    ) -> Set[str]:
        """Atomically replace by_client rows for a client and return affected supplier GSTINs."""
        fid = _parse_uuid(firm_owner_id)
        cid = _parse_uuid(client_gstin_id)
        if not fid or not cid:
            return set()

        with self._session_factory() as session:
            # 1. Fetch prior suppliers for this client
            prior_stmt = select(SupplierComplianceByClient.supplier_gstin_normalized).where(
                SupplierComplianceByClient.firm_owner_id == fid,
                SupplierComplianceByClient.client_gstin_id == cid,
            )
            prior = {str(g).strip().upper() for g in session.scalars(prior_stmt).all() if g}

            # 2. Delete existing contributions for this client
            del_stmt = delete(SupplierComplianceByClient).where(
                SupplierComplianceByClient.firm_owner_id == fid,
                SupplierComplianceByClient.client_gstin_id == cid,
            )
            session.execute(del_stmt)

            # 3. Insert new rows
            now = datetime.now(timezone.utc)
            new_gstins: Set[str] = set()
            for r in rows:
                sg = str(r.get("supplier_gstin_normalized") or "").strip().upper()
                if not sg:
                    continue
                new_gstins.add(sg)
                obj = SupplierComplianceByClient(
                    id=_parse_uuid(r.get("id")),
                    firm_owner_id=fid,
                    client_gstin_id=cid,
                    supplier_gstin_normalized=sg,
                    supplier_trade_name=r.get("supplier_trade_name", "") or "",
                    total_invoices=int(r.get("total_invoices") or 0),
                    mismatch_invoice_count=int(r.get("mismatch_invoice_count") or 0),
                    rule37_open_count=int(r.get("rule37_open_count") or 0),
                    rule37_at_risk_paise=int(r.get("rule37_at_risk_paise") or 0),
                    section_17_5_count=int(r.get("section_17_5_count") or 0),
                    late_filing_count=int(r.get("late_filing_count") or 0),
                    pr_only_count=int(r.get("pr_only_count") or 0),
                    quarterly_filer_flag=bool(r.get("quarterly_filer_flag")),
                    last_updated_at=_parse_datetime(r.get("last_updated_at")) or now,
                    created_at=_parse_datetime(r.get("created_at")) or now,
                )
                session.add(obj)

            session.commit()
            return prior | new_gstins

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. supplier_followup_audit
    # ═══════════════════════════════════════════════════════════════════════════

    def insert_supplier_followup_audit(
        self,
        row_or_rows: Any,
    ) -> Any:
        """Insert immutable record(s) into supplier_followup_audit."""
        is_list = isinstance(row_or_rows, (list, tuple))
        rows = list(row_or_rows) if is_list else [row_or_rows]
        now = datetime.now(timezone.utc)
        results = []

        with self._session_factory() as session:
            for row in rows:
                rid = _parse_uuid(row.get("run_id"))
                uid = _parse_uuid(row.get("generated_by") or row.get("created_by"))
                raw_status = str(row.get("status") or "generated").strip().lower()
                status_val = raw_status if raw_status in ("generated", "downloaded", "copied") else "generated"

                raw_template = str(row.get("template_type") or "wrongful_itc_single").strip().lower()
                template_val = raw_template if raw_template in ("wrongful_itc_single", "wrongful_itc_bulk") else "wrongful_itc_single"

                period_val = str(row.get("tax_period") or "2025-01").strip()[:7]

                obj = SupplierFollowupAudit(
                    id=_parse_uuid(row.get("id")),
                    run_id=rid,
                    tax_period=period_val,
                    supplier_gstin=str(row.get("supplier_gstin") or "").strip().upper(),
                    record_ids=[str(x) for x in (row.get("record_ids") or row.get("invoice_numbers") or [])],
                    invoice_snapshot=row.get("invoice_snapshot") or {},
                    template_type=template_val,
                    generated_by=uid or uuid.uuid4(),
                    generated_at=_parse_datetime(row.get("generated_at") or row.get("created_at")) or now,
                    status=status_val,
                    supplier_name_display=row.get("supplier_name_display") or row.get("supplier_name"),
                    letter_body=row.get("letter_body"),
                )
                session.add(obj)
                session.flush()
                results.append(obj.to_dict())
            session.commit()
            return results if is_list else (results[0] if results else {})

    def list_supplier_followup_audit_for_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        supplier_gstin: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List follow-up audits for a run with optional status and supplier filtering."""
        rid = _parse_uuid(run_id)
        if not rid:
            return []

        with self._session_factory() as session:
            stmt = select(SupplierFollowupAudit).where(
                SupplierFollowupAudit.run_id == rid
            )
            if status:
                stmt = stmt.where(SupplierFollowupAudit.status == status.strip().lower())
            if supplier_gstin:
                stmt = stmt.where(
                    SupplierFollowupAudit.supplier_gstin == supplier_gstin.strip().upper()
                )
            stmt = stmt.order_by(sa_desc(SupplierFollowupAudit.generated_at))
            rows = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in rows]

    def list_supplier_followup_audit_for_runs(
        self,
        run_ids: List[str],
        *,
        status: Optional[str] = None,
        tax_period: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List follow-up audits across multiple run IDs."""
        rids = [_parse_uuid(x) for x in run_ids if _parse_uuid(x)]
        if not rids:
            return []

        with self._session_factory() as session:
            stmt = select(SupplierFollowupAudit).where(
                SupplierFollowupAudit.run_id.in_(rids)
            )
            if status:
                stmt = stmt.where(SupplierFollowupAudit.status == status.strip().lower())
            if tax_period:
                stmt = stmt.where(SupplierFollowupAudit.tax_period == tax_period.strip())
            stmt = stmt.order_by(sa_desc(SupplierFollowupAudit.generated_at))
            rows = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in rows]

    def delete_supplier_followup_audit_for_run(self, run_id: str) -> int:
        """Cascade cleanup of follow-up audits for a deleted reconciliation run."""
        rid = _parse_uuid(run_id)
        if not rid:
            return 0

        with self._session_factory() as session:
            stmt = delete(SupplierFollowupAudit).where(SupplierFollowupAudit.run_id == rid)
            res = session.execute(stmt)
            session.commit()
            return res.rowcount or 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. itc_work_items
    # ═══════════════════════════════════════════════════════════════════════════

    def get_work_item(
        self,
        work_item_id: str,
        *,
        client_gstin_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch work item by ID with optional tenant boundary check."""
        wid = _parse_uuid(work_item_id)
        if not wid:
            return None

        with self._session_factory() as session:
            stmt = select(ITCWorkItem).where(ITCWorkItem.id == wid)
            if client_gstin_id:
                cid = _parse_uuid(client_gstin_id)
                if cid:
                    stmt = stmt.where(ITCWorkItem.client_gstin_id == cid)
            item = session.scalars(stmt).first()
            return _model_to_dict(item) if item else None

    def list_work_items(
        self,
        client_gstin_id: str,
        *,
        run_id: Optional[str] = None,
        status_filter: Optional[str] = None,
        priority_filter: Optional[str] = None,
        assigned_to_filter: Optional[str] = None,
        exception_type_filter: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        exception_type: Optional[str] = None,
        vendor_gstin: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        current_user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List work items for a client with filters and pagination matching the lifecycle engine."""
        cid = _parse_uuid(client_gstin_id)
        if not cid:
            return [], 0

        status_filter = status_filter or status
        priority_filter = priority_filter or priority
        exception_type_filter = exception_type_filter or exception_type

        with self._session_factory() as session:
            stmt = select(ITCWorkItem).where(ITCWorkItem.client_gstin_id == cid)

            if run_id:
                rid = _parse_uuid(run_id)
                if rid:
                    stmt = stmt.where(ITCWorkItem.run_id == rid)

            if vendor_gstin and vendor_gstin.strip():
                stmt = stmt.where(ITCWorkItem.vendor_gstin == vendor_gstin.strip().upper())

            if status_filter:
                s_norm = status_filter.strip().upper()
                if s_norm == "BLOCKERS":
                    stmt = stmt.where(ITCWorkItem.is_blocking == True)
                elif s_norm != "ALL":
                    stmt = stmt.where(ITCWorkItem.status == s_norm)

            if priority_filter and priority_filter.strip().upper() != "ALL":
                stmt = stmt.where(ITCWorkItem.priority == priority_filter.strip().upper())

            if exception_type_filter:
                stmt = stmt.where(ITCWorkItem.exception_type == exception_type_filter.strip())

            if assigned_to_filter:
                a_norm = assigned_to_filter.strip()
                if a_norm == "UNASSIGNED":
                    stmt = stmt.where(ITCWorkItem.assigned_to.is_(None))
                elif a_norm == "MY_WORK" and current_user_id:
                    my_uid = _parse_uuid(current_user_id)
                    if my_uid:
                        stmt = stmt.where(ITCWorkItem.assigned_to == my_uid)
                elif a_norm != "ALL":
                    uid = _parse_uuid(a_norm)
                    if uid:
                        stmt = stmt.where(ITCWorkItem.assigned_to == uid)

            if search and search.strip():
                term = f"%{search.strip()}%"
                stmt = stmt.where(
                    sa.or_(
                        ITCWorkItem.invoice_number.ilike(term),
                        ITCWorkItem.vendor_name.ilike(term),
                        ITCWorkItem.vendor_gstin.ilike(term),
                        ITCWorkItem.record_id.ilike(term),
                    )
                )

            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = session.scalar(count_stmt) or 0

            # Order by is_blocking DESC, created_at DESC
            page_stmt = stmt.order_by(
                sa_desc(ITCWorkItem.is_blocking),
                sa_desc(ITCWorkItem.created_at),
            ).offset(offset).limit(limit)

            items = [_model_to_dict(x) for x in session.scalars(page_stmt).all()]
            return items, int(total)

    def insert_work_item(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a single work item."""
        fid = _parse_uuid(row.get("firm_owner_id"))
        cid = _parse_uuid(row.get("client_gstin_id"))
        rid = _parse_uuid(row.get("run_id") or row.get("reconciliation_run_id"))
        now = datetime.now(timezone.utc)

        with self._session_factory() as session:
            obj = ITCWorkItem(
                id=_parse_uuid(row.get("id")),
                firm_owner_id=fid,
                client_gstin_id=cid,
                run_id=rid,
                record_id=str(row.get("record_id") or ""),
                exception_type=str(row.get("exception_type") or ""),
                status=str(row.get("status") or "OPEN"),
                priority=str(row.get("priority") or "MEDIUM"),
                system_priority=str(row.get("system_priority") or "MEDIUM"),
                manual_priority=row.get("manual_priority"),
                priority_override_reason=row.get("priority_override_reason"),
                priority_changed_by=_parse_uuid(row.get("priority_changed_by")),
                priority_changed_at=_parse_datetime(row.get("priority_changed_at")),
                category=str(row.get("category") or "OTHER"),
                title=row.get("title"),
                what=str(row.get("what") or ""),
                why=str(row.get("why") or ""),
                next_action=str(row.get("next_action") or ""),
                assigned_to=_parse_uuid(row.get("assigned_to")),
                assigned_at=_parse_datetime(row.get("assigned_at")),
                assigned_by=_parse_uuid(row.get("assigned_by")),
                due_at=_parse_datetime(row.get("due_at")),
                sla_status=str(row.get("sla_status") or "NO_DUE_DATE"),
                resolution_code=row.get("resolution_code"),
                resolution_note=row.get("resolution_note"),
                resolved_at=_parse_datetime(row.get("resolved_at")),
                resolved_by=_parse_uuid(row.get("resolved_by")),
                dismissal_reason=row.get("dismissal_reason"),
                dismissed_at=_parse_datetime(row.get("dismissed_at")),
                dismissed_by=_parse_uuid(row.get("dismissed_by")),
                reopen_reason=row.get("reopen_reason"),
                reopened_at=_parse_datetime(row.get("reopened_at")),
                reopened_by=_parse_uuid(row.get("reopened_by")),
                revalidation_status=str(row.get("revalidation_status") or "NONE"),
                revalidation_requested_at=_parse_datetime(row.get("revalidation_requested_at")),
                revalidation_completed_at=_parse_datetime(row.get("revalidation_completed_at")),
                revalidation_result=row.get("revalidation_result"),
                source_version=int(row.get("source_version") or 1),
                carried_forward_from_id=_parse_uuid(row.get("carried_forward_from_id")),
                vendor_gstin=row.get("vendor_gstin") or row.get("supplier_gstin"),
                vendor_name=row.get("vendor_name"),
                invoice_number=row.get("invoice_number"),
                invoice_date=_parse_date(row.get("invoice_date")),
                taxable_value=Decimal(str(row.get("taxable_value") or "0")),
                igst=Decimal(str(row.get("igst") or "0")),
                cgst=Decimal(str(row.get("cgst") or "0")),
                sgst=Decimal(str(row.get("sgst") or "0")),
                cess=Decimal(str(row.get("cess") or "0")),
                total_tax=Decimal(str(row.get("total_tax") or "0")),
                itc_amount_at_stake=Decimal(str(row.get("itc_amount_at_stake") or "0")),
                itc_amount_at_stake_paise=int(row.get("itc_amount_at_stake_paise") or 0),
                is_blocking=bool(row.get("is_blocking")),
                created_at=_parse_datetime(row.get("created_at")) or now,
                created_by=_parse_uuid(row.get("created_by")),
                updated_at=_parse_datetime(row.get("updated_at")) or now,
                updated_by=_parse_uuid(row.get("updated_by")),
            )
            session.add(obj)
            session.flush()
            out = obj.to_dict()
            session.commit()
            return out

    def update_work_item(
        self,
        work_item_id: str,
        updates: Dict[str, Any],
        *,
        client_gstin_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update an existing work item."""
        wid = _parse_uuid(work_item_id)
        if not wid:
            return None

        with self._session_factory() as session:
            stmt = select(ITCWorkItem).where(ITCWorkItem.id == wid)
            if client_gstin_id:
                cid = _parse_uuid(client_gstin_id)
                if cid:
                    stmt = stmt.where(ITCWorkItem.client_gstin_id == cid)
            item = session.scalars(stmt).first()
            if not item:
                return None

            now = datetime.now(timezone.utc)
            uuid_cols = {
                "firm_owner_id", "client_gstin_id", "run_id", "priority_changed_by",
                "assigned_to", "assigned_by", "resolved_by", "dismissed_by",
                "reopened_by", "carried_forward_from_id", "created_by", "updated_by",
            }
            datetime_cols = {
                "updated_at", "resolved_at", "dismissed_at", "reopened_at", "due_at",
                "priority_changed_at", "assigned_at", "revalidation_requested_at",
                "revalidation_completed_at", "created_at",
            }
            date_cols = {"invoice_date"}
            decimal_cols = {
                "taxable_value", "igst", "cgst", "sgst", "cess", "total_tax", "itc_amount_at_stake",
            }
            int_cols = {"itc_amount_at_stake_paise", "source_version"}
            bool_cols = {"is_blocking"}

            for k, v in updates.items():
                if k == "id":
                    continue
                if hasattr(item, k):
                    if k in datetime_cols:
                        setattr(item, k, _parse_datetime(v) or (now if k == "updated_at" else None))
                    elif k in date_cols:
                        setattr(item, k, _parse_date(v))
                    elif k in uuid_cols:
                        setattr(item, k, _parse_uuid(v))
                    elif k in int_cols:
                        setattr(item, k, int(v or 0))
                    elif k in decimal_cols:
                        setattr(item, k, Decimal(str(v or "0")))
                    elif k in bool_cols:
                        setattr(item, k, bool(v))
                    else:
                        setattr(item, k, v)

            if "updated_at" not in updates:
                item.updated_at = now

            session.flush()
            out = item.to_dict()
            session.commit()
            return out

    def get_existing_work_items_map_for_run(
        self,
        run_id: str,
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """Fetch existing work items for a run indexed by (record_id, exception_type)."""
        rid = _parse_uuid(run_id)
        if not rid:
            return {}

        with self._session_factory() as session:
            stmt = select(ITCWorkItem).where(ITCWorkItem.run_id == rid)
            rows = session.scalars(stmt).all()
            return {
                (r.record_id, r.exception_type): _model_to_dict(r)
                for r in rows
            }

    def delete_work_items_for_run(self, run_id: str) -> int:
        """Cascade delete work items for a deleted run."""
        rid = _parse_uuid(run_id)
        if not rid:
            return 0

        with self._session_factory() as session:
            stmt = delete(ITCWorkItem).where(ITCWorkItem.run_id == rid)
            res = session.execute(stmt)
            session.commit()
            return res.rowcount or 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. itc_work_item_events
    # ═══════════════════════════════════════════════════════════════════════════

    def insert_work_item_event(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Insert an immutable work item activity event."""
        wid = _parse_uuid(row.get("work_item_id"))
        aid = _parse_uuid(row.get("actor_id") or row.get("performed_by_user_id"))
        now = datetime.now(timezone.utc)

        with self._session_factory() as session:
            obj = ITCWorkItemEvent(
                id=_parse_uuid(row.get("id")),
                work_item_id=wid,
                event_type=str(row.get("event_type") or ""),
                from_status=row.get("from_status"),
                to_status=row.get("to_status"),
                actor_id=aid,
                actor_role=row.get("actor_role"),
                actor_name=row.get("actor_name"),
                note=row.get("note"),
                metadata_payload=row.get("metadata") or row.get("event_metadata") or {},
                created_at=_parse_datetime(row.get("created_at")) or now,
            )
            session.add(obj)
            session.flush()
            out = obj.to_dict()
            session.commit()
            return out

    def list_work_item_events(self, work_item_id: str) -> List[Dict[str, Any]]:
        """List all events for a work item ordered chronologically."""
        wid = _parse_uuid(work_item_id)
        if not wid:
            return []

        with self._session_factory() as session:
            stmt = select(ITCWorkItemEvent).where(
                ITCWorkItemEvent.work_item_id == wid
            ).order_by(ITCWorkItemEvent.created_at.asc())
            rows = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in rows]

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. vendor_followup_logs
    # ═══════════════════════════════════════════════════════════════════════════

    def insert_vendor_followup_log(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a vendor follow-up dispatch log."""
        cid = _parse_uuid(row.get("client_gstin_id"))
        wid = _parse_uuid(row.get("work_item_id"))
        uid = _parse_uuid(row.get("dispatched_by") or row.get("user_id"))
        now = datetime.now(timezone.utc)

        with self._session_factory() as session:
            obj = VendorFollowupLog(
                id=_parse_uuid(row.get("id")),
                client_gstin_id=cid,
                supplier_gstin=str(row.get("supplier_gstin") or "").strip().upper(),
                supplier_name=row.get("supplier_name"),
                vendor_phone=row.get("vendor_phone"),
                vendor_email=row.get("vendor_email"),
                channel=str(row.get("channel") or "WHATSAPP"),
                template_type=str(row.get("template_type") or "POLITE_REMINDER"),
                invoices_count=int(row.get("invoices_count") or 1),
                at_risk_itc_rupees=Decimal(str(row.get("at_risk_itc_rupees") or "0.00")),
                status=str(row.get("status") or "SENT"),
                notes=row.get("notes"),
                dispatched_by=uid,
                dispatched_at=_parse_datetime(row.get("dispatched_at")) or now,
                work_item_id=wid,
                message_body=row.get("message_body"),
                token=row.get("token"),
                viewed_at=_parse_datetime(row.get("viewed_at")),
                arn_number=row.get("arn_number"),
                promised_period=row.get("promised_period"),
                dispute_reason=row.get("dispute_reason"),
                attachment_key=row.get("attachment_key"),
                expires_at=_parse_datetime(row.get("expires_at")),
                invoices_snapshot=row.get("invoices_snapshot"),
                response_action=row.get("response_action"),
                responded_at=_parse_datetime(row.get("responded_at")),
            )
            session.add(obj)
            session.flush()
            out = obj.to_dict()
            session.commit()
            return out

    def get_vendor_followup_log_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Fetch follow-up dispatch log by its secure portal token."""
        tok = str(token or "").strip()
        if not tok:
            return None

        with self._session_factory() as session:
            stmt = select(VendorFollowupLog).where(VendorFollowupLog.token == tok).limit(1)
            row = session.scalars(stmt).first()
            return _model_to_dict(row) if row else None

    def get_vendor_followup_log_by_id(self, log_id: str) -> Optional[Dict[str, Any]]:
        """Fetch follow-up dispatch log by primary key ID."""
        lid = _parse_uuid(log_id)
        if not lid:
            return None

        with self._session_factory() as session:
            row = session.get(VendorFollowupLog, lid)
            return _model_to_dict(row) if row else None

    def update_vendor_followup_log(
        self,
        log_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update follow-up log record (e.g. token access, portal action)."""
        lid = _parse_uuid(log_id)
        if not lid:
            return None

        with self._session_factory() as session:
            row = session.get(VendorFollowupLog, lid)
            if not row:
                return None

            now = datetime.now(timezone.utc)
            datetime_cols = {
                "dispatched_at", "viewed_at", "expires_at", "responded_at",
            }
            uuid_cols = {"client_gstin_id", "work_item_id", "dispatched_by"}

            for k, v in updates.items():
                if k == "id":
                    continue
                if hasattr(row, k):
                    if k in datetime_cols:
                        setattr(row, k, _parse_datetime(v) or (now if "at" in k else None))
                    elif k in uuid_cols:
                        setattr(row, k, _parse_uuid(v))
                    elif k == "invoices_count":
                        setattr(row, k, int(v or 1))
                    elif k == "at_risk_itc_rupees":
                        setattr(row, k, Decimal(str(v or "0.00")))
                    else:
                        setattr(row, k, v)

            session.flush()
            out = row.to_dict()
            session.commit()
            return out

    def update_vendor_followup_logs_by_supplier(
        self,
        client_gstin_id: str,
        supplier_gstin: str,
        updates: Dict[str, Any],
    ) -> int:
        """Update contact info or status on followup logs for a supplier under a client."""
        cid = _parse_uuid(client_gstin_id)
        sg = str(supplier_gstin or "").strip().upper()
        if not cid or not sg:
            return 0

        with self._session_factory() as session:
            stmt = select(VendorFollowupLog).where(
                VendorFollowupLog.client_gstin_id == cid,
                VendorFollowupLog.supplier_gstin == sg,
            )
            rows = session.scalars(stmt).all()
            for row in rows:
                for k, v in updates.items():
                    if hasattr(row, k) and k != "id":
                        setattr(row, k, v)
            session.flush()
            session.commit()
            return len(rows)

    def list_vendor_followup_logs_for_client(
        self,
        client_gstin_id: str,
        *,
        supplier_gstin: Optional[str] = None,
        work_item_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List follow-up logs for a client ordered by dispatched_at DESC."""
        cid = _parse_uuid(client_gstin_id)
        if not cid:
            return []

        with self._session_factory() as session:
            stmt = select(VendorFollowupLog).where(
                VendorFollowupLog.client_gstin_id == cid
            )
            if supplier_gstin:
                stmt = stmt.where(
                    VendorFollowupLog.supplier_gstin == supplier_gstin.strip().upper()
                )
            if work_item_id:
                wid = _parse_uuid(work_item_id)
                if wid:
                    stmt = stmt.where(VendorFollowupLog.work_item_id == wid)

            stmt = stmt.order_by(sa_desc(VendorFollowupLog.dispatched_at)).offset(offset).limit(limit)
            rows = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in rows]

    def list_vendor_followup_logs_for_work_item(
        self,
        work_item_id: str,
        *,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """List follow-up logs specifically linked to a work item."""
        wid = _parse_uuid(work_item_id)
        if not wid:
            return []

        with self._session_factory() as session:
            stmt = select(VendorFollowupLog).where(
                VendorFollowupLog.work_item_id == wid
            ).order_by(sa_desc(VendorFollowupLog.dispatched_at)).limit(limit)
            rows = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in rows]

    def update_supplier_compliance_summary_by_gstin(
        self,
        supplier_gstin_normalized: str,
        updates: Dict[str, Any],
    ) -> int:
        """Update summary rows matching a normalized supplier GSTIN across firms."""
        gstin = str(supplier_gstin_normalized or "").strip().upper()
        if not gstin:
            return 0

        with self._session_factory() as session:
            stmt = select(SupplierComplianceSummary).where(
                SupplierComplianceSummary.supplier_gstin_normalized == gstin
            )
            rows = session.scalars(stmt).all()
            for r in rows:
                for k, v in updates.items():
                    if hasattr(r, k) and k not in ("id", "firm_owner_id", "supplier_gstin_normalized"):
                        setattr(r, k, v)
            session.flush()
            session.commit()
            return len(rows)

    def list_all_supplier_compliance_summaries(self) -> List[Dict[str, Any]]:
        """List all supplier compliance summaries across firms (e.g. for vendor risk calculations)."""
        with self._session_factory() as session:
            rows = session.scalars(select(SupplierComplianceSummary)).all()
            return [_model_to_dict(r) for r in rows]


# ── Global Singleton Factory ──────────────────────────────────────────────────

_vendor_compliance_repo: Optional[AuroraVendorComplianceRepository] = None


def get_vendor_compliance_repository() -> Optional[AuroraVendorComplianceRepository]:
    """Return the module-level AuroraVendorComplianceRepository singleton.

    Returns None when Aurora is not configured.
    """
    global _vendor_compliance_repo
    if _vendor_compliance_repo is not None:
        return _vendor_compliance_repo
    try:
        from app.aurora import get_aurora_sessionmaker
        sf = get_aurora_sessionmaker()
        _vendor_compliance_repo = AuroraVendorComplianceRepository(session_factory=sf)
        return _vendor_compliance_repo
    except Exception as exc:
        _log.debug("Aurora vendor compliance repository unavailable: %s", exc)
        return None


def set_vendor_compliance_repository(repo: Optional[AuroraVendorComplianceRepository]) -> None:
    """Set the module-level AuroraVendorComplianceRepository singleton (primarily for testing)."""
    global _vendor_compliance_repo
    _vendor_compliance_repo = repo
