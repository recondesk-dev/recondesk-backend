"""AWS Aurora Client Portal, Communication, User Preferences & Audit Logs Repository — Batch 4C.

Provides typed, safe SQLAlchemy 2.x data access for:
1. notification_preferences (Per-user email notification toggles)
2. upload_requests (Client portal upload links with token and expiry)
3. uploaded_files (Uploaded file artifacts and metadata)
4. communication_logs (Audit log of dispatched client messages)
5. audit_logs (Insert-only workspace audit trail with firm_id scoping)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import desc as sa_desc, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
    get_aurora_session,
)
from app.models.portal_and_audit import (
    AuditLog,
    CommunicationLog,
    NotificationPreference,
    UploadedFile,
    UploadRequest,
)

_log = logging.getLogger("recondesk.aurora.portal_and_audit")


def _parse_uuid(val: Any) -> Optional[UUID]:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val).strip())
    except (ValueError, TypeError, AttributeError):
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


class AuroraPortalAndAuditRepository:
    """SQLAlchemy repository for Batch 4C entities."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session]] = None,
        session: Optional[Session] = None,
    ) -> None:
        self._session_factory = session_factory
        self._session = session

    def _get_session(self) -> Session:
        if self._session is not None:
            return self._session
        if self._session_factory is not None:
            return self._session_factory()
        return get_aurora_session()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Notification Preferences
    # ─────────────────────────────────────────────────────────────────────────

    def get_notification_preferences(self, user_id: str) -> Optional[dict[str, Any]]:
        u_uuid = _parse_uuid(user_id)
        if not u_uuid:
            return None
        with self._get_session() as session:
            record = session.get(NotificationPreference, u_uuid)
            return record.to_dict() if record else None

    def upsert_notification_preferences(
        self,
        user_id: str,
        *,
        run_completed: bool = True,
        runs_expiring_soon: bool = True,
        payment_receipts: bool = True,
        rule37_alerts: bool = True,
    ) -> dict[str, Any]:
        u_uuid = _parse_uuid(user_id)
        if not u_uuid:
            raise ValueError(f"Invalid user_id UUID: {user_id}")
        with self._get_session() as session:
            record = session.get(NotificationPreference, u_uuid)
            now = datetime.now(timezone.utc)
            if record:
                record.run_completed = run_completed
                record.runs_expiring_soon = runs_expiring_soon
                record.payment_receipts = payment_receipts
                record.rule37_alerts = rule37_alerts
                record.updated_at = now
            else:
                record = NotificationPreference(
                    user_id=u_uuid,
                    run_completed=run_completed,
                    runs_expiring_soon=runs_expiring_soon,
                    payment_receipts=payment_receipts,
                    rule37_alerts=rule37_alerts,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            session.commit()
            session.refresh(record)
            return record.to_dict()

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Upload Requests
    # ─────────────────────────────────────────────────────────────────────────

    def get_upload_request_by_id(self, upload_request_id: str) -> Optional[dict[str, Any]]:
        r_uuid = _parse_uuid(upload_request_id)
        if not r_uuid:
            return None
        with self._get_session() as session:
            record = session.get(UploadRequest, r_uuid)
            return record.to_dict() if record else None

    def get_upload_request_by_token(self, token: str) -> Optional[dict[str, Any]]:
        clean_token = str(token or "").strip()
        if not clean_token:
            return None
        with self._get_session() as session:
            stmt = select(UploadRequest).where(UploadRequest.token == clean_token).limit(1)
            record = session.scalars(stmt).first()
            return record.to_dict() if record else None

    def list_upload_requests(
        self,
        client_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        c_uuid = _parse_uuid(client_id)
        if not c_uuid:
            return []
        with self._get_session() as session:
            stmt = (
                select(UploadRequest)
                .where(UploadRequest.client_id == c_uuid)
                .order_by(sa_desc(UploadRequest.created_at))
                .offset(offset)
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [r.to_dict() for r in rows]

    def create_upload_request(
        self,
        *,
        client_id: str,
        organization_id: str,
        token: str,
        title: str,
        description: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        created_by_user_id: str,
    ) -> dict[str, Any]:
        c_uuid = _parse_uuid(client_id)
        org_uuid = _parse_uuid(organization_id)
        creator_uuid = _parse_uuid(created_by_user_id)
        if not c_uuid or not org_uuid or not creator_uuid:
            raise ValueError("Invalid client_id, organization_id, or created_by_user_id UUID")

        with self._get_session() as session:
            rec = UploadRequest(
                client_id=c_uuid,
                organization_id=org_uuid,
                token=str(token).strip(),
                title=str(title).strip(),
                description=description.strip() if description else None,
                expires_at=_parse_dt(expires_at),
                created_by_user_id=creator_uuid,
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return rec.to_dict()

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Uploaded Files
    # ─────────────────────────────────────────────────────────────────────────

    def get_uploaded_file(self, file_id: str) -> Optional[dict[str, Any]]:
        f_uuid = _parse_uuid(file_id)
        if not f_uuid:
            return None
        with self._get_session() as session:
            record = session.get(UploadedFile, f_uuid)
            return record.to_dict() if record else None

    def list_uploaded_files_by_request_ids(
        self,
        upload_request_ids: Sequence[str],
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        uuids = [_parse_uuid(x) for x in upload_request_ids if _parse_uuid(x) is not None]
        if not uuids:
            return []
        with self._get_session() as session:
            stmt = (
                select(UploadedFile)
                .where(UploadedFile.upload_request_id.in_(uuids))
                .order_by(sa_desc(UploadedFile.uploaded_at))
                .offset(offset)
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [r.to_dict() for r in rows]

    def create_uploaded_file(
        self,
        *,
        upload_request_id: str,
        filename: str,
        file_size: int,
        mime_type: str,
        public_url: str,
    ) -> dict[str, Any]:
        req_uuid = _parse_uuid(upload_request_id)
        if not req_uuid:
            raise ValueError("Invalid upload_request_id UUID")
        with self._get_session() as session:
            rec = UploadedFile(
                upload_request_id=req_uuid,
                filename=str(filename).strip(),
                file_size=int(file_size),
                mime_type=str(mime_type).strip(),
                public_url=str(public_url).strip(),
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return rec.to_dict()

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Communication Logs
    # ─────────────────────────────────────────────────────────────────────────

    def get_communication_log(self, log_id: str) -> Optional[dict[str, Any]]:
        l_uuid = _parse_uuid(log_id)
        if not l_uuid:
            return None
        with self._get_session() as session:
            record = session.get(CommunicationLog, l_uuid)
            return record.to_dict() if record else None

    def list_communication_logs(
        self,
        client_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        c_uuid = _parse_uuid(client_id)
        if not c_uuid:
            return []
        with self._get_session() as session:
            stmt = (
                select(CommunicationLog)
                .where(CommunicationLog.client_id == c_uuid)
                .order_by(sa_desc(CommunicationLog.created_at))
                .offset(offset)
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [r.to_dict() for r in rows]

    def create_communication_log(
        self,
        *,
        client_id: str,
        organization_id: str,
        template_type: str,
        message_content: str,
        sent_via: str,
        sent_by_user_id: str,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        c_uuid = _parse_uuid(client_id)
        org_uuid = _parse_uuid(organization_id)
        sender_uuid = _parse_uuid(sent_by_user_id)
        if not c_uuid or not org_uuid or not sender_uuid:
            raise ValueError("Invalid client_id, organization_id, or sent_by_user_id UUID")

        with self._get_session() as session:
            rec = CommunicationLog(
                client_id=c_uuid,
                organization_id=org_uuid,
                template_type=str(template_type).strip(),
                message_content=str(message_content).strip(),
                sent_via=str(sent_via).strip(),
                sent_by_user_id=sender_uuid,
                notes=str(notes).strip() if notes else None,
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return rec.to_dict()

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Audit Logs
    # ─────────────────────────────────────────────────────────────────────────

    def insert_audit_log(
        self,
        *,
        action: str,
        user_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None,
        firm_id: Optional[str] = None,
        user_name: Optional[str] = None,
        role: Optional[str] = None,
        entity_label: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        u_uuid = _parse_uuid(user_id)
        e_uuid = _parse_uuid(entity_id)
        corr_uuid = _parse_uuid(correlation_id)
        f_uuid = _parse_uuid(firm_id)

        with self._get_session() as session:
            rec = AuditLog(
                user_id=u_uuid,
                action=str(action).strip(),
                entity_type=str(entity_type).strip() if entity_type else None,
                entity_id=e_uuid,
                metadata_=metadata,
                created_at=_parse_dt(created_at) or datetime.now(timezone.utc),
                ip_address=str(ip_address).strip()[:128] if ip_address else None,
                correlation_id=corr_uuid,
                firm_id=f_uuid,
                user_name=str(user_name).strip() if user_name else None,
                role=str(role).strip() if role else None,
                entity_label=str(entity_label).strip() if entity_label else None,
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return rec.to_dict()

    def list_audit_logs(
        self,
        firm_id: str,
        *,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[list[dict[str, Any]], int]:
        f_uuid = _parse_uuid(firm_id)
        if not f_uuid:
            return [], 0

        with self._get_session() as session:
            stmt = select(AuditLog).where(AuditLog.firm_id == f_uuid)
            count_stmt = select(func.count(AuditLog.id)).where(AuditLog.firm_id == f_uuid)

            if user_id:
                u_uuid = _parse_uuid(user_id)
                if u_uuid:
                    stmt = stmt.where(AuditLog.user_id == u_uuid)
                    count_stmt = count_stmt.where(AuditLog.user_id == u_uuid)
            if action:
                stmt = stmt.where(AuditLog.action == action.strip())
                count_stmt = count_stmt.where(AuditLog.action == action.strip())
            if from_date:
                dt_from = _parse_dt(from_date)
                if dt_from:
                    stmt = stmt.where(AuditLog.created_at >= dt_from)
                    count_stmt = count_stmt.where(AuditLog.created_at >= dt_from)
            if to_date:
                dt_to = _parse_dt(to_date)
                if dt_to:
                    stmt = stmt.where(AuditLog.created_at <= dt_to)
                    count_stmt = count_stmt.where(AuditLog.created_at <= dt_to)

            total = session.scalar(count_stmt) or 0
            stmt = stmt.order_by(sa_desc(AuditLog.created_at)).offset(offset).limit(limit)
            rows = session.scalars(stmt).all()
            return [r.to_dict() for r in rows], int(total)

    def check_audit_log_exists(self, action: str, entity_id: str) -> bool:
        """Check if an audit log entry already exists (for idempotency guards)."""
        e_uuid = _parse_uuid(entity_id)
        if not e_uuid:
            return False
        with self._get_session() as session:
            stmt = (
                select(AuditLog.id)
                .where(AuditLog.action == action.strip())
                .where(AuditLog.entity_id == e_uuid)
                .limit(1)
            )
            return session.scalar(stmt) is not None


_global_portal_and_audit_repo: Optional[AuroraPortalAndAuditRepository] = None


def get_portal_and_audit_repository() -> AuroraPortalAndAuditRepository:
    """Return the global repository singleton."""
    global _global_portal_and_audit_repo
    if _global_portal_and_audit_repo is None:
        _global_portal_and_audit_repo = AuroraPortalAndAuditRepository()
    return _global_portal_and_audit_repo


def set_portal_and_audit_repository(
    repo: Optional[AuroraPortalAndAuditRepository],
) -> None:
    """Inject or reset repository instance (used in tests)."""
    global _global_portal_and_audit_repo
    _global_portal_and_audit_repo = repo
