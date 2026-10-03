"""AWS Aurora Integrations & Connectors Repository for ReconDesk — Batch 3B.

Provides typed, safe SQLAlchemy 2.x data access for:
1. tally_bridge_keys (Firm-scoped Tally API keys and sync metadata)
2. tally_ledger_masters (Tally ledger name -> GSTIN and master records)
3. client_einvoice_credentials (Client GSTIN e-invoice portal credentials & session tokens)
4. einvoice_recon_results (e-Invoice vs GSTR-2B / PR reconciliation outcomes)
5. gst_fetch_log (GST portal fetch audit history and statuses)
6. ims_action_submissions (IMS CA invoice acceptance/rejection writebacks)
7. fn_claim_ims_action_submission (PostgreSQL RPC function for atomic IMS claim)

Architecture & Invariants:
- Aurora is PRIMARY for all 6 tables and the RPC.
- Aurora is ALWAYS attempted first.
- Controlled, non-blocking fallback to Supabase only on operational failure.
- Strict tenant boundary isolation:
    * Firm/account-scoped for Tally keys and ledgers (`account_id` == UserProfile.id)
    * Client-scoped for e-Invoice credentials and logs (`client_gstin_id` / `client_id` == ClientGSTIN.id)
    * Run-scoped for IMS actions (`run_id` == ReconciliationRun.id)
- Zero credential exposure in logs and string representations.
- Full dialect compatibility: PostgreSQL in production, SQLite in test suites.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, desc as sa_desc, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
    get_aurora_session,
)
from app.models.integrations import (
    ClientEinvoiceCredential,
    EinvoiceReconResult,
    GstFetchLog,
    ImsActionSubmission,
    TallyBridgeKey,
    TallyLedgerMaster,
)

_log = logging.getLogger("recondesk.aurora.integrations")

_fallback_sessionmaker: Optional[sessionmaker[Session]] = None


def _get_fallback_sessionmaker() -> sessionmaker[Session]:
    global _fallback_sessionmaker
    if _fallback_sessionmaker is None:
        from app.scripts.backfill_batch3b_integrations import (
            Batch3BIntegrationsOrchestrator,
        )
        orch = Batch3BIntegrationsOrchestrator()
        engine = orch._get_engine()
        _fallback_sessionmaker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _fallback_sessionmaker


def _is_sqlite(session: Session) -> bool:
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


def _parse_numeric(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _model_to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class AuroraIntegrationsRepository:
    """Typed data-access repository for Batch 3B tables against AWS Aurora PostgreSQL."""

    def __init__(self, session_factory: Optional[sessionmaker[Session]] = None) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        if self._session_factory:
            return self._session_factory()
        try:
            return get_aurora_session()
        except AuroraConfigurationError:
            return _get_fallback_sessionmaker()()

    # ── 1. Tally Bridge Keys ───────────────────────────────────────────────────

    def get_tally_bridge_key_by_api_key(self, api_key: str) -> Optional[dict[str, Any]]:
        """Look up an active Tally bridge key by its plaintext API key."""
        if not api_key:
            return None
        session = self._get_session()
        try:
            stmt = select(TallyBridgeKey).where(
                TallyBridgeKey.api_key == api_key,
                TallyBridgeKey.revoked_at.is_(None),
            )
            result = session.scalars(stmt).first()
            return _model_to_dict(result) if result else None
        finally:
            session.close()

    def get_tally_bridge_key_by_id(
        self, key_id: str | UUID, account_id: Optional[str | UUID] = None
    ) -> Optional[dict[str, Any]]:
        """Look up a Tally bridge key by ID and optional account boundary."""
        kid = _parse_uuid(key_id)
        if not kid:
            return None
        session = self._get_session()
        try:
            stmt = select(TallyBridgeKey).where(TallyBridgeKey.id == kid)
            if account_id:
                aid = _parse_uuid(account_id)
                stmt = stmt.where(TallyBridgeKey.account_id == aid)
            result = session.scalars(stmt).first()
            return _model_to_dict(result) if result else None
        finally:
            session.close()

    def list_tally_bridge_keys_for_account(
        self, account_id: str | UUID, limit: int = 5
    ) -> list[dict[str, Any]]:
        """List recent Tally bridge keys for a firm account."""
        aid = _parse_uuid(account_id)
        if not aid:
            return []
        session = self._get_session()
        try:
            stmt = (
                select(TallyBridgeKey)
                .where(TallyBridgeKey.account_id == aid)
                .order_by(sa_desc(TallyBridgeKey.created_at))
                .limit(limit)
            )
            results = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in results]
        finally:
            session.close()

    def create_tally_bridge_key(
        self,
        *,
        account_id: str | UUID,
        api_key: str,
        company_name: str = "",
        key_id: Optional[str | UUID] = None,
    ) -> dict[str, Any]:
        """Create and persist a new Tally bridge key for a firm account."""
        aid = _parse_uuid(account_id)
        kid = _parse_uuid(key_id)
        if not aid or not api_key:
            raise ValueError("account_id and api_key are required to create Tally bridge key")

        session = self._get_session()
        try:
            obj = TallyBridgeKey(
                id=kid or (None if _is_sqlite(session) else sa.text("gen_random_uuid()")),
                api_key=api_key,
                account_id=aid,
                company_name=company_name or "",
                created_at=datetime.now(timezone.utc),
            )
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return _model_to_dict(obj)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def rotate_tally_bridge_keys_for_account(
        self, account_id: str | UUID, revoked_at: Optional[datetime] = None
    ) -> int:
        """Revoke all existing active Tally bridge keys for an account before generating a new one."""
        aid = _parse_uuid(account_id)
        if not aid:
            return 0
        ts = revoked_at or datetime.now(timezone.utc)
        session = self._get_session()
        try:
            stmt = (
                update(TallyBridgeKey)
                .where(
                    TallyBridgeKey.account_id == aid,
                    TallyBridgeKey.revoked_at.is_(None),
                )
                .values(revoked_at=ts)
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def revoke_tally_bridge_key(
        self, *, key_id: str | UUID, account_id: str | UUID, revoked_at: Optional[datetime] = None
    ) -> bool:
        """Revoke a specific Tally bridge key scoped to an account."""
        kid = _parse_uuid(key_id)
        aid = _parse_uuid(account_id)
        if not kid or not aid:
            return False
        ts = revoked_at or datetime.now(timezone.utc)
        session = self._get_session()
        try:
            stmt = (
                update(TallyBridgeKey)
                .where(
                    TallyBridgeKey.id == kid,
                    TallyBridgeKey.account_id == aid,
                    TallyBridgeKey.revoked_at.is_(None),
                )
                .values(revoked_at=ts)
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_tally_bridge_key_last_synced(
        self,
        *,
        key_id: Optional[str | UUID] = None,
        account_id: Optional[str | UUID] = None,
        last_synced_at: Optional[datetime] = None,
    ) -> int:
        """Update last_synced_at on active Tally bridge key(s)."""
        kid = _parse_uuid(key_id)
        aid = _parse_uuid(account_id)
        if not kid and not aid:
            return 0
        ts = last_synced_at or datetime.now(timezone.utc)
        session = self._get_session()
        try:
            stmt = update(TallyBridgeKey).where(TallyBridgeKey.revoked_at.is_(None))
            if kid:
                stmt = stmt.where(TallyBridgeKey.id == kid)
            if aid:
                stmt = stmt.where(TallyBridgeKey.account_id == aid)
            stmt = stmt.values(last_synced_at=ts)
            res = session.execute(stmt)
            session.commit()
            return res.rowcount
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 2. Tally Ledger Masters ────────────────────────────────────────────────

    def load_tally_ledger_gstin_map(self, account_id: str | UUID) -> dict[str, str]:
        """Load ledger name -> GSTIN mapping for an account."""
        aid = _parse_uuid(account_id)
        if not aid:
            return {}
        session = self._get_session()
        try:
            stmt = select(TallyLedgerMaster.name, TallyLedgerMaster.gstin).where(
                TallyLedgerMaster.account_id == aid,
                TallyLedgerMaster.gstin != "",
                TallyLedgerMaster.gstin.isnot(None),
            )
            results = session.execute(stmt).all()
            return {str(name): str(gstin).strip().upper() for name, gstin in results if name and gstin}
        finally:
            session.close()

    def upsert_tally_ledgers(
        self,
        account_id: str | UUID,
        company_name: str,
        ledgers: Sequence[dict[str, Any]],
    ) -> int:
        """Upsert a batch of Tally ledgers for an account and company."""
        aid = _parse_uuid(account_id)
        if not aid or not ledgers:
            return 0
        session = self._get_session()
        try:
            now = datetime.now(timezone.utc)
            count = 0
            for item in ledgers:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                gstin = str(item.get("gstin") or "").strip().upper()
                parent_group = str(item.get("parent_group") or "")
                state = str(item.get("state") or "")
                op_bal = _parse_numeric(item.get("opening_balance"))
                cl_bal = _parse_numeric(item.get("closing_balance"))

                existing = session.scalars(
                    select(TallyLedgerMaster).where(
                        TallyLedgerMaster.account_id == aid,
                        TallyLedgerMaster.company_name == (company_name or ""),
                        TallyLedgerMaster.name == name,
                    )
                ).first()

                if existing:
                    existing.gstin = gstin
                    existing.parent_group = parent_group
                    existing.state = state
                    existing.opening_balance = op_bal
                    existing.closing_balance = cl_bal
                    existing.synced_at = now
                else:
                    obj = TallyLedgerMaster(
                        id=None if _is_sqlite(session) else sa.text("gen_random_uuid()"),
                        account_id=aid,
                        company_name=company_name or "",
                        name=name,
                        parent_group=parent_group,
                        gstin=gstin,
                        state=state,
                        opening_balance=op_bal,
                        closing_balance=cl_bal,
                        synced_at=now,
                    )
                    session.add(obj)
                count += 1

            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 3. Client e-Invoice Credentials ────────────────────────────────────────

    def get_client_einvoice_credential(
        self, client_gstin_id: str | UUID
    ) -> Optional[dict[str, Any]]:
        """Retrieve e-invoice credentials for a client GSTIN."""
        cid = _parse_uuid(client_gstin_id)
        if not cid:
            return None
        session = self._get_session()
        try:
            stmt = select(ClientEinvoiceCredential).where(
                ClientEinvoiceCredential.client_gstin_id == cid
            )
            result = session.scalars(stmt).first()
            return _model_to_dict(result) if result else None
        finally:
            session.close()

    def upsert_client_einvoice_credential(
        self,
        *,
        client_gstin_id: str | UUID,
        einvoice_username: str,
        einvoice_password: str,
        session_token: Optional[str] = None,
        session_token_expiry: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Insert or update e-invoice portal credentials for a client GSTIN."""
        cid = _parse_uuid(client_gstin_id)
        if not cid:
            raise ValueError("client_gstin_id is required")

        session = self._get_session()
        try:
            existing = session.scalars(
                select(ClientEinvoiceCredential).where(
                    ClientEinvoiceCredential.client_gstin_id == cid
                )
            ).first()

            now = datetime.now(timezone.utc)
            if existing:
                existing.einvoice_username = einvoice_username
                existing.einvoice_password = einvoice_password
                if session_token is not None:
                    existing.session_token = session_token
                if session_token_expiry is not None:
                    existing.session_token_expiry = session_token_expiry
                existing.updated_at = now
                session.commit()
                session.refresh(existing)
                return _model_to_dict(existing)
            else:
                obj = ClientEinvoiceCredential(
                    id=None if _is_sqlite(session) else sa.text("gen_random_uuid()"),
                    client_gstin_id=cid,
                    einvoice_username=einvoice_username,
                    einvoice_password=einvoice_password,
                    session_token=session_token,
                    session_token_expiry=session_token_expiry,
                    created_at=now,
                    updated_at=now,
                )
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return _model_to_dict(obj)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_client_einvoice_token(
        self,
        *,
        client_gstin_id: str | UUID,
        session_token: str,
        session_token_expiry: datetime,
    ) -> bool:
        """Update active session token and expiry for a client GSTIN."""
        cid = _parse_uuid(client_gstin_id)
        if not cid:
            return False
        session = self._get_session()
        try:
            stmt = (
                update(ClientEinvoiceCredential)
                .where(ClientEinvoiceCredential.client_gstin_id == cid)
                .values(
                    session_token=session_token,
                    session_token_expiry=session_token_expiry,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 4. e-Invoice Reconciliation Results ────────────────────────────────────

    def get_einvoice_recon_result_by_id(
        self, result_id: str | UUID
    ) -> Optional[dict[str, Any]]:
        """Fetch a single e-invoice recon result by its UUID."""
        rid = _parse_uuid(result_id)
        if not rid:
            return None
        session = self._get_session()
        try:
            stmt = select(EinvoiceReconResult).where(EinvoiceReconResult.id == rid)
            result = session.scalars(stmt).first()
            return _model_to_dict(result) if result else None
        finally:
            session.close()

    def update_einvoice_recon_result(
        self, result_id: str | UUID, fields: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Update fields on a single e-invoice recon result."""
        rid = _parse_uuid(result_id)
        if not rid or not fields:
            return None
        session = self._get_session()
        try:
            stmt = select(EinvoiceReconResult).where(EinvoiceReconResult.id == rid)
            obj = session.scalars(stmt).first()
            if not obj:
                return None
            for k, v in fields.items():
                if hasattr(obj, k):
                    if k == "verified_at":
                        setattr(obj, k, _parse_datetime(v))
                    else:
                        setattr(obj, k, v)
            session.commit()
            session.refresh(obj)
            return _model_to_dict(obj)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_einvoice_recon_results(
        self,
        *,
        client_gstin_id: str | UUID,
        period: str,
        run_id: Optional[str | UUID] = None,
    ) -> list[dict[str, Any]]:
        """List e-invoice reconciliation results for a client and period."""
        cid = _parse_uuid(client_gstin_id)
        if not cid:
            return []
        session = self._get_session()
        try:
            stmt = select(EinvoiceReconResult).where(
                EinvoiceReconResult.client_gstin_id == cid,
                EinvoiceReconResult.period == period,
            )
            if run_id:
                rid = _parse_uuid(run_id)
                stmt = stmt.where(EinvoiceReconResult.run_id == rid)
            stmt = stmt.order_by(EinvoiceReconResult.invoice_number)
            results = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in results]
        finally:
            session.close()

    def get_einvoice_recon_results_by_run_or_client(
        self, run_id_or_client_id: str | UUID
    ) -> list[dict[str, Any]]:
        """List recon results by run_id, falling back to client_gstin_id."""
        uid = _parse_uuid(run_id_or_client_id)
        if not uid:
            return []
        session = self._get_session()
        try:
            stmt = select(EinvoiceReconResult).where(EinvoiceReconResult.run_id == uid)
            results = session.scalars(stmt).all()
            if not results:
                stmt_client = (
                    select(EinvoiceReconResult)
                    .where(EinvoiceReconResult.client_gstin_id == uid)
                    .order_by(sa_desc(EinvoiceReconResult.created_at))
                    .limit(200)
                )
                results = session.scalars(stmt_client).all()
            return [_model_to_dict(r) for r in results]
        finally:
            session.close()

    def insert_einvoice_recon_results(
        self, results: Sequence[dict[str, Any]]
    ) -> int:
        """Batch insert e-invoice reconciliation results."""
        if not results:
            return 0
        session = self._get_session()
        try:
            count = 0
            now = datetime.now(timezone.utc)
            for r in results:
                cid = _parse_uuid(r.get("client_gstin_id"))
                if not cid:
                    continue
                rid = _parse_uuid(r.get("run_id"))
                obj = EinvoiceReconResult(
                    id=_parse_uuid(r.get("id")) or (None if _is_sqlite(session) else sa.text("gen_random_uuid()")),
                    run_id=rid,
                    client_gstin_id=cid,
                    period=str(r.get("period") or "")[:7],
                    invoice_number=str(r.get("invoice_number") or ""),
                    irn=r.get("irn"),
                    irn_status=r.get("irn_status"),
                    category=str(r.get("category") or "other"),
                    book_value=_parse_numeric(r.get("book_value") or 0),
                    einvoice_value=_parse_numeric(r.get("einvoice_value") or 0),
                    details=r.get("details"),
                    verification_source=r.get("verification_source"),
                    verified_at=_parse_datetime(r.get("verified_at")),
                    created_at=_parse_datetime(r.get("created_at")) or now,
                )
                session.add(obj)
                count += 1
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 5. GST Fetch Log ───────────────────────────────────────────────────────

    def insert_gst_fetch_log(self, log_entry: dict[str, Any]) -> dict[str, Any]:
        """Record an outcome in gst_fetch_log."""
        cid = _parse_uuid(log_entry.get("client_id"))
        if not cid:
            raise ValueError("client_id is required for gst_fetch_log")

        session = self._get_session()
        try:
            now = datetime.now(timezone.utc)
            obj = GstFetchLog(
                id=_parse_uuid(log_entry.get("id")) or (None if _is_sqlite(session) else sa.text("gen_random_uuid()")),
                client_id=cid,
                gstin=str(log_entry.get("gstin") or ""),
                return_type=str(log_entry.get("return_type") or ""),
                period=str(log_entry.get("period") or ""),
                section=str(log_entry.get("section") or ""),
                status=str(log_entry.get("status") or ""),
                fetched_at=_parse_datetime(log_entry.get("fetched_at")) or now,
                error_message=log_entry.get("error_message"),
            )
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return _model_to_dict(obj)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 6. IMS Action Submissions & RPC Claim ─────────────────────────────────

    def find_non_failed_ims_submission(
        self, *, invoice_id: str, period: str, gstin: str
    ) -> Optional[dict[str, Any]]:
        """Find non-failed submission for an invoice/period/gstin."""
        session = self._get_session()
        try:
            p = str(period or "")[:7]
            g = str(gstin or "").strip().upper()
            stmt = select(ImsActionSubmission).where(
                ImsActionSubmission.invoice_id == invoice_id,
                ImsActionSubmission.period == p,
                ImsActionSubmission.gstin == g,
                ImsActionSubmission.status.in_(["claiming", "pending", "confirmed", "unclear"]),
            ).limit(1)
            result = session.scalars(stmt).first()
            return _model_to_dict(result) if result else None
        finally:
            session.close()

    def list_ims_submissions_for_run(
        self, run_id: str | UUID, status: Optional[str] = "confirmed"
    ) -> list[dict[str, Any]]:
        """List IMS submissions associated with a reconciliation run."""
        rid = _parse_uuid(run_id)
        if not rid:
            return []
        session = self._get_session()
        try:
            stmt = select(ImsActionSubmission).where(ImsActionSubmission.run_id == rid)
            if status:
                stmt = stmt.where(ImsActionSubmission.status == status)
            results = session.scalars(stmt).all()
            return [_model_to_dict(r) for r in results]
        finally:
            session.close()

    def upsert_ims_submission(self, row: dict[str, Any]) -> dict[str, Any]:
        """Upsert an IMS action submission record."""
        session = self._get_session()
        try:
            p = str(row.get("period") or "")[:7]
            g = str(row.get("gstin") or "").strip().upper()
            inv_id = str(row.get("invoice_id") or "")
            now = datetime.now(timezone.utc)
            rid = _parse_uuid(row.get("run_id"))

            existing = session.scalars(
                select(ImsActionSubmission).where(
                    ImsActionSubmission.invoice_id == inv_id,
                    ImsActionSubmission.period == p,
                    ImsActionSubmission.gstin == g,
                )
            ).first()

            if existing:
                for k, v in row.items():
                    if k in ("id", "invoice_id", "period", "gstin", "created_at"):
                        continue
                    if k == "run_id":
                        setattr(existing, k, _parse_uuid(v))
                    elif hasattr(existing, k):
                        setattr(existing, k, v)
                existing.updated_at = now
                session.commit()
                session.refresh(existing)
                return _model_to_dict(existing)
            else:
                obj = ImsActionSubmission(
                    id=_parse_uuid(row.get("id")) or (None if _is_sqlite(session) else sa.text("gen_random_uuid()")),
                    invoice_id=inv_id,
                    period=p,
                    gstin=g,
                    chosen_action=str(row.get("chosen_action") or "accept"),
                    recommended_action=row.get("recommended_action"),
                    submit_mode=str(row.get("submit_mode") or "confirm_recommendation"),
                    status=str(row.get("status") or "pending"),
                    reference_id=row.get("reference_id"),
                    transaction_id=row.get("transaction_id"),
                    status_cd=row.get("status_cd"),
                    error_code=row.get("error_code"),
                    error_message=row.get("error_message"),
                    raw_poll=row.get("raw_poll"),
                    run_id=rid,
                    created_at=now,
                    updated_at=now,
                )
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return _model_to_dict(obj)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def try_claim_ims_submission(
        self,
        *,
        invoice_id: str,
        period: str,
        gstin: str,
        chosen_action: str,
        recommended_action: Optional[str] = None,
        submit_mode: str = "confirm_recommendation",
        run_id: Optional[str | UUID] = None,
    ) -> Optional[dict[str, Any]]:
        """Atomic claim via PostgreSQL function fn_claim_ims_action_submission or equivalent SQLite transaction."""
        p = str(period or "")[:7]
        g = str(gstin or "").strip().upper()
        rid = _parse_uuid(run_id)
        mode = submit_mode or "confirm_recommendation"

        session = self._get_session()
        try:
            if not _is_sqlite(session):
                # Execute native PostgreSQL stored procedure
                stmt = sa.text("""
                    SELECT id, invoice_id, gstin, period, chosen_action, recommended_action,
                           submit_mode, status, reference_id, transaction_id, status_cd,
                           error_code, error_message, raw_poll, run_id, created_at, updated_at
                    FROM public.fn_claim_ims_action_submission(
                        :p_invoice_id,
                        :p_gstin,
                        :p_period,
                        :p_chosen_action,
                        :p_recommended_action,
                        :p_submit_mode,
                        :p_run_id
                    )
                """)
                res = session.execute(
                    stmt,
                    {
                        "p_invoice_id": invoice_id,
                        "p_gstin": g,
                        "p_period": p,
                        "p_chosen_action": chosen_action,
                        "p_recommended_action": recommended_action,
                        "p_submit_mode": mode,
                        "p_run_id": str(rid) if rid else None,
                    },
                ).mappings().first()
                session.commit()
                return dict(res) if res else None
            else:
                # SQLite fallback implementing identical concurrency/idempotency semantics
                now = datetime.now(timezone.utc)
                existing = session.scalars(
                    select(ImsActionSubmission).where(
                        ImsActionSubmission.invoice_id == invoice_id,
                        ImsActionSubmission.period == p,
                        ImsActionSubmission.gstin == g,
                    )
                ).first()

                if existing is None:
                    obj = ImsActionSubmission(
                        id=None,
                        invoice_id=invoice_id,
                        period=p,
                        gstin=g,
                        chosen_action=chosen_action,
                        recommended_action=recommended_action,
                        submit_mode=mode,
                        status="claiming",
                        run_id=rid,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(obj)
                    session.commit()
                    session.refresh(obj)
                    return _model_to_dict(obj)
                elif existing.status in ("failed", "claimed_offline"):
                    existing.chosen_action = chosen_action
                    existing.recommended_action = recommended_action
                    existing.submit_mode = mode
                    existing.status = "claiming"
                    existing.run_id = rid
                    existing.updated_at = now
                    session.commit()
                    session.refresh(existing)
                    return _model_to_dict(existing)
                else:
                    return None
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


_integrations_repo_instance: Optional[AuroraIntegrationsRepository] = None


def get_integrations_repository() -> AuroraIntegrationsRepository:
    """Singleton getter for AuroraIntegrationsRepository."""
    global _integrations_repo_instance
    if _integrations_repo_instance is None:
        _integrations_repo_instance = AuroraIntegrationsRepository()
    return _integrations_repo_instance
