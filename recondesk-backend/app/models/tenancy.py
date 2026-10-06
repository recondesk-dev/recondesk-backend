"""SQLAlchemy 2.x declarative models for the foundational Aurora tenancy layer.

Defines:
- UserProfile: Canonical ReconDesk user profile and firm owner anchor.
- TeamMember: Staff team membership and invitations under a firm owner.
- ClientGSTIN: Client GSTIN records owned by a firm owner and assigned to staff.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.schema_base import Base, GUID


class UserProfile(Base):
    """Canonical ReconDesk user profile in AWS Aurora.

    Represents CA principals (firm owners) and team members (staff).
    Serves as the root foreign key anchor for tenancy and client assignments.
    """

    __tablename__ = "user_profiles"

    id = Column(GUID(), primary_key=True)
    email = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    firm_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    role = Column(String(50), default="admin", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    plan = Column(String(50), default="free", nullable=True)
    runs_used = Column(Integer, default=0, nullable=True)
    runs_limit = Column(Integer, default=2, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    runs_balance = Column(Integer, default=0, nullable=True)
    free_runs_remaining = Column(Integer, default=2, nullable=False)
    firm_city = Column(String(255), nullable=True)
    onboarding_completed = Column(Boolean, default=False, nullable=True)
    icai_membership_number = Column(String(100), nullable=True)
    firm_gstin = Column(String(15), nullable=True)
    gstin_limit = Column(Integer, default=2, nullable=False)
    subscription_ends_at = Column(DateTime(timezone=True), nullable=True)
    is_first_login = Column(Boolean, default=True, nullable=False)
    client_gstin_id = Column(String(15), nullable=True)
    auto_approve_confidence_threshold = Column(Integer, default=95, nullable=False)

    # Relationships
    owned_clients = relationship(
        "ClientGSTIN",
        foreign_keys="ClientGSTIN.firm_owner_id",
        back_populates="firm_owner",
        cascade="all, delete-orphan",
    )
    assigned_clients = relationship(
        "ClientGSTIN",
        foreign_keys="ClientGSTIN.assigned_to",
        back_populates="assignee",
    )
    team_memberships = relationship(
        "TeamMember",
        foreign_keys="TeamMember.firm_owner_id",
        back_populates="firm_owner",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize user profile into dictionary compatible with Supabase PostgREST format."""
        return {
            "id": str(self.id),
            "email": self.email,
            "full_name": self.full_name,
            "firm_name": self.firm_name,
            "phone": self.phone,
            "role": self.role,
            "is_active": self.is_active,
            "plan": self.plan,
            "runs_used": self.runs_used,
            "runs_limit": self.runs_limit,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "runs_balance": self.runs_balance,
            "free_runs_remaining": self.free_runs_remaining,
            "firm_city": self.firm_city,
            "onboarding_completed": self.onboarding_completed,
            "icai_membership_number": self.icai_membership_number,
            "firm_gstin": self.firm_gstin,
            "gstin_limit": self.gstin_limit,
            "subscription_ends_at": (
                self.subscription_ends_at.isoformat() if self.subscription_ends_at else None
            ),
            "is_first_login": self.is_first_login,
            "client_gstin_id": self.client_gstin_id,
            "auto_approve_confidence_threshold": self.auto_approve_confidence_threshold,
        }


class TeamMember(Base):
    """Team membership and invitation record in AWS Aurora.

    Maps a firm owner (CA) to staff members or pending invitations.
    """

    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("firm_owner_id", "member_user_id", name="uq_team_members_firm_member"),
        CheckConstraint("role IN ('admin', 'staff')", name="ck_team_members_role"),
        Index("idx_team_members_firm_owner_id", "firm_owner_id"),
        Index("idx_team_members_member_user_id", "member_user_id"),
        Index("idx_team_members_invited_email", "invited_email"),
    )

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    firm_owner_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_user_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    role = Column(String(50), nullable=False, default="staff")
    invited_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    invited_email = Column(String(255), nullable=True)
    invite_token = Column(String(255), nullable=True)
    invite_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    firm_owner = relationship(
        "UserProfile",
        foreign_keys=[firm_owner_id],
        back_populates="team_memberships",
    )
    member = relationship(
        "UserProfile",
        foreign_keys=[member_user_id],
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize team member record into dictionary compatible with Supabase PostgREST format."""
        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id),
            "member_user_id": str(self.member_user_id) if self.member_user_id else None,
            "role": self.role,
            "invited_at": self.invited_at.isoformat() if self.invited_at else None,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "is_active": self.is_active,
            "invited_email": self.invited_email,
            "invite_token": self.invite_token,
            "invite_expires_at": (
                self.invite_expires_at.isoformat() if self.invite_expires_at else None
            ),
        }


class ClientGSTIN(Base):
    """Client GSTIN entity in AWS Aurora.

    Represents GSTIN registration scoped to a firm owner and assigned to staff.
    """

    __tablename__ = "client_gstins"
    __table_args__ = (
        UniqueConstraint("firm_owner_id", "gstin", name="uq_client_gstins_firm_gstin"),
        CheckConstraint(
            "scheme_type IN ('regular', 'composition', 'casual', 'nrtp', 'isd', 'tds_tcs_deductor')",
            name="ck_client_gstins_scheme_type",
        ),
        CheckConstraint(
            "filing_frequency IN ('monthly', 'qrmp')",
            name="ck_client_gstins_filing_frequency",
        ),
        Index("idx_client_gstins_firm_owner_id", "firm_owner_id"),
        Index("idx_client_gstins_assigned_to", "assigned_to"),
        Index("idx_client_gstins_gstin", "gstin"),
    )

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    firm_owner_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    gstin = Column(String(15), nullable=False)
    trade_name = Column(String(255), nullable=True)
    legal_name = Column(String(255), nullable=True)
    state_code = Column(String(10), nullable=True)
    registration_type = Column(String(50), nullable=True)
    assigned_to = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column(Boolean, nullable=False, default=True)
    added_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    gstn_access_token = Column(String, nullable=True)
    gstn_token_expiry = Column(DateTime(timezone=True), nullable=True)
    is_demo = Column(Boolean, nullable=False, default=False)
    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    scheme_type = Column(String(50), nullable=False, default="regular")
    filing_frequency = Column(String(20), nullable=False, default="monthly")

    # Relationships
    firm_owner = relationship(
        "UserProfile",
        foreign_keys=[firm_owner_id],
        back_populates="owned_clients",
    )
    assignee = relationship(
        "UserProfile",
        foreign_keys=[assigned_to],
        back_populates="assigned_clients",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize client GSTIN record into dictionary compatible with Supabase PostgREST format."""
        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id),
            "gstin": self.gstin,
            "trade_name": self.trade_name,
            "legal_name": self.legal_name,
            "state_code": self.state_code,
            "registration_type": self.registration_type,
            "assigned_to": str(self.assigned_to) if self.assigned_to else None,
            "is_active": self.is_active,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "gstn_access_token": self.gstn_access_token,
            "gstn_token_expiry": (
                self.gstn_token_expiry.isoformat() if self.gstn_token_expiry else None
            ),
            "is_demo": self.is_demo,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "scheme_type": self.scheme_type,
            "filing_frequency": self.filing_frequency,
        }
