"""AWS Aurora Tenancy Repository for ReconDesk.

Provides safe, typed SQLAlchemy data-access methods for:
- User profiles (lookup, active status, role resolution)
- Firm membership (owner resolution, team membership, invite tracking)
- Client GSTINs (firm listing, staff assignment, ownership verification)

Security Invariants:
1. Always operates on canonical ReconDesk IDs (user_profiles.id), NEVER raw Cognito claims.sub.
2. Respects is_active flags across all tenant and client lookups.
3. Distinguishes between infrastructure misses (table/record not yet in Aurora)
   and authorization denials (record exists but does not belong to firm/staff).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.tenancy import ClientGSTIN, TeamMember, UserProfile

_log = logging.getLogger("recondesk.aurora.tenancy")


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val is None or isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    return None


class AuroraTenancyRepository:
    """Repository handling tenancy, profile, and client authorization queries against AWS Aurora."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session]] = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            from app.aurora import get_aurora_sessionmaker
            self._session_factory = get_aurora_sessionmaker()

    def _get_session(self) -> Session:
        return self._session_factory()

    # ── User Profile Operations ───────────────────────────────────────────────

    def get_user_profile(self, user_id: str) -> Optional[dict[str, Any]]:
        """Fetch canonical user profile by primary key (user_profiles.id)."""
        uid = str(user_id or "").strip()
        if not uid:
            return None

        with self._get_session() as session:
            stmt = select(UserProfile).where(UserProfile.id == uid)
            profile = session.scalar(stmt)
            if profile is None:
                return None
            return profile.to_dict()

    def is_user_active(self, user_id: str) -> Optional[bool]:
        """Check whether a user account is active.

        Returns:
            True: Profile found and is_active is True.
            False: Profile found and is_active is False (denial).
            None: Profile not found in Aurora (infrastructure miss).
        """
        uid = str(user_id or "").strip()
        if not uid:
            return None

        with self._get_session() as session:
            stmt = select(UserProfile.is_active).where(UserProfile.id == uid)
            res = session.execute(stmt).first()
            if res is None:
                return None
            return bool(res[0])

    def get_user_role(self, user_id: str) -> Optional[str]:
        """Retrieve user's canonical role from Aurora user profile.

        Returns role string ('admin', 'staff', 'owner') or None if not found in Aurora.
        """
        uid = str(user_id or "").strip()
        if not uid:
            return None

        with self._get_session() as session:
            stmt = select(UserProfile.role).where(UserProfile.id == uid)
            res = session.execute(stmt).first()
            if res is None:
                return None
            return str(res[0] or "admin").strip().lower()

    def _ensure_user_profile_exists(
        self,
        session: Session,
        user_id: str,
        *,
        role: str = "admin",
        email: Optional[str] = None,
    ) -> None:
        """Auto-seed a minimal placeholder UserProfile to satisfy foreign key constraints."""
        uid = str(user_id or "").strip()
        if not uid:
            return
        stmt = select(UserProfile.id).where(UserProfile.id == uid).limit(1)
        if session.execute(stmt).first() is None:
            prof = UserProfile(
                id=uid,
                email=email or f"{uid}@local.placeholder",
                role=role,
                is_active=True,
            )
            session.add(prof)
            session.flush()

    def upsert_user_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        """Upsert canonical user profile in Aurora."""
        uid = str(data.get("id") or "").strip()
        if not uid:
            raise ValueError("UserProfile id cannot be empty")

        valid_cols = {c.name for c in UserProfile.__table__.columns}
        with self._get_session() as session:
            prof = session.scalar(select(UserProfile).where(UserProfile.id == uid))
            if prof is not None:
                for k, v in data.items():
                    if k in valid_cols and k != "id":
                        if k in ("created_at", "subscription_ends_at"):
                            setattr(prof, k, _parse_datetime(v))
                        else:
                            setattr(prof, k, v)
                session.commit()
                return prof.to_dict()
            else:
                attrs: dict[str, Any] = {}
                for k, v in data.items():
                    if k in valid_cols:
                        if k in ("created_at", "subscription_ends_at"):
                            attrs[k] = _parse_datetime(v)
                        else:
                            attrs[k] = v
                if "id" not in attrs or not attrs["id"]:
                    attrs["id"] = uid
                if "role" not in attrs:
                    attrs["role"] = "admin"
                if "is_active" not in attrs:
                    attrs["is_active"] = True
                prof = UserProfile(**attrs)
                session.add(prof)
                session.commit()
                return prof.to_dict()

    def update_user_profile(
        self, user_id: str, fields: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Update specific columns of user profile in Aurora."""
        uid = str(user_id or "").strip()
        if not uid:
            return None

        valid_cols = {c.name for c in UserProfile.__table__.columns}
        with self._get_session() as session:
            prof = session.scalar(select(UserProfile).where(UserProfile.id == uid))
            if prof is None:
                self._ensure_user_profile_exists(session, uid)
                prof = session.scalar(select(UserProfile).where(UserProfile.id == uid))
                if prof is None:
                    return None
            for k, v in fields.items():
                if k in valid_cols and k != "id":
                    if k in ("created_at", "subscription_ends_at"):
                        setattr(prof, k, _parse_datetime(v))
                    else:
                        setattr(prof, k, v)
            session.commit()
            return prof.to_dict()

    # ── Firm Membership Operations ────────────────────────────────────────────

    def is_firm_owner(self, user_id: str) -> bool:
        """True if the user is a firm owner / CA principal."""
        uid = str(user_id or "").strip()
        if not uid:
            return False

        with self._get_session() as session:
            # 1. Direct role check
            role_stmt = select(UserProfile.role).where(UserProfile.id == uid)
            role_res = session.execute(role_stmt).first()
            if role_res and str(role_res[0]).strip().lower() in ("admin", "owner"):
                return True

            # 2. Check if user owns any clients
            client_stmt = select(ClientGSTIN.id).where(
                ClientGSTIN.firm_owner_id == uid,
                ClientGSTIN.is_active.is_(True),
            ).limit(1)
            if session.execute(client_stmt).first() is not None:
                return True

        return False

    def get_firm_owner_id_for_user(self, user_id: str) -> Optional[str]:
        """Resolve the CA principal ID that anchors this user's firm.

        - For Admin / Owner: returns user_id itself.
        - For Staff: checks active team membership or assigned client firm_owner_id.
        - Returns None if not resolved in Aurora.
        """
        uid = str(user_id or "").strip()
        if not uid:
            return None

        with self._get_session() as session:
            # Check user role first
            role_stmt = select(UserProfile.role).where(UserProfile.id == uid)
            role_res = session.execute(role_stmt).first()
            if role_res and str(role_res[0]).strip().lower() in ("admin", "owner"):
                return uid

            # Check team_members where member_user_id == uid
            tm_stmt = select(TeamMember.firm_owner_id).where(
                TeamMember.member_user_id == uid,
                TeamMember.is_active.is_(True),
            ).limit(1)
            tm_res = session.execute(tm_stmt).first()
            if tm_res and tm_res[0]:
                return str(tm_res[0])

            # Check assigned client_gstins where assigned_to == uid
            cg_stmt = select(ClientGSTIN.firm_owner_id).where(
                ClientGSTIN.assigned_to == uid,
                ClientGSTIN.is_active.is_(True),
            ).limit(1)
            cg_res = session.execute(cg_stmt).first()
            if cg_res and cg_res[0]:
                return str(cg_res[0])

        return None

    def get_team_membership(self, user_id: str) -> Optional[dict[str, Any]]:
        """Retrieve active team member record for a user in Aurora."""
        uid = str(user_id or "").strip()
        if not uid:
            return None

        with self._get_session() as session:
            stmt = select(TeamMember).where(
                TeamMember.member_user_id == uid,
                TeamMember.is_active.is_(True),
            ).limit(1)
            tm = session.scalar(stmt)
            if tm is None:
                return None
            return tm.to_dict()

    def create_or_update_team_member(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update team member/invitation in Aurora.

        FK Safe: Automatically ensures parent UserProfile rows exist for
        firm_owner_id and member_user_id to avoid ForeignKeyViolation errors.
        """
        mid = str(data.get("id") or "").strip()
        foid = str(data.get("firm_owner_id") or "").strip()
        member_uid = str(data.get("member_user_id") or "").strip() or None
        invited_email = str(data.get("invited_email") or "").strip().lower() or None

        valid_cols = {c.name for c in TeamMember.__table__.columns}
        with self._get_session() as session:
            if foid:
                self._ensure_user_profile_exists(session, foid, role="admin")
            if member_uid:
                self._ensure_user_profile_exists(
                    session, member_uid, role=str(data.get("role") or "staff")
                )

            member = None
            if mid:
                member = session.scalar(select(TeamMember).where(TeamMember.id == mid))
            if member is None and foid and member_uid:
                member = session.scalar(
                    select(TeamMember).where(
                        TeamMember.firm_owner_id == foid,
                        TeamMember.member_user_id == member_uid,
                    )
                )
            if member is None and foid and invited_email:
                member = session.scalar(
                    select(TeamMember).where(
                        TeamMember.firm_owner_id == foid,
                        TeamMember.invited_email == invited_email,
                    )
                )

            if member is not None:
                for k, v in data.items():
                    if k in valid_cols and k != "id":
                        if k in ("invited_at", "accepted_at", "invite_expires_at"):
                            setattr(member, k, _parse_datetime(v))
                        else:
                            setattr(member, k, v)
                session.commit()
                return member.to_dict()
            else:
                attrs: dict[str, Any] = {}
                for k, v in data.items():
                    if k in valid_cols:
                        if k in ("invited_at", "accepted_at", "invite_expires_at"):
                            attrs[k] = _parse_datetime(v)
                        else:
                            attrs[k] = v
                if "id" not in attrs or not attrs["id"]:
                    attrs["id"] = mid or str(uuid.uuid4())
                member = TeamMember(**attrs)
                session.add(member)
                session.commit()
                return member.to_dict()

    def update_team_member(
        self, member_id: str, fields: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Update specific columns of team member record in Aurora."""
        mid = str(member_id or "").strip()
        if not mid:
            return None

        valid_cols = {c.name for c in TeamMember.__table__.columns}
        with self._get_session() as session:
            member = session.scalar(select(TeamMember).where(TeamMember.id == mid))
            if member is None:
                return None
            member_uid = fields.get("member_user_id")
            if member_uid:
                self._ensure_user_profile_exists(
                    session,
                    str(member_uid).strip(),
                    role=str(fields.get("role") or member.role or "staff"),
                )
            for k, v in fields.items():
                if k in valid_cols and k != "id":
                    if k in ("invited_at", "accepted_at", "invite_expires_at"):
                        setattr(member, k, _parse_datetime(v))
                    else:
                        setattr(member, k, v)
            session.commit()
            return member.to_dict()

    def deactivate_team_member(self, member_id: str) -> bool:
        """Deactivate team member in Aurora."""
        mid = str(member_id or "").strip()
        if not mid:
            return False

        with self._get_session() as session:
            member = session.scalar(select(TeamMember).where(TeamMember.id == mid))
            if member is None:
                return False
            member.is_active = False
            member.member_user_id = None
            session.commit()
            return True

    # ── Client GSTIN Operations ───────────────────────────────────────────────

    def list_accessible_client_gstin_ids(
        self, user_id: str, role: Optional[str] = None
    ) -> Optional[Set[str]]:
        """List all active client_gstin IDs accessible to the given user in Aurora.

        Returns:
            None: user/tenancy identity is NOT present in Aurora (permits Supabase fallback).
            set(): user exists in Aurora but has zero accessible active clients (DO NOT fall back).
            non-empty set: user exists in Aurora and has accessible active clients (DO NOT fall back).

        - Admin/Owner: All active clients where firm_owner_id == user_id.
        - Staff: Only active clients where assigned_to == user_id.
        """
        uid = str(user_id or "").strip()
        if not uid:
            return None

        # Check if this user has a pending tenancy synchronization failure
        try:
            from app.services.tenancy_sync import (
                is_tenancy_sync_pending,
                reconcile_user_tenancy_from_supabase,
            )
            if is_tenancy_sync_pending(uid):
                reconciled = reconcile_user_tenancy_from_supabase(uid)
                if not reconciled:
                    # Reconciliation failed (Aurora down or error): permit Supabase fallback
                    return None
        except Exception as sync_exc:
            _log.warning("Tenancy sync check failed for %s: %s", uid, sync_exc)

        with self._get_session() as session:
            # 1. Check user existence in Aurora user_profiles
            user_stmt = (
                select(UserProfile.id, UserProfile.role)
                .where(UserProfile.id == uid)
                .limit(1)
            )
            user_row = session.execute(user_stmt).first()
            if user_row is None:
                return None  # User absent from Aurora: permit Supabase fallback

            resolved_role = (role or user_row[1] or "admin").strip().lower()

            # 2. Query accessible clients in Aurora
            if resolved_role in ("admin", "owner") or not resolved_role:
                stmt = select(ClientGSTIN.id).where(
                    ClientGSTIN.firm_owner_id == uid,
                    ClientGSTIN.is_active.is_(True),
                )
            else:
                stmt = select(ClientGSTIN.id).where(
                    ClientGSTIN.assigned_to == uid,
                    ClientGSTIN.is_active.is_(True),
                )

            rows = session.execute(stmt).fetchall()
            return {str(r[0]) for r in rows if r[0]}

    def list_accessible_clients(
        self,
        user_id: str,
        role: Optional[str] = None,
        limit: int = 500,
    ) -> Optional[list[dict[str, Any]]]:
        """Retrieve full active client records accessible to user_id in Aurora.

        Returns:
            None: user/tenancy identity is NOT present in Aurora (permits Supabase fallback).
            []: user exists in Aurora but has zero accessible active clients (DO NOT fall back).
            [dict, ...]: user exists in Aurora and has accessible active clients (DO NOT fall back).

        - Admin/Owner: All active clients where firm_owner_id == user_id, ordered by added_at DESC.
        - Staff: Only active clients where assigned_to == user_id, ordered by added_at DESC.
        Enforces a bounded limit of maximum 500 records.
        """
        uid = str(user_id or "").strip()
        if not uid:
            return None

        # Check if this user has a pending tenancy synchronization failure
        try:
            from app.services.tenancy_sync import (
                is_tenancy_sync_pending,
                reconcile_user_tenancy_from_supabase,
            )
            if is_tenancy_sync_pending(uid):
                reconciled = reconcile_user_tenancy_from_supabase(uid)
                if not reconciled:
                    # Reconciliation failed (Aurora down or error): permit Supabase fallback
                    return None
        except Exception as sync_exc:
            _log.warning("Tenancy sync check failed for %s: %s", uid, sync_exc)

        # Bounded limit: minimum 1, maximum 500
        safe_limit = min(max(1, int(limit if limit is not None else 500)), 500)

        with self._get_session() as session:
            # 1. Check user existence in Aurora user_profiles
            user_stmt = (
                select(UserProfile.id, UserProfile.role)
                .where(UserProfile.id == uid)
                .limit(1)
            )
            user_row = session.execute(user_stmt).first()
            if user_row is None:
                return None  # User absent from Aurora: permit Supabase fallback

            resolved_role = (role or user_row[1] or "admin").strip().lower()

            # 2. Query accessible clients in Aurora
            if resolved_role in ("admin", "owner") or not resolved_role:
                stmt = (
                    select(ClientGSTIN)
                    .where(
                        ClientGSTIN.firm_owner_id == uid,
                        ClientGSTIN.is_active.is_(True),
                    )
                    .order_by(ClientGSTIN.added_at.desc())
                    .limit(safe_limit)
                )
            else:
                stmt = (
                    select(ClientGSTIN)
                    .where(
                        ClientGSTIN.assigned_to == uid,
                        ClientGSTIN.is_active.is_(True),
                    )
                    .order_by(ClientGSTIN.added_at.desc())
                    .limit(safe_limit)
                )

            clients = session.scalars(stmt).all()
            return [client.to_dict() for client in clients]

    def get_client_gstin(self, client_gstin_id: str) -> Optional[dict[str, Any]]:
        """Fetch client GSTIN record by primary key."""
        cid = str(client_gstin_id or "").strip()
        if not cid:
            return None

        with self._get_session() as session:
            stmt = select(ClientGSTIN).where(ClientGSTIN.id == cid)
            client = session.scalar(stmt)
            if client is None:
                return None
            return client.to_dict()

    def client_exists(self, client_gstin_id: str) -> bool:
        """Check whether a client GSTIN record exists in Aurora."""
        cid = str(client_gstin_id or "").strip()
        if not cid:
            return False

        with self._get_session() as session:
            stmt = select(ClientGSTIN.id).where(ClientGSTIN.id == cid).limit(1)
            return session.execute(stmt).first() is not None

    def create_client(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or restore client GSTIN record in Aurora.

        FK Safe: Automatically ensures parent UserProfile rows exist for
        firm_owner_id and assigned_to to avoid ForeignKeyViolation errors.
        """
        cid = str(data.get("id") or "").strip()
        foid = str(data.get("firm_owner_id") or "").strip()
        gstin = str(data.get("gstin") or "").strip().upper()
        assigned_to = str(data.get("assigned_to") or "").strip() or None

        valid_cols = {c.name for c in ClientGSTIN.__table__.columns}
        with self._get_session() as session:
            if foid:
                self._ensure_user_profile_exists(session, foid, role="admin")
            if assigned_to:
                self._ensure_user_profile_exists(session, assigned_to, role="staff")

            # Check if client already exists by ID or (firm_owner_id, gstin)
            client = None
            if cid:
                client = session.scalar(select(ClientGSTIN).where(ClientGSTIN.id == cid))
            if client is None and foid and gstin:
                client = session.scalar(
                    select(ClientGSTIN).where(
                        ClientGSTIN.firm_owner_id == foid,
                        ClientGSTIN.gstin == gstin,
                    )
                )

            if client is not None:
                for k, v in data.items():
                    if k in valid_cols and k != "id":
                        if k in ("added_at", "gstn_token_expiry"):
                            setattr(client, k, _parse_datetime(v))
                        else:
                            setattr(client, k, v)
                if "is_active" not in data:
                    client.is_active = True
                session.commit()
                return client.to_dict()
            else:
                attrs: dict[str, Any] = {}
                for k, v in data.items():
                    if k in valid_cols:
                        if k in ("added_at", "gstn_token_expiry"):
                            attrs[k] = _parse_datetime(v)
                        else:
                            attrs[k] = v
                if "id" not in attrs or not attrs["id"]:
                    attrs["id"] = cid or str(uuid.uuid4())
                if "is_active" not in attrs:
                    attrs["is_active"] = True
                client = ClientGSTIN(**attrs)
                session.add(client)
                session.commit()
                return client.to_dict()

    def update_client(
        self, client_id: str, fields: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Update fields for a client GSTIN in Aurora."""
        cid = str(client_id or "").strip()
        if not cid:
            return None

        valid_cols = {c.name for c in ClientGSTIN.__table__.columns}
        with self._get_session() as session:
            client = session.scalar(select(ClientGSTIN).where(ClientGSTIN.id == cid))
            if client is None:
                return None
            assigned_to = fields.get("assigned_to")
            if assigned_to:
                self._ensure_user_profile_exists(
                    session, str(assigned_to).strip(), role="staff"
                )
            for k, v in fields.items():
                if k in valid_cols and k != "id":
                    if k in ("added_at", "gstn_token_expiry"):
                        setattr(client, k, _parse_datetime(v))
                    else:
                        setattr(client, k, v)
            session.commit()
            return client.to_dict()

    def soft_delete_client(self, client_id: str) -> bool:
        """Soft-delete client in Aurora by setting is_active = False."""
        cid = str(client_id or "").strip()
        if not cid:
            return False

        with self._get_session() as session:
            client = session.scalar(select(ClientGSTIN).where(ClientGSTIN.id == cid))
            if client is None:
                return False
            client.is_active = False
            session.commit()
            return True

    def verify_firm_ownership(
        self, client_gstin_id: str, firm_owner_id: str
    ) -> Optional[bool]:
        """Verify whether a client belongs to the specified firm owner.

        Returns:
            True: Client exists and belongs to firm_owner_id.
            False: Client exists but belongs to a different firm (AUTHORIZATION DENIAL).
            None: Client not found in Aurora (infrastructure miss).
        """
        cid = str(client_gstin_id or "").strip()
        foid = str(firm_owner_id or "").strip()
        if not cid or not foid:
            return None

        with self._get_session() as session:
            stmt = select(ClientGSTIN.firm_owner_id).where(ClientGSTIN.id == cid).limit(1)
            res = session.execute(stmt).first()
            if res is None:
                return None
            return str(res[0]).strip() == foid

    def verify_staff_assignment(
        self, client_gstin_id: str, staff_user_id: str
    ) -> Optional[bool]:
        """Verify whether a client is assigned to the specified staff user.

        Returns:
            True: Client exists, is active, and assigned to staff_user_id.
            False: Client exists but is not assigned to staff_user_id (AUTHORIZATION DENIAL).
            None: Client not found in Aurora (infrastructure miss).
        """
        cid = str(client_gstin_id or "").strip()
        uid = str(staff_user_id or "").strip()
        if not cid or not uid:
            return None

        with self._get_session() as session:
            stmt = select(ClientGSTIN.assigned_to, ClientGSTIN.is_active).where(
                ClientGSTIN.id == cid
            ).limit(1)
            res = session.execute(stmt).first()
            if res is None:
                return None
            assigned_to, is_active = res
            if not is_active:
                return False
            return str(assigned_to or "").strip() == uid

    def get_firm_owner_for_client(self, client_gstin_id: str) -> Optional[str]:
        """Return firm_owner_id for a client GSTIN in Aurora, or None if client not in Aurora."""
        cid = str(client_gstin_id or "").strip()
        if not cid:
            return None

        with self._get_session() as session:
            stmt = select(ClientGSTIN.firm_owner_id).where(ClientGSTIN.id == cid).limit(1)
            res = session.execute(stmt).first()
            if res is None:
                return None
            return str(res[0])

    def user_can_access_firm(self, user_id: str, firm_owner_id: str) -> Optional[bool]:
        """Check whether user has access to a firm (as owner, active team member, or assigned staff).

        Returns:
            True: Confirmed access in Aurora.
            None: Not confirmed in Aurora (allows fallback to Supabase during migration).
        """
        uid = str(user_id or "").strip()
        foid = str(firm_owner_id or "").strip()
        if not uid or not foid:
            return False
        if uid == foid:
            return True

        with self._get_session() as session:
            # 1. Active team membership
            tm_stmt = select(TeamMember.id).where(
                TeamMember.firm_owner_id == foid,
                TeamMember.member_user_id == uid,
                TeamMember.is_active.is_(True),
            ).limit(1)
            if session.execute(tm_stmt).first() is not None:
                return True

            # 2. Active client assignment
            cg_stmt = select(ClientGSTIN.id).where(
                ClientGSTIN.firm_owner_id == foid,
                ClientGSTIN.assigned_to == uid,
                ClientGSTIN.is_active.is_(True),
            ).limit(1)
            if session.execute(cg_stmt).first() is not None:
                return True

        return None

    def user_in_same_firm(
        self, user_id: str, firm_owner_id: str, client_gstin_id: str
    ) -> Optional[bool]:
        """Check whether user is firm owner or assigned to the specified client.

        Returns:
            True: Authorized (is owner or assigned to active client).
            False: Client exists in Aurora but access is denied (belongs to different firm,
                   unassigned staff, or inactive).
            None: Client not found in Aurora (infrastructure miss, allow Supabase fallback).
        """
        uid = str(user_id or "").strip()
        foid = str(firm_owner_id or "").strip()
        cid = str(client_gstin_id or "").strip()
        if not uid or not foid:
            return False
        if not cid:
            return uid == foid

        with self._get_session() as session:
            stmt = select(
                ClientGSTIN.firm_owner_id,
                ClientGSTIN.assigned_to,
                ClientGSTIN.is_active,
            ).where(ClientGSTIN.id == cid).limit(1)
            res = session.execute(stmt).first()
            if res is None:
                return None  # Client not in Aurora

            client_owner_id, assigned_to, is_active = res
            if not is_active:
                return False
            if str(client_owner_id).strip() != foid:
                return False
            if uid == foid:
                return True
            return str(assigned_to or "").strip() == uid


# ── Global Tenancy Repository Management ─────────────────────────────────────

_tenancy_repo: Optional[AuroraTenancyRepository] = None


def get_tenancy_repository() -> Optional[AuroraTenancyRepository]:
    """Return the global AuroraTenancyRepository if Aurora is enabled/configured, else None."""
    global _tenancy_repo
    if _tenancy_repo is not None:
        return _tenancy_repo

    from app.aurora import get_aurora_database_url, is_aurora_enabled

    if is_aurora_enabled() or get_aurora_database_url():
        try:
            _tenancy_repo = AuroraTenancyRepository()
            return _tenancy_repo
        except Exception as exc:
            _log.warning("Failed to initialize AuroraTenancyRepository: %s", type(exc).__name__)
            return None

    return None


def set_tenancy_repository(repo: Optional[AuroraTenancyRepository]) -> None:
    """Explicitly set or reset the tenancy repository (for tests)."""
    global _tenancy_repo
    _tenancy_repo = repo
