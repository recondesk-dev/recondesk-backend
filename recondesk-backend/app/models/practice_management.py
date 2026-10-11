"""Models for Phase 3.4 CA Firm Practice Management, PAN Organizations, and Staff Tasks.

Provides SQLAlchemy ORM mappings, enums, and serialized dataclass representations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.models.schema_base import Base, GUID


class TaskCategory(str, Enum):
    RECONCILIATION = "RECONCILIATION"
    GSTR1_FILING = "GSTR1_FILING"
    GSTR3B_FILING = "GSTR3B_FILING"
    GSTR9_FILING = "GSTR9_FILING"
    CLIENT_APPROVAL = "CLIENT_APPROVAL"
    MAKER_CHECKER_REVIEW = "MAKER_CHECKER_REVIEW"
    NOTICE_REPLY = "NOTICE_REPLY"
    ITC_REVIEW = "ITC_REVIEW"
    GENERAL_COMPLIANCE = "GENERAL_COMPLIANCE"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TaskStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskAction(str, Enum):
    CREATED = "CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    REASSIGNED = "REASSIGNED"
    DUE_DATE_UPDATED = "DUE_DATE_UPDATED"
    COMMENT_ADDED = "COMMENT_ADDED"
    COMPLETED = "COMPLETED"
    DELETED = "DELETED"


# ---------------------------------------------------------------------------
# SQLAlchemy Models
# ---------------------------------------------------------------------------

class ClientOrganization(Base):
    """PAN-level legal entity grouping one or more state GSTINs."""

    __tablename__ = "client_organizations"

    id = Column(GUID(), primary_key=True, default=uuid4)
    firm_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    pan = Column(String(10), nullable=False)
    legal_name = Column(String(255), nullable=False)
    trade_name = Column(String(255), nullable=True)
    constitution_of_business = Column(String(100), nullable=True)
    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    extra_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_client_organizations_firm_id", "firm_id"),
        Index("idx_client_organizations_pan", "pan"),
        Index("idx_client_organizations_legal_name", "firm_id", "legal_name"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_id": str(self.firm_id),
            "pan": self.pan,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "constitution_of_business": self.constitution_of_business,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "is_active": self.is_active,
            "metadata": self.extra_metadata or {},
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }


class PracticeTask(Base):
    """Staff task item anchored to a firm, organization, client GSTIN, and period."""

    __tablename__ = "practice_tasks"

    id = Column(GUID(), primary_key=True, default=uuid4)
    firm_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(GUID(), ForeignKey("client_organizations.id", ondelete="SET NULL"), nullable=True)
    client_gstin_id = Column(GUID(), ForeignKey("client_gstins.id", ondelete="CASCADE"), nullable=True)
    period = Column(String(7), nullable=True)
    category = Column(String(50), nullable=False, default=TaskCategory.GENERAL_COMPLIANCE.value)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String(20), nullable=False, default=TaskPriority.MEDIUM.value)
    status = Column(String(30), nullable=False, default=TaskStatus.TODO.value)
    assignee_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(Date, nullable=True)
    created_by = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_by = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    extra_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_practice_tasks_firm_status", "firm_id", "status"),
        Index("idx_practice_tasks_assignee", "firm_id", "assignee_id"),
        Index("idx_practice_tasks_client_period", "client_gstin_id", "period"),
        Index("idx_practice_tasks_due_date", "firm_id", "due_date"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_id": str(self.firm_id),
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "client_gstin_id": str(self.client_gstin_id) if self.client_gstin_id else None,
            "period": self.period,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "assignee_id": str(self.assignee_id) if self.assignee_id else None,
            "due_date": str(self.due_date) if self.due_date else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "completed_at": self.completed_at.isoformat() if isinstance(self.completed_at, datetime) else (str(self.completed_at) if self.completed_at else None),
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "metadata": self.extra_metadata or {},
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }


class PracticeTaskAuditTrail(Base):
    """Immutable audit trail of task assignments, state transitions, and notes."""

    __tablename__ = "practice_task_audit_trail"

    id = Column(GUID(), primary_key=True, default=uuid4)
    task_id = Column(GUID(), ForeignKey("practice_tasks.id", ondelete="CASCADE"), nullable=False)
    firm_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(50), nullable=False)
    actor_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String(255), nullable=False)
    actor_role = Column(String(50), nullable=False)
    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=True)
    from_assignee_id = Column(GUID(), nullable=True)
    to_assignee_id = Column(GUID(), nullable=True)
    notes = Column(Text, nullable=True)
    extra_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "task_id": str(self.task_id),
            "firm_id": str(self.firm_id),
            "action": self.action,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "actor_name": self.actor_name,
            "actor_role": self.actor_role,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "from_assignee_id": str(self.from_assignee_id) if self.from_assignee_id else None,
            "to_assignee_id": str(self.to_assignee_id) if self.to_assignee_id else None,
            "notes": self.notes,
            "metadata": self.extra_metadata or {},
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
        }


# ---------------------------------------------------------------------------
# Dataclasses for in-memory and testing operations
# ---------------------------------------------------------------------------

@dataclass
class OrganizationData:
    id: str
    firm_id: str
    pan: str
    legal_name: str
    trade_name: Optional[str] = None
    constitution_of_business: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "firm_id": self.firm_id,
            "pan": self.pan,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "constitution_of_business": self.constitution_of_business,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "is_active": self.is_active,
            "metadata": self.metadata or {},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TaskData:
    id: str
    firm_id: str
    title: str
    category: str = TaskCategory.GENERAL_COMPLIANCE.value
    organization_id: Optional[str] = None
    client_gstin_id: Optional[str] = None
    period: Optional[str] = None
    description: Optional[str] = None
    priority: str = TaskPriority.MEDIUM.value
    status: str = TaskStatus.TODO.value
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    created_by: Optional[str] = None
    completed_at: Optional[str] = None
    completed_by: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "firm_id": self.firm_id,
            "organization_id": self.organization_id,
            "client_gstin_id": self.client_gstin_id,
            "period": self.period,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "assignee_id": self.assignee_id,
            "due_date": self.due_date,
            "created_by": self.created_by,
            "completed_at": self.completed_at,
            "completed_by": self.completed_by,
            "metadata": self.metadata or {},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
