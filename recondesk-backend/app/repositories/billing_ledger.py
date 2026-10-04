"""AWS Aurora Billing & E-Invoicing Ledger Repository for ReconDesk — Batch 4B.

Provides typed, safe SQLAlchemy 2.x data access for:
1. billing_company_profiles (Seller details, GST credentials, sequence counters)
2. billing_customers (B2B/B2C buyers)
3. billing_items (Item/HSN catalog)
4. billing_invoices (Invoices & IRP registration metadata)
5. billing_invoice_line_items (Itemized lines with tax computations)
6. billing_credit_debit_notes (Credit/Debit notes linked to invoices)
7. billing_cdn_line_items (Itemized CDN lines)
8. billing_irp_submission_log (Immutable IRP audit logs)
RPC:
- increment_invoice_number_seq(p_profile_id uuid)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, desc as sa_desc, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
    get_aurora_session,
)
from app.models.billing_ledger import (
    BillingCdnLineItem,
    BillingCompanyProfile,
    BillingCreditDebitNote,
    BillingCustomer,
    BillingInvoice,
    BillingInvoiceLineItem,
    BillingIrpSubmissionLog,
    BillingItem,
)

_log = logging.getLogger("recondesk.aurora.billing_ledger")


def _parse_uuid(val: Any) -> Optional[UUID]:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val.strip()[:10])
        except ValueError:
            return None
    return None


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


class AuroraBillingLedgerRepository:
    """Safe, typed data access layer for Batch 4B entities."""

    def __init__(self, session_factory: Optional[sessionmaker[Session]] = None) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        if self._session_factory is not None:
            return self._session_factory()
        return get_aurora_session()

    # ── 1. Company Profiles ───────────────────────────────────────────────────

    def get_company_profile(
        self,
        profile_id: str | UUID,
        client_gstin_id: Optional[str | UUID] = None,
        *,
        redact_sensitive: bool = False,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        p_id = _parse_uuid(profile_id)
        if not p_id:
            return None

        def _query(s: Session) -> Optional[Dict[str, Any]]:
            stmt = select(BillingCompanyProfile).where(BillingCompanyProfile.id == p_id)
            if client_gstin_id:
                c_id = _parse_uuid(client_gstin_id)
                if c_id:
                    stmt = stmt.where(BillingCompanyProfile.client_gstin_id == c_id)
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict(redact_sensitive=redact_sensitive) if obj else None

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def list_company_profiles(
        self,
        client_gstin_id: str | UUID,
        *,
        redact_sensitive: bool = False,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        c_id = _parse_uuid(client_gstin_id)
        if not c_id:
            return []

        def _query(s: Session) -> List[Dict[str, Any]]:
            stmt = (
                select(BillingCompanyProfile)
                .where(BillingCompanyProfile.client_gstin_id == c_id)
                .order_by(sa_desc(BillingCompanyProfile.created_at))
            )
            objs = s.execute(stmt).scalars().all()
            return [o.to_dict(redact_sensitive=redact_sensitive) for o in objs]

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def create_company_profile(
        self,
        profile_data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        clean = dict(profile_data)
        if "id" in clean and clean["id"]:
            clean["id"] = _parse_uuid(clean["id"])
        if "client_gstin_id" in clean:
            clean["client_gstin_id"] = _parse_uuid(clean["client_gstin_id"])

        obj = BillingCompanyProfile(**clean)

        def _execute(s: Session) -> Dict[str, Any]:
            s.add(obj)
            s.flush()
            return obj.to_dict(redact_sensitive=False)

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def update_company_profile(
        self,
        profile_id: str | UUID,
        client_gstin_id: str | UUID,
        update_data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        p_id = _parse_uuid(profile_id)
        c_id = _parse_uuid(client_gstin_id)
        if not p_id or not c_id:
            return None

        clean = dict(update_data)
        clean["updated_at"] = datetime.now(timezone.utc)

        def _execute(s: Session) -> Optional[Dict[str, Any]]:
            stmt = (
                update(BillingCompanyProfile)
                .where(
                    BillingCompanyProfile.id == p_id,
                    BillingCompanyProfile.client_gstin_id == c_id,
                )
                .values(**clean)
                .returning(BillingCompanyProfile)
            )
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict(redact_sensitive=False) if obj else None

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def increment_invoice_number_seq(
        self,
        profile_id: str | UUID,
        session: Optional[Session] = None,
    ) -> Tuple[str, int]:
        """Atomically increment invoice number sequence for the profile.
        
        Returns (prefix, seq_number).
        Uses PostgreSQL RPC public.increment_invoice_number_seq when available,
        falling back to row-locking atomic update.
        """
        p_id = _parse_uuid(profile_id)
        if not p_id:
            raise ValueError(f"Invalid profile_id: {profile_id}")

        def _execute(s: Session) -> Tuple[str, int]:
            bind = s.get_bind()
            if bind.dialect.name == "postgresql":
                try:
                    res = s.execute(
                        sa.text("SELECT prefix, seq FROM public.increment_invoice_number_seq(:p_id)"),
                        {"p_id": p_id},
                    ).first()
                    if res:
                        return (str(res[0] or ""), int(res[1]))
                except Exception as exc:
                    _log.warning("Direct RPC invocation failed, using row lock update: %s", exc)

            stmt = (
                select(BillingCompanyProfile)
                .where(BillingCompanyProfile.id == p_id)
                .with_for_update()
            )
            profile = s.execute(stmt).scalar_one_or_none()
            if not profile:
                raise ValueError(f"Company profile not found: {profile_id}")

            prefix = profile.invoice_number_prefix or ""
            curr_seq = int(profile.invoice_number_next_seq)
            profile.invoice_number_next_seq = curr_seq + 1
            profile.updated_at = datetime.now(timezone.utc)
            s.flush()
            return (prefix, curr_seq)

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def increment_cdn_number_seq(
        self,
        profile_id: str | UUID,
        session: Optional[Session] = None,
    ) -> Tuple[str, int]:
        """Atomically increment CDN number sequence for the profile."""
        p_id = _parse_uuid(profile_id)
        if not p_id:
            raise ValueError(f"Invalid profile_id: {profile_id}")

        def _execute(s: Session) -> Tuple[str, int]:
            stmt = (
                select(BillingCompanyProfile)
                .where(BillingCompanyProfile.id == p_id)
                .with_for_update()
            )
            profile = s.execute(stmt).scalar_one_or_none()
            if not profile:
                raise ValueError(f"Company profile not found: {profile_id}")

            prefix = profile.cdn_number_prefix or "CRN/"
            curr_seq = int(profile.cdn_number_next_seq)
            profile.cdn_number_next_seq = curr_seq + 1
            profile.updated_at = datetime.now(timezone.utc)
            s.flush()
            return (prefix, curr_seq)

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    # ── 2. Customers ──────────────────────────────────────────────────────────

    def get_customer(
        self,
        customer_id: str | UUID,
        client_gstin_id: Optional[str | UUID] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        c_id = _parse_uuid(customer_id)
        if not c_id:
            return None

        def _query(s: Session) -> Optional[Dict[str, Any]]:
            stmt = select(BillingCustomer).where(BillingCustomer.id == c_id)
            if client_gstin_id:
                cg_id = _parse_uuid(client_gstin_id)
                if cg_id:
                    stmt = stmt.where(BillingCustomer.client_gstin_id == cg_id)
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict() if obj else None

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def list_customers(
        self,
        client_gstin_id: str | UUID,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        cg_id = _parse_uuid(client_gstin_id)
        if not cg_id:
            return []

        def _query(s: Session) -> List[Dict[str, Any]]:
            stmt = (
                select(BillingCustomer)
                .where(BillingCustomer.client_gstin_id == cg_id)
                .order_by(sa_desc(BillingCustomer.created_at))
            )
            objs = s.execute(stmt).scalars().all()
            return [o.to_dict() for o in objs]

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def create_customer(
        self,
        customer_data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        clean = dict(customer_data)
        if "id" in clean and clean["id"]:
            clean["id"] = _parse_uuid(clean["id"])
        if "client_gstin_id" in clean:
            clean["client_gstin_id"] = _parse_uuid(clean["client_gstin_id"])

        obj = BillingCustomer(**clean)

        def _execute(s: Session) -> Dict[str, Any]:
            s.add(obj)
            s.flush()
            return obj.to_dict()

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def update_customer(
        self,
        customer_id: str | UUID,
        client_gstin_id: str | UUID,
        update_data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        c_id = _parse_uuid(customer_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not c_id or not cg_id:
            return None

        clean = dict(update_data)
        clean["updated_at"] = datetime.now(timezone.utc)

        def _execute(s: Session) -> Optional[Dict[str, Any]]:
            stmt = (
                update(BillingCustomer)
                .where(
                    BillingCustomer.id == c_id,
                    BillingCustomer.client_gstin_id == cg_id,
                )
                .values(**clean)
                .returning(BillingCustomer)
            )
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict() if obj else None

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def delete_customer(
        self,
        customer_id: str | UUID,
        client_gstin_id: str | UUID,
        session: Optional[Session] = None,
    ) -> bool:
        c_id = _parse_uuid(customer_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not c_id or not cg_id:
            return False

        def _execute(s: Session) -> bool:
            stmt = (
                delete(BillingCustomer)
                .where(
                    BillingCustomer.id == c_id,
                    BillingCustomer.client_gstin_id == cg_id,
                )
            )
            res = s.execute(stmt)
            return res.rowcount > 0

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    # ── 3. Items Catalog ──────────────────────────────────────────────────────

    def get_item(
        self,
        item_id: str | UUID,
        client_gstin_id: Optional[str | UUID] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        i_id = _parse_uuid(item_id)
        if not i_id:
            return None

        def _query(s: Session) -> Optional[Dict[str, Any]]:
            stmt = select(BillingItem).where(BillingItem.id == i_id)
            if client_gstin_id:
                cg_id = _parse_uuid(client_gstin_id)
                if cg_id:
                    stmt = stmt.where(BillingItem.client_gstin_id == cg_id)
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict() if obj else None

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def list_items(
        self,
        client_gstin_id: str | UUID,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        cg_id = _parse_uuid(client_gstin_id)
        if not cg_id:
            return []

        def _query(s: Session) -> List[Dict[str, Any]]:
            stmt = (
                select(BillingItem)
                .where(BillingItem.client_gstin_id == cg_id)
                .order_by(BillingItem.name)
            )
            objs = s.execute(stmt).scalars().all()
            return [o.to_dict() for o in objs]

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def create_item(
        self,
        item_data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        clean = dict(item_data)
        if "id" in clean and clean["id"]:
            clean["id"] = _parse_uuid(clean["id"])
        if "client_gstin_id" in clean:
            clean["client_gstin_id"] = _parse_uuid(clean["client_gstin_id"])

        obj = BillingItem(**clean)

        def _execute(s: Session) -> Dict[str, Any]:
            s.add(obj)
            s.flush()
            return obj.to_dict()

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def update_item(
        self,
        item_id: str | UUID,
        client_gstin_id: str | UUID,
        update_data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        i_id = _parse_uuid(item_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not i_id or not cg_id:
            return None

        clean = dict(update_data)
        clean["updated_at"] = datetime.now(timezone.utc)

        def _execute(s: Session) -> Optional[Dict[str, Any]]:
            stmt = (
                update(BillingItem)
                .where(
                    BillingItem.id == i_id,
                    BillingItem.client_gstin_id == cg_id,
                )
                .values(**clean)
                .returning(BillingItem)
            )
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict() if obj else None

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def delete_item(
        self,
        item_id: str | UUID,
        client_gstin_id: str | UUID,
        session: Optional[Session] = None,
    ) -> bool:
        i_id = _parse_uuid(item_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not i_id or not cg_id:
            return False

        def _execute(s: Session) -> bool:
            stmt = (
                delete(BillingItem)
                .where(
                    BillingItem.id == i_id,
                    BillingItem.client_gstin_id == cg_id,
                )
            )
            res = s.execute(stmt)
            return res.rowcount > 0

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    # ── 4. Invoices & Line Items ──────────────────────────────────────────────

    def get_invoice(
        self,
        invoice_id: str | UUID,
        client_gstin_id: Optional[str | UUID] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        inv_id = _parse_uuid(invoice_id)
        if not inv_id:
            return None

        def _query(s: Session) -> Optional[Dict[str, Any]]:
            stmt = select(BillingInvoice).where(BillingInvoice.id == inv_id)
            if client_gstin_id:
                cg_id = _parse_uuid(client_gstin_id)
                if cg_id:
                    stmt = stmt.where(BillingInvoice.client_gstin_id == cg_id)
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict() if obj else None

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def get_invoice_detail(
        self,
        invoice_id: str | UUID,
        client_gstin_id: Optional[str | UUID] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        inv_id = _parse_uuid(invoice_id)
        if not inv_id:
            return None

        def _query(s: Session) -> Optional[Dict[str, Any]]:
            stmt = select(BillingInvoice).where(BillingInvoice.id == inv_id)
            if client_gstin_id:
                cg_id = _parse_uuid(client_gstin_id)
                if cg_id:
                    stmt = stmt.where(BillingInvoice.client_gstin_id == cg_id)
            inv = s.execute(stmt).scalar_one_or_none()
            if not inv:
                return None

            inv_dict = inv.to_dict()

            # Company Profile
            cp = s.get(BillingCompanyProfile, inv.company_profile_id)
            inv_dict["company_profile"] = cp.to_dict(redact_sensitive=False) if cp else None

            # Customer
            cust = s.get(BillingCustomer, inv.customer_id)
            inv_dict["customer"] = cust.to_dict() if cust else None

            # Line items
            lines_stmt = (
                select(BillingInvoiceLineItem)
                .where(BillingInvoiceLineItem.invoice_id == inv_id)
            )
            lines = s.execute(lines_stmt).scalars().all()
            inv_dict["line_items"] = [l.to_dict() for l in lines]

            return inv_dict

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def list_invoices(
        self,
        client_gstin_id: str | UUID,
        status: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        cg_id = _parse_uuid(client_gstin_id)
        if not cg_id:
            return []

        def _query(s: Session) -> List[Dict[str, Any]]:
            stmt = (
                select(BillingInvoice)
                .where(BillingInvoice.client_gstin_id == cg_id)
            )
            if status:
                stmt = stmt.where(BillingInvoice.status == status)
            stmt = stmt.order_by(sa_desc(BillingInvoice.created_at))
            objs = s.execute(stmt).scalars().all()
            return [o.to_dict() for o in objs]

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def create_invoice(
        self,
        invoice_data: Dict[str, Any],
        line_items_data: Sequence[Dict[str, Any]],
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Create invoice and its itemized line items atomically."""
        clean_inv = dict(invoice_data)
        if "id" in clean_inv and clean_inv["id"]:
            clean_inv["id"] = _parse_uuid(clean_inv["id"])
        if "client_gstin_id" in clean_inv:
            clean_inv["client_gstin_id"] = _parse_uuid(clean_inv["client_gstin_id"])
        if "company_profile_id" in clean_inv:
            clean_inv["company_profile_id"] = _parse_uuid(clean_inv["company_profile_id"])
        if "customer_id" in clean_inv:
            clean_inv["customer_id"] = _parse_uuid(clean_inv["customer_id"])
        if "invoice_date" in clean_inv:
            clean_inv["invoice_date"] = _parse_date(clean_inv["invoice_date"])
        if "due_date" in clean_inv and clean_inv["due_date"]:
            clean_inv["due_date"] = _parse_date(clean_inv["due_date"])

        inv_obj = BillingInvoice(**clean_inv)

        def _execute(s: Session) -> Dict[str, Any]:
            s.add(inv_obj)
            s.flush()

            inserted_lines: List[BillingInvoiceLineItem] = []
            for item in line_items_data:
                clean_item = dict(item)
                if "id" in clean_item and clean_item["id"]:
                    clean_item["id"] = _parse_uuid(clean_item["id"])
                clean_item["invoice_id"] = inv_obj.id
                if "item_id" in clean_item and clean_item["item_id"]:
                    clean_item["item_id"] = _parse_uuid(clean_item["item_id"])

                line_obj = BillingInvoiceLineItem(**clean_item)
                s.add(line_obj)
                inserted_lines.append(line_obj)

            s.flush()
            result = inv_obj.to_dict()
            result["line_items"] = [l.to_dict() for l in inserted_lines]
            return result

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def update_invoice(
        self,
        invoice_id: str | UUID,
        client_gstin_id: str | UUID,
        invoice_data: Dict[str, Any],
        line_items_data: Optional[Sequence[Dict[str, Any]]] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        inv_id = _parse_uuid(invoice_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not inv_id or not cg_id:
            return None

        clean_inv = dict(invoice_data)
        clean_inv["updated_at"] = datetime.now(timezone.utc)
        if "customer_id" in clean_inv and clean_inv["customer_id"]:
            clean_inv["customer_id"] = _parse_uuid(clean_inv["customer_id"])
        if "invoice_date" in clean_inv and clean_inv["invoice_date"]:
            clean_inv["invoice_date"] = _parse_date(clean_inv["invoice_date"])
        if "due_date" in clean_inv and clean_inv["due_date"]:
            clean_inv["due_date"] = _parse_date(clean_inv["due_date"])

        def _execute(s: Session) -> Optional[Dict[str, Any]]:
            stmt = (
                update(BillingInvoice)
                .where(
                    BillingInvoice.id == inv_id,
                    BillingInvoice.client_gstin_id == cg_id,
                )
                .values(**clean_inv)
            )
            res = s.execute(stmt)
            if res.rowcount == 0:
                return None

            if line_items_data is not None:
                s.execute(
                    delete(BillingInvoiceLineItem).where(
                        BillingInvoiceLineItem.invoice_id == inv_id
                    )
                )
                for item in line_items_data:
                    clean_item = dict(item)
                    if "id" in clean_item and clean_item["id"]:
                        clean_item["id"] = _parse_uuid(clean_item["id"])
                    clean_item["invoice_id"] = inv_id
                    if "item_id" in clean_item and clean_item["item_id"]:
                        clean_item["item_id"] = _parse_uuid(clean_item["item_id"])
                    s.add(BillingInvoiceLineItem(**clean_item))

            s.flush()
            return self.get_invoice_detail(inv_id, cg_id, session=s)

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def delete_invoice(
        self,
        invoice_id: str | UUID,
        client_gstin_id: str | UUID,
        session: Optional[Session] = None,
    ) -> bool:
        inv_id = _parse_uuid(invoice_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not inv_id or not cg_id:
            return False

        def _execute(s: Session) -> bool:
            stmt = delete(BillingInvoice).where(
                BillingInvoice.id == inv_id,
                BillingInvoice.client_gstin_id == cg_id,
            )
            res = s.execute(stmt)
            return res.rowcount > 0

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    # ── 5. Credit Notes & Debit Notes (CDNR) ──────────────────────────────────

    def get_cdn(
        self,
        cdn_id: str | UUID,
        client_gstin_id: Optional[str | UUID] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        c_id = _parse_uuid(cdn_id)
        if not c_id:
            return None

        def _query(s: Session) -> Optional[Dict[str, Any]]:
            stmt = select(BillingCreditDebitNote).where(BillingCreditDebitNote.id == c_id)
            if client_gstin_id:
                cg_id = _parse_uuid(client_gstin_id)
                if cg_id:
                    stmt = stmt.where(BillingCreditDebitNote.client_gstin_id == cg_id)
            obj = s.execute(stmt).scalar_one_or_none()
            return obj.to_dict() if obj else None

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def get_cdn_detail(
        self,
        cdn_id: str | UUID,
        client_gstin_id: Optional[str | UUID] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        c_id = _parse_uuid(cdn_id)
        if not c_id:
            return None

        def _query(s: Session) -> Optional[Dict[str, Any]]:
            stmt = select(BillingCreditDebitNote).where(BillingCreditDebitNote.id == c_id)
            if client_gstin_id:
                cg_id = _parse_uuid(client_gstin_id)
                if cg_id:
                    stmt = stmt.where(BillingCreditDebitNote.client_gstin_id == cg_id)
            cdn = s.execute(stmt).scalar_one_or_none()
            if not cdn:
                return None

            cdn_dict = cdn.to_dict()

            orig_inv_detail = self.get_invoice_detail(
                cdn.original_invoice_id, client_gstin_id, session=s
            )
            cdn_dict["original_invoice"] = orig_inv_detail
            cdn_dict["company_profile"] = orig_inv_detail.get("company_profile") if orig_inv_detail else None
            cdn_dict["customer"] = orig_inv_detail.get("customer") if orig_inv_detail else None

            lines_stmt = (
                select(BillingCdnLineItem)
                .where(BillingCdnLineItem.cdn_id == c_id)
            )
            lines = s.execute(lines_stmt).scalars().all()
            cdn_dict["line_items"] = [l.to_dict() for l in lines]

            return cdn_dict

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def list_cdns(
        self,
        client_gstin_id: str | UUID,
        original_invoice_id: Optional[str | UUID] = None,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        cg_id = _parse_uuid(client_gstin_id)
        if not cg_id:
            return []

        def _query(s: Session) -> List[Dict[str, Any]]:
            stmt = select(BillingCreditDebitNote).where(
                BillingCreditDebitNote.client_gstin_id == cg_id
            )
            if original_invoice_id:
                inv_id = _parse_uuid(original_invoice_id)
                if inv_id:
                    stmt = stmt.where(BillingCreditDebitNote.original_invoice_id == inv_id)
            stmt = stmt.order_by(sa_desc(BillingCreditDebitNote.created_at))
            objs = s.execute(stmt).scalars().all()
            return [o.to_dict() for o in objs]

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)

    def create_cdn(
        self,
        cdn_data: Dict[str, Any],
        line_items_data: Sequence[Dict[str, Any]],
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Create credit/debit note and line items atomically."""
        clean_cdn = dict(cdn_data)
        if "id" in clean_cdn and clean_cdn["id"]:
            clean_cdn["id"] = _parse_uuid(clean_cdn["id"])
        if "client_gstin_id" in clean_cdn:
            clean_cdn["client_gstin_id"] = _parse_uuid(clean_cdn["client_gstin_id"])
        if "original_invoice_id" in clean_cdn:
            clean_cdn["original_invoice_id"] = _parse_uuid(clean_cdn["original_invoice_id"])
        if "note_date" in clean_cdn:
            clean_cdn["note_date"] = _parse_date(clean_cdn["note_date"])

        cdn_obj = BillingCreditDebitNote(**clean_cdn)

        def _execute(s: Session) -> Dict[str, Any]:
            s.add(cdn_obj)
            s.flush()

            inserted_lines: List[BillingCdnLineItem] = []
            valid_cdn_cols = {c.name for c in BillingCdnLineItem.__table__.columns}
            for item in line_items_data:
                clean_item = dict(item)
                if "id" in clean_item and clean_item["id"]:
                    clean_item["id"] = _parse_uuid(clean_item["id"])
                clean_item["cdn_id"] = cdn_obj.id
                if "item_id" in clean_item and clean_item["item_id"]:
                    clean_item["item_id"] = _parse_uuid(clean_item["item_id"])
                if "tax_rate_percent" not in clean_item:
                    clean_item["tax_rate_percent"] = (
                        (clean_item.get("cgst_rate_percent") or 0.0) + (clean_item.get("sgst_rate_percent") or 0.0)
                    ) or clean_item.get("igst_rate_percent") or 18.0
                filtered_item = {k: v for k, v in clean_item.items() if k in valid_cdn_cols}

                line_obj = BillingCdnLineItem(**filtered_item)
                s.add(line_obj)
                inserted_lines.append(line_obj)

            s.flush()
            result = cdn_obj.to_dict()
            result["line_items"] = [l.to_dict() for l in inserted_lines]
            return result

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def update_cdn(
        self,
        cdn_id: str | UUID,
        client_gstin_id: str | UUID,
        cdn_data: Dict[str, Any],
        line_items_data: Optional[Sequence[Dict[str, Any]]] = None,
        session: Optional[Session] = None,
    ) -> Optional[Dict[str, Any]]:
        c_id = _parse_uuid(cdn_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not c_id or not cg_id:
            return None

        clean_cdn = dict(cdn_data)
        clean_cdn["updated_at"] = datetime.now(timezone.utc)
        if "note_date" in clean_cdn and clean_cdn["note_date"]:
            clean_cdn["note_date"] = _parse_date(clean_cdn["note_date"])

        def _execute(s: Session) -> Optional[Dict[str, Any]]:
            stmt = (
                update(BillingCreditDebitNote)
                .where(
                    BillingCreditDebitNote.id == c_id,
                    BillingCreditDebitNote.client_gstin_id == cg_id,
                )
                .values(**clean_cdn)
            )
            res = s.execute(stmt)
            if res.rowcount == 0:
                return None

            if line_items_data is not None:
                s.execute(
                    delete(BillingCdnLineItem).where(
                        BillingCdnLineItem.cdn_id == c_id
                    )
                )
                valid_cdn_cols = {c.name for c in BillingCdnLineItem.__table__.columns}
                for item in line_items_data:
                    clean_item = dict(item)
                    if "id" in clean_item and clean_item["id"]:
                        clean_item["id"] = _parse_uuid(clean_item["id"])
                    clean_item["cdn_id"] = c_id
                    if "item_id" in clean_item and clean_item["item_id"]:
                        clean_item["item_id"] = _parse_uuid(clean_item["item_id"])
                    if "tax_rate_percent" not in clean_item:
                        clean_item["tax_rate_percent"] = (
                            (clean_item.get("cgst_rate_percent") or 0.0) + (clean_item.get("sgst_rate_percent") or 0.0)
                        ) or clean_item.get("igst_rate_percent") or 18.0
                    filtered_item = {k: v for k, v in clean_item.items() if k in valid_cdn_cols}
                    s.add(BillingCdnLineItem(**filtered_item))

            s.flush()
            return self.get_cdn_detail(c_id, cg_id, session=s)

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    # ── 6. IRP Submission Audit Log ───────────────────────────────────────────

    def log_irp_submission(
        self,
        invoice_id: str | UUID,
        client_gstin_id: str | UUID,
        environment: str,
        request_payload: Any,
        response_status: str,
        response_body: Any,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        inv_id = _parse_uuid(invoice_id)
        cg_id = _parse_uuid(client_gstin_id)
        if not inv_id or not cg_id:
            raise ValueError(f"Invalid UUID for invoice_id ({invoice_id}) or client_gstin_id ({client_gstin_id})")

        obj = BillingIrpSubmissionLog(
            invoice_id=inv_id,
            client_gstin_id=cg_id,
            environment=environment,
            request_payload=request_payload,
            response_status=response_status,
            response_body=response_body,
            attempted_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )

        def _execute(s: Session) -> Dict[str, Any]:
            s.add(obj)
            s.flush()
            return obj.to_dict()

        if session is not None:
            return _execute(session)
        with self._get_session() as s:
            with s.begin():
                return _execute(s)

    def list_irp_logs(
        self,
        invoice_id: str | UUID,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        inv_id = _parse_uuid(invoice_id)
        if not inv_id:
            return []

        def _query(s: Session) -> List[Dict[str, Any]]:
            stmt = (
                select(BillingIrpSubmissionLog)
                .where(BillingIrpSubmissionLog.invoice_id == inv_id)
                .order_by(sa_desc(BillingIrpSubmissionLog.attempted_at))
            )
            objs = s.execute(stmt).scalars().all()
            return [o.to_dict() for o in objs]

        if session is not None:
            return _query(session)
        with self._get_session() as s:
            return _query(s)


# Module-level repository singleton
_billing_ledger_repository: Optional[AuroraBillingLedgerRepository] = None


def get_billing_ledger_repository() -> AuroraBillingLedgerRepository:
    """Return the global AuroraBillingLedgerRepository singleton."""
    global _billing_ledger_repository
    if _billing_ledger_repository is None:
        _billing_ledger_repository = AuroraBillingLedgerRepository()
    return _billing_ledger_repository


def set_billing_ledger_repository(repo: Optional[AuroraBillingLedgerRepository]) -> None:
    """Set or reset the global AuroraBillingLedgerRepository singleton."""
    global _billing_ledger_repository
    _billing_ledger_repository = repo
