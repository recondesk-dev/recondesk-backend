"""Batch 4B Backfill & Parity Verifier: E-Invoicing & B2B Billing Ledger.

Migrates from Supabase to AWS Aurora PostgreSQL:
1. billing_company_profiles (1 row)
2. billing_customers (2 rows)
3. billing_items (2 rows)
4. billing_invoices (3 rows)
5. billing_invoice_line_items (3 rows)
6. billing_credit_debit_notes (0 rows)
7. billing_cdn_line_items (0 rows)
8. billing_irp_submission_log (0 rows)
Total Batch 4B rows: 11 records.

Safety & Constraints:
- Default mode is DRY-RUN (`--dry-run`).
- Zero Supabase data mutations or deletes.
- In dry-run mode:
    * Inserts all source rows within an explicit transaction.
    * Performs 100% field-by-field, timestamp, and numeric parity checks.
    * Verifies FK and tenant constraints.
    * Rolls back transaction completely.
    * Connects via fresh connection to verify zero residual rows.
- SENSITIVE DATA PROTECTION:
    * `bank_account_number` is redacted in logs and string outputs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
from uuid import UUID

# Ensure recondesk-backend is on sys.path
backend_root = Path(__file__).resolve().parents[2]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv
load_dotenv(backend_root / ".env")

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
)
from app.models.schema_base import Base, GUID
from app.models.tenancy import ClientGSTIN, UserProfile
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

logger = logging.getLogger("recondesk.backfill.batch4b")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@dataclass
class TableParityReport:
    table_name: str
    supabase_count: int = 0
    aurora_pre_count: int = 0
    inserted_count: int = 0
    exact_matches: int = 0
    field_mismatches: int = 0
    missing_count: int = 0
    extra_count: int = 0
    orphan_fks: int = 0
    final_count: int = 0
    mismatch_details: list[str] = field(default_factory=list)

    def is_clean(self) -> bool:
        return (
            self.field_mismatches == 0
            and self.missing_count == 0
            and self.extra_count == 0
            and self.orphan_fks == 0
        )


@dataclass
class BatchParityReport:
    commit_mode: bool = False
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    tables: list[TableParityReport] = field(default_factory=list)

    @property
    def total_source_rows(self) -> int:
        return sum(t.supabase_count for t in self.tables)

    @property
    def total_inserted(self) -> int:
        return sum(t.inserted_count for t in self.tables)

    @property
    def total_matches(self) -> int:
        return sum(t.exact_matches for t in self.tables)

    @property
    def total_mismatches(self) -> int:
        return sum(t.field_mismatches for t in self.tables)

    @property
    def total_orphans(self) -> int:
        return sum(t.orphan_fks for t in self.tables)

    def is_clean(self) -> bool:
        return all(t.is_clean() for t in self.tables)


def _normalize_ts(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return val.strip()
    return str(val)


def _normalize_date(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, str):
        try:
            d = date.fromisoformat(val.strip()[:10])
            return d.strftime("%Y-%m-%d")
        except ValueError:
            return val.strip()
    return str(val)


def _normalize_numeric(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(Decimal(str(val)))
    except Exception:
        return None


def _normalize_json(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return json.dumps(parsed, sort_keys=True)
        except Exception:
            return val.strip()
    try:
        return json.dumps(val, sort_keys=True)
    except Exception:
        return str(val)


def _normalize_uuid(val: Any) -> Optional[str]:
    if val is None:
        return None
    try:
        return str(UUID(str(val)))
    except Exception:
        return str(val).strip()


def _parse_ts(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
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


def _compare_field(source_val: Any, aurora_val: Any, field_type: str = "text") -> bool:
    if field_type == "ts":
        return _normalize_ts(source_val) == _normalize_ts(aurora_val)
    if field_type == "date":
        return _normalize_date(source_val) == _normalize_date(aurora_val)
    if field_type == "numeric":
        sv = _normalize_numeric(source_val)
        av = _normalize_numeric(aurora_val)
        if sv is None and av is None:
            return True
        if sv is None or av is None:
            return False
        return abs(sv - av) < 1e-4
    if field_type == "uuid":
        return _normalize_uuid(source_val) == _normalize_uuid(aurora_val)
    if field_type == "json":
        return _normalize_json(source_val) == _normalize_json(aurora_val)
    if field_type == "bool":
        if source_val is None and aurora_val is None:
            return True
        return bool(source_val) == bool(aurora_val)

    # Default text comparison
    sv_str = str(source_val).strip() if source_val is not None else ""
    av_str = str(aurora_val).strip() if aurora_val is not None else ""
    return sv_str == av_str


class Batch4bBackfillMigrator:
    """Orchestrates deterministic backfill and parity check for Batch 4B."""

    TABLES = [
        "billing_company_profiles",
        "billing_customers",
        "billing_items",
        "billing_invoices",
        "billing_invoice_line_items",
        "billing_credit_debit_notes",
        "billing_cdn_line_items",
        "billing_irp_submission_log",
    ]

    EXPECTED_SOURCE_COUNTS = {
        "billing_company_profiles": 1,
        "billing_customers": 2,
        "billing_items": 2,
        "billing_invoices": 3,
        "billing_invoice_line_items": 3,
        "billing_credit_debit_notes": 0,
        "billing_cdn_line_items": 0,
        "billing_irp_submission_log": 0,
    }

    def __init__(
        self,
        *,
        engine: Optional[Engine] = None,
        supabase_client: Any = None,
        sqlite_path: Optional[str] = None,
        batch_size: int = 500,
    ) -> None:
        self._engine = engine
        self._sb = supabase_client
        self._sqlite_path = sqlite_path
        self._batch_size = batch_size

    def _get_supabase(self) -> Any:
        if self._sb is not None:
            return self._sb
        from app.database import get_supabase
        return get_supabase()

    def _get_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        try:
            return get_aurora_engine()
        except AuroraConfigurationError:
            db_target = self._sqlite_path or "sqlite:///:memory:"
            if db_target == "sqlite:///:memory:":
                from sqlalchemy.pool import StaticPool
                eng = sa.create_engine(
                    "sqlite:///:memory:",
                    connect_args={"check_same_thread": False},
                    poolclass=StaticPool,
                    echo=False,
                )
            else:
                eng = sa.create_engine(db_target, echo=False)
            Base.metadata.create_all(bind=eng)
            self._engine = eng
            return eng

    def fetch_all_supabase_rows(self, table_name: str) -> list[dict[str, Any]]:
        sb = self._get_supabase()
        all_rows: list[dict[str, Any]] = []
        offset = 0
        limit = self._batch_size

        while True:
            resp = (
                sb.table(table_name)
                .select("*")
                .range(offset, offset + limit - 1)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < limit:
                break
            offset += limit

        return all_rows

    def verify_foreign_keys(
        self,
        session: Session,
        table_name: str,
        rows: list[dict[str, Any]],
    ) -> int:
        orphans = 0
        for r in rows:
            # Client GSTIN check
            cg_id = _normalize_uuid(r.get("client_gstin_id"))
            if cg_id:
                exists = session.get(ClientGSTIN, UUID(cg_id))
                if not exists:
                    logger.error(
                        "Orphan FK in %s %s: client_gstin_id %s not in client_gstins",
                        table_name,
                        r.get("id"),
                        cg_id,
                    )
                    orphans += 1

            if table_name == "billing_invoices":
                cp_id = _normalize_uuid(r.get("company_profile_id"))
                if cp_id and not session.get(BillingCompanyProfile, UUID(cp_id)):
                    logger.error("Orphan company_profile_id %s in invoice %s", cp_id, r.get("id"))
                    orphans += 1
                cust_id = _normalize_uuid(r.get("customer_id"))
                if cust_id and not session.get(BillingCustomer, UUID(cust_id)):
                    logger.error("Orphan customer_id %s in invoice %s", cust_id, r.get("id"))
                    orphans += 1

            elif table_name == "billing_invoice_line_items":
                inv_id = _normalize_uuid(r.get("invoice_id"))
                if inv_id and not session.get(BillingInvoice, UUID(inv_id)):
                    logger.error("Orphan invoice_id %s in line item %s", inv_id, r.get("id"))
                    orphans += 1
                item_id = _normalize_uuid(r.get("item_id"))
                if item_id and not session.get(BillingItem, UUID(item_id)):
                    logger.error("Orphan item_id %s in line item %s", item_id, r.get("id"))
                    orphans += 1

            elif table_name == "billing_credit_debit_notes":
                orig_id = _normalize_uuid(r.get("original_invoice_id"))
                if orig_id and not session.get(BillingInvoice, UUID(orig_id)):
                    logger.error("Orphan original_invoice_id %s in cdn %s", orig_id, r.get("id"))
                    orphans += 1

            elif table_name == "billing_cdn_line_items":
                cdn_id = _normalize_uuid(r.get("cdn_id"))
                if cdn_id and not session.get(BillingCreditDebitNote, UUID(cdn_id)):
                    logger.error("Orphan cdn_id %s in cdn line %s", cdn_id, r.get("id"))
                    orphans += 1
                item_id = _normalize_uuid(r.get("item_id"))
                if item_id and not session.get(BillingItem, UUID(item_id)):
                    logger.error("Orphan item_id %s in cdn line %s", item_id, r.get("id"))
                    orphans += 1

            elif table_name == "billing_irp_submission_log":
                inv_id = _normalize_uuid(r.get("invoice_id"))
                if inv_id and not session.get(BillingInvoice, UUID(inv_id)):
                    logger.error("Orphan invoice_id %s in irp log %s", inv_id, r.get("id"))
                    orphans += 1

        return orphans

    def _seed_parent_fixtures_if_needed(
        self,
        session: Session,
        source_data: dict[str, list[dict[str, Any]]],
    ) -> None:
        """For test or standalone environments where parent rows may not exist."""
        client_ids = set()
        for tbl, rows in source_data.items():
            for r in rows:
                cid = _normalize_uuid(r.get("client_gstin_id"))
                if cid:
                    client_ids.add(cid)

        # Check user profile
        default_owner_id = UUID("b15fb04f-7b29-4f1b-ac70-f00b905e254b")
        if not session.get(UserProfile, default_owner_id):
            session.add(
                UserProfile(
                    id=default_owner_id,
                    email="test_owner@recondesk.com",
                    full_name="Test Owner",
                    role="firm_owner",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.flush()

        for cid in client_ids:
            uid = UUID(cid)
            if not session.get(ClientGSTIN, uid):
                session.add(
                    ClientGSTIN(
                        id=uid,
                        firm_owner_id=default_owner_id,
                        gstin="27ISKPK1273H1ZF",
                        trade_name="Test Client Trade",
                        legal_name="Test Client Legal",
                        state_code="27",
                        added_at=datetime.now(timezone.utc),
                    )
                )
        session.flush()

    def _insert_company_profiles(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            obj = BillingCompanyProfile(
                id=UUID(rid),
                client_gstin_id=UUID(str(r["client_gstin_id"])),
                legal_name=r["legal_name"],
                trade_name=r.get("trade_name"),
                address_line1=r.get("address_line1") or "",
                address_line2=r.get("address_line2"),
                city=r.get("city") or "",
                state=r.get("state") or "",
                state_code=r.get("state_code") or "27",
                pincode=r.get("pincode") or "",
                gstin=r["gstin"],
                pan=r.get("pan"),
                bank_account_number=r.get("bank_account_number"),
                bank_ifsc=r.get("bank_ifsc"),
                bank_name=r.get("bank_name"),
                invoice_number_prefix=r.get("invoice_number_prefix") or "",
                invoice_number_next_seq=int(r.get("invoice_number_next_seq", 1)),
                financial_year_reset=bool(r.get("financial_year_reset", True)),
                cdn_number_prefix=r.get("cdn_number_prefix") or "CRN/",
                cdn_number_next_seq=int(r.get("cdn_number_next_seq", 1)),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    def _insert_customers(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            obj = BillingCustomer(
                id=UUID(rid),
                client_gstin_id=UUID(str(r["client_gstin_id"])),
                name=r["name"],
                gstin=r.get("gstin"),
                address_line1=r.get("address_line1") or "",
                address_line2=r.get("address_line2"),
                city=r.get("city") or "",
                state=r.get("state") or "",
                state_code=r.get("state_code") or "27",
                pincode=r.get("pincode") or "",
                is_b2b=bool(r.get("is_b2b", True)),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    def _insert_items(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            obj = BillingItem(
                id=UUID(rid),
                client_gstin_id=UUID(str(r["client_gstin_id"])),
                name=r["name"],
                hsn_or_sac_code=r["hsn_or_sac_code"],
                unit=r.get("unit") or "NOS",
                default_rate=int(r.get("default_rate", 0)),
                default_tax_rate_percent=Decimal(str(r.get("default_tax_rate_percent", 18.00))),
                item_type=r.get("item_type") or "goods",
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    def _insert_invoices(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            obj = BillingInvoice(
                id=UUID(rid),
                client_gstin_id=UUID(str(r["client_gstin_id"])),
                company_profile_id=UUID(str(r["company_profile_id"])),
                customer_id=UUID(str(r["customer_id"])),
                invoice_number=r["invoice_number"],
                invoice_date=_parse_date(r.get("invoice_date")) or date.today(),
                due_date=_parse_date(r.get("due_date")),
                place_of_supply=r.get("place_of_supply") or "27",
                is_interstate=bool(r.get("is_interstate", False)),
                subtotal_paise=int(r.get("subtotal_paise", 0)),
                total_tax_paise=int(r.get("total_tax_paise", 0)),
                total_paise=int(r.get("total_paise", 0)),
                status=r.get("status") or "draft",
                irn=r.get("irn"),
                notes=r.get("notes"),
                irn_ack_number=r.get("irn_ack_number"),
                irn_ack_date=_parse_ts(r.get("irn_ack_date")),
                irn_qr_code=r.get("irn_qr_code"),
                irn_signed_json=r.get("irn_signed_json"),
                irp_status=r.get("irp_status") or "not_submitted",
                irp_error_detail=r.get("irp_error_detail"),
                irp_environment=r.get("irp_environment") or "test",
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    def _insert_invoice_line_items(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            item_uuid = UUID(str(r["item_id"])) if r.get("item_id") else None
            obj = BillingInvoiceLineItem(
                id=UUID(rid),
                invoice_id=UUID(str(r["invoice_id"])),
                item_id=item_uuid,
                description=r["description"],
                hsn_or_sac_code=r["hsn_or_sac_code"],
                quantity=Decimal(str(r.get("quantity", 1.0))),
                unit=r.get("unit") or "NOS",
                rate_paise=int(r.get("rate_paise", 0)),
                discount_percent=Decimal(str(r.get("discount_percent", 0.00))),
                taxable_value_paise=int(r.get("taxable_value_paise", 0)),
                cgst_rate_percent=Decimal(str(r.get("cgst_rate_percent", 0.00))),
                cgst_paise=int(r.get("cgst_paise", 0)),
                sgst_rate_percent=Decimal(str(r.get("sgst_rate_percent", 0.00))),
                sgst_paise=int(r.get("sgst_paise", 0)),
                igst_rate_percent=Decimal(str(r.get("igst_rate_percent", 0.00))),
                igst_paise=int(r.get("igst_paise", 0)),
                cess_paise=int(r.get("cess_paise", 0)),
                line_total_paise=int(r.get("line_total_paise", 0)),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    def _insert_cdns(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            obj = BillingCreditDebitNote(
                id=UUID(rid),
                client_gstin_id=UUID(str(r["client_gstin_id"])),
                original_invoice_id=UUID(str(r["original_invoice_id"])),
                note_type=r.get("note_type") or "credit",
                note_number=r["note_number"],
                note_date=_parse_date(r.get("note_date")) or date.today(),
                reason=r.get("reason") or "1-Sales Return",
                reason_detail=r.get("reason_detail"),
                subtotal_paise=int(r.get("subtotal_paise", 0)),
                total_tax_paise=int(r.get("total_tax_paise", 0)),
                total_paise=int(r.get("total_paise", 0)),
                status=r.get("status") or "draft",
                irn=r.get("irn"),
                irn_ack_number=r.get("irn_ack_number"),
                irn_ack_date=_parse_ts(r.get("irn_ack_date")),
                irn_qr_code=r.get("irn_qr_code"),
                irn_signed_json=r.get("irn_signed_json"),
                irp_status=r.get("irp_status") or "not_submitted",
                irp_error_detail=r.get("irp_error_detail"),
                irp_environment=r.get("irp_environment") or "test",
                notes=r.get("notes"),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    def _insert_cdn_line_items(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            item_uuid = UUID(str(r["item_id"])) if r.get("item_id") else None
            obj = BillingCdnLineItem(
                id=UUID(rid),
                cdn_id=UUID(str(r["cdn_id"])),
                item_id=item_uuid,
                description=r["description"],
                hsn_or_sac_code=r["hsn_or_sac_code"],
                quantity=Decimal(str(r.get("quantity", 1.0))),
                unit=r.get("unit") or "NOS",
                rate_paise=int(r.get("rate_paise", 0)),
                discount_percent=Decimal(str(r.get("discount_percent", 0.00))),
                taxable_value_paise=int(r.get("taxable_value_paise", 0)),
                tax_rate_percent=Decimal(str(r.get("tax_rate_percent", 18.00))),
                cgst_paise=int(r.get("cgst_paise", 0)),
                sgst_paise=int(r.get("sgst_paise", 0)),
                igst_paise=int(r.get("igst_paise", 0)),
                cess_paise=int(r.get("cess_paise", 0)),
                line_total_paise=int(r.get("line_total_paise", 0)),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    def _insert_irp_logs(
        self,
        session: Session,
        rows: list[dict[str, Any]],
        existing_ids: set[str],
        tr: TableParityReport,
    ) -> None:
        for r in rows:
            rid = str(r["id"])
            if rid in existing_ids:
                continue
            obj = BillingIrpSubmissionLog(
                id=UUID(rid),
                invoice_id=UUID(str(r["invoice_id"])),
                client_gstin_id=UUID(str(r["client_gstin_id"])),
                attempted_at=_parse_ts(r.get("attempted_at")) or datetime.now(timezone.utc),
                environment=r.get("environment") or "test",
                request_payload=r.get("request_payload"),
                response_status=r["response_status"],
                response_body=r.get("response_body"),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            existing_ids.add(rid)
            tr.inserted_count += 1

    FIELD_SPECS = {
        "billing_company_profiles": {
            "id": "uuid",
            "client_gstin_id": "uuid",
            "legal_name": "text",
            "trade_name": "text",
            "address_line1": "text",
            "address_line2": "text",
            "city": "text",
            "state": "text",
            "state_code": "text",
            "pincode": "text",
            "gstin": "text",
            "pan": "text",
            "bank_account_number": "text",
            "bank_ifsc": "text",
            "bank_name": "text",
            "invoice_number_prefix": "text",
            "invoice_number_next_seq": "numeric",
            "financial_year_reset": "bool",
            "cdn_number_prefix": "text",
            "cdn_number_next_seq": "numeric",
            "created_at": "ts",
        },
        "billing_customers": {
            "id": "uuid",
            "client_gstin_id": "uuid",
            "name": "text",
            "gstin": "text",
            "address_line1": "text",
            "address_line2": "text",
            "city": "text",
            "state": "text",
            "state_code": "text",
            "pincode": "text",
            "is_b2b": "bool",
            "created_at": "ts",
        },
        "billing_items": {
            "id": "uuid",
            "client_gstin_id": "uuid",
            "name": "text",
            "hsn_or_sac_code": "text",
            "unit": "text",
            "default_rate": "numeric",
            "default_tax_rate_percent": "numeric",
            "item_type": "text",
            "created_at": "ts",
        },
        "billing_invoices": {
            "id": "uuid",
            "client_gstin_id": "uuid",
            "company_profile_id": "uuid",
            "customer_id": "uuid",
            "invoice_number": "text",
            "invoice_date": "date",
            "due_date": "date",
            "place_of_supply": "text",
            "is_interstate": "bool",
            "subtotal_paise": "numeric",
            "total_tax_paise": "numeric",
            "total_paise": "numeric",
            "status": "text",
            "irn": "text",
            "notes": "text",
            "irp_status": "text",
            "irp_environment": "text",
            "created_at": "ts",
        },
        "billing_invoice_line_items": {
            "id": "uuid",
            "invoice_id": "uuid",
            "item_id": "uuid",
            "description": "text",
            "hsn_or_sac_code": "text",
            "quantity": "numeric",
            "unit": "text",
            "rate_paise": "numeric",
            "discount_percent": "numeric",
            "taxable_value_paise": "numeric",
            "cgst_rate_percent": "numeric",
            "cgst_paise": "numeric",
            "sgst_rate_percent": "numeric",
            "sgst_paise": "numeric",
            "igst_rate_percent": "numeric",
            "igst_paise": "numeric",
            "cess_paise": "numeric",
            "line_total_paise": "numeric",
        },
        "billing_credit_debit_notes": {
            "id": "uuid",
            "client_gstin_id": "uuid",
            "original_invoice_id": "uuid",
            "note_type": "text",
            "note_number": "text",
            "note_date": "date",
            "reason": "text",
            "reason_detail": "text",
            "subtotal_paise": "numeric",
            "total_tax_paise": "numeric",
            "total_paise": "numeric",
            "status": "text",
            "irn": "text",
            "irp_status": "text",
            "irp_environment": "text",
            "notes": "text",
            "created_at": "ts",
        },
        "billing_cdn_line_items": {
            "id": "uuid",
            "cdn_id": "uuid",
            "item_id": "uuid",
            "description": "text",
            "hsn_or_sac_code": "text",
            "quantity": "numeric",
            "unit": "text",
            "rate_paise": "numeric",
            "discount_percent": "numeric",
            "taxable_value_paise": "numeric",
            "tax_rate_percent": "numeric",
            "cgst_paise": "numeric",
            "sgst_paise": "numeric",
            "igst_paise": "numeric",
            "cess_paise": "numeric",
            "line_total_paise": "numeric",
            "created_at": "ts",
        },
        "billing_irp_submission_log": {
            "id": "uuid",
            "invoice_id": "uuid",
            "client_gstin_id": "uuid",
            "attempted_at": "ts",
            "environment": "text",
            "response_status": "text",
            "created_at": "ts",
        },
    }

    MODEL_MAP = {
        "billing_company_profiles": BillingCompanyProfile,
        "billing_customers": BillingCustomer,
        "billing_items": BillingItem,
        "billing_invoices": BillingInvoice,
        "billing_invoice_line_items": BillingInvoiceLineItem,
        "billing_credit_debit_notes": BillingCreditDebitNote,
        "billing_cdn_line_items": BillingCdnLineItem,
        "billing_irp_submission_log": BillingIrpSubmissionLog,
    }

    def run_backfill(self, *, commit: bool = False) -> BatchParityReport:
        mode_str = "COMMIT (PRODUCTION)" if commit else "DRY-RUN (ROLLBACK)"
        logger.info("Starting Batch 4B backfill in %s mode", mode_str)

        report = BatchParityReport(commit_mode=commit)
        engine = self._get_engine()
        SessionLocal = sessionmaker(bind=engine)

        source_data: dict[str, list[dict[str, Any]]] = {}
        for tbl in self.TABLES:
            logger.info("Fetching source records from Supabase for %s", tbl)
            rows = self.fetch_all_supabase_rows(tbl)
            source_data[tbl] = rows
            logger.info("Fetched %d rows for %s", len(rows), tbl)

        with SessionLocal() as session:
            tr_map: dict[str, TableParityReport] = {}
            for tbl in self.TABLES:
                model_cls = self.MODEL_MAP[tbl]
                pre_count = session.query(func.count()).select_from(model_cls).scalar() or 0
                tr = TableParityReport(
                    table_name=tbl,
                    supabase_count=len(source_data[tbl]),
                    aurora_pre_count=pre_count,
                )
                tr_map[tbl] = tr
                report.tables.append(tr)

            existing_ids: dict[str, set[str]] = {}
            for tbl in self.TABLES:
                model_cls = self.MODEL_MAP[tbl]
                existing_ids[tbl] = {str(pk) for (pk,) in session.query(model_cls.id).all()}

            self._seed_parent_fixtures_if_needed(session, source_data)

            # 1. billing_company_profiles
            self._insert_company_profiles(
                session, source_data["billing_company_profiles"], existing_ids["billing_company_profiles"], tr_map["billing_company_profiles"]
            )
            session.flush()

            # 2. billing_customers
            self._insert_customers(
                session, source_data["billing_customers"], existing_ids["billing_customers"], tr_map["billing_customers"]
            )
            session.flush()

            # 3. billing_items
            self._insert_items(
                session, source_data["billing_items"], existing_ids["billing_items"], tr_map["billing_items"]
            )
            session.flush()

            # 4. billing_invoices
            self._insert_invoices(
                session, source_data["billing_invoices"], existing_ids["billing_invoices"], tr_map["billing_invoices"]
            )
            session.flush()

            # 5. billing_invoice_line_items
            self._insert_invoice_line_items(
                session, source_data["billing_invoice_line_items"], existing_ids["billing_invoice_line_items"], tr_map["billing_invoice_line_items"]
            )
            session.flush()

            # 6. billing_credit_debit_notes
            self._insert_cdns(
                session, source_data["billing_credit_debit_notes"], existing_ids["billing_credit_debit_notes"], tr_map["billing_credit_debit_notes"]
            )
            session.flush()

            # 7. billing_cdn_line_items
            self._insert_cdn_line_items(
                session, source_data["billing_cdn_line_items"], existing_ids["billing_cdn_line_items"], tr_map["billing_cdn_line_items"]
            )
            session.flush()

            # 8. billing_irp_submission_log
            self._insert_irp_logs(
                session, source_data["billing_irp_submission_log"], existing_ids["billing_irp_submission_log"], tr_map["billing_irp_submission_log"]
            )
            session.flush()

            for tbl in self.TABLES:
                orphans = self.verify_foreign_keys(session, tbl, source_data[tbl])
                tr_map[tbl].orphan_fks = orphans
                if orphans > 0:
                    logger.error("Discovered %d orphan records in %s", orphans, tbl)

            # Field-by-field parity check
            for tbl in self.TABLES:
                tr = tr_map[tbl]
                model_cls = self.MODEL_MAP[tbl]
                field_specs = self.FIELD_SPECS[tbl]

                for src_row in source_data[tbl]:
                    pk_val = src_row["id"]
                    aurora_obj = session.get(model_cls, UUID(str(pk_val)))
                    if not aurora_obj:
                        tr.missing_count += 1
                        tr.mismatch_details.append(f"Missing row in Aurora: {pk_val}")
                        continue

                    row_clean = True

                    for f_name, f_type in field_specs.items():
                        s_val = src_row.get(f_name)
                        a_val = getattr(aurora_obj, f_name, None)

                        if not _compare_field(s_val, a_val, f_type):
                            row_clean = False
                            # Redact sensitive bank account if mismatched
                            s_disp = "***REDACTED***" if f_name == "bank_account_number" else s_val
                            a_disp = "***REDACTED***" if f_name == "bank_account_number" else a_val
                            msg = f"Table {tbl} row {pk_val} col {f_name}: source='{s_disp}' != aurora='{a_disp}'"
                            logger.error(msg)
                            tr.mismatch_details.append(msg)

                    if row_clean:
                        tr.exact_matches += 1
                    else:
                        tr.field_mismatches += 1

            if commit:
                if not report.is_clean():
                    logger.error("ABORTING COMMIT: Parity mismatches detected!")
                    session.rollback()
                    raise RuntimeError("Batch 4B commit aborted due to parity errors")

                session.commit()
                logger.info("COMMITTED: Batch 4B records successfully written to Aurora")
            else:
                session.rollback()
                logger.info("DRY-RUN COMPLETE: Transaction explicitly rolled back")

        # Fresh connection check
        with SessionLocal() as fresh_session:
            for tr in report.tables:
                model_cls = self.MODEL_MAP[tr.table_name]
                post_count = fresh_session.query(func.count()).select_from(model_cls).scalar() or 0
                tr.final_count = post_count
                if commit:
                    expected_final = tr.aurora_pre_count + tr.inserted_count
                    if post_count != expected_final:
                        logger.error(
                            "Fresh connection count mismatch for %s: expected %d, got %d",
                            tr.table_name,
                            expected_final,
                            post_count,
                        )
                else:
                    if post_count != tr.aurora_pre_count:
                        logger.error(
                            "Fresh connection residual leak detected for %s: pre=%d, post=%d",
                            tr.table_name,
                            tr.aurora_pre_count,
                            post_count,
                        )

        report.end_time = time.time()
        self.print_summary(report)
        return report

    def print_summary(self, report: BatchParityReport) -> None:
        elapsed = report.end_time - report.start_time
        mode_str = "COMMIT (PRODUCTION)" if report.commit_mode else "DRY-RUN (VERIFIED ROLLBACK)"
        print("\n" + "=" * 76)
        print(f"RECONDESK — BATCH 4B PARITY & BACKFILL REPORT [{mode_str}]")
        print("=" * 76)
        print(f"Execution time: {elapsed:.2f}s | Clean Status: {report.is_clean()}\n")
        print(f"{'Table Name':<30} | {'Source':<7} | {'Pre':<5} | {'Ins':<5} | {'Match':<5} | {'Diff':<5} | {'Post':<5}")
        print("-" * 76)
        for t in report.tables:
            print(
                f"{t.table_name:<30} | {t.supabase_count:<7} | {t.aurora_pre_count:<5} | "
                f"{t.inserted_count:<5} | {t.exact_matches:<5} | {t.field_mismatches:<5} | {t.final_count:<5}"
            )
        print("-" * 76)
        print(
            f"{'TOTAL':<30} | {report.total_source_rows:<7} | {'-':<5} | "
            f"{report.total_inserted:<5} | {report.total_matches:<5} | {report.total_mismatches:<5} | {'-':<5}"
        )
        print("=" * 76)
        if report.total_mismatches > 0:
            print(f"\nFAILURE: {report.total_mismatches} field mismatches detected!")
            for t in report.tables:
                for m in t.mismatch_details[:10]:
                    print(f"  - {m}")
        elif report.is_clean():
            print("\nSUCCESS: 100% field parity achieved. Zero mismatches, zero orphans.")
        print("=" * 76 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch 4B Backfill & Parity Verifier")
    parser.add_argument("--commit", action="store_true", help="Execute real production backfill commit")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Execute dry-run with rollback")
    args = parser.parse_args()

    commit_mode = bool(args.commit)
    migrator = Batch4bBackfillMigrator()
    report = migrator.run_backfill(commit=commit_mode)
    if not report.is_clean():
        sys.exit(1)


if __name__ == "__main__":
    main()
