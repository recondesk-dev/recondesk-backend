"""Client Review, Consent and Filing Authorization Service (Phase 3.3).

Enforces explicit, cryptographically verifiable client authorization for return filings:
- Time-limited, single-purpose access tokens hashed via SHA-256 (plaintext tokens are never stored).
- Immutable client review and authorization audit log.
- Explicit signatory declaration (name, designation, contact, consent version).
- Cryptographic figures binding: Alteration of return figures revokes consent and raises HTTP 409.
- Server-side gate enforcement on filing operations (GSTR-1, GSTR-3B, and Celery workers).
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.models.roles import is_admin_or_partner, is_manager_or_above, is_writer_or_above, normalize_role
from app.services.firm_access import assert_client_gstin_in_firm
from app.services.pre_filing_validator import compute_figures_digest

_log = logging.getLogger(__name__)

CLIENT_AUTH_TABLE = "client_filing_authorizations"
CLIENT_AUDIT_TABLE = "client_authorization_audit_trail"

DEFAULT_CONSENT_TEXT_VERSION = "v1.0"
STANDARD_CONSENT_DECLARATION = (
    "I hereby confirm that I have reviewed the return figures, tax liabilities, input tax credits, "
    "and net payable amounts presented. I declare that the figures are true, correct, and complete to "
    "the best of my knowledge, and I explicitly authorize the CA firm to file this GST return with the GSTN."
)


class ClientAuthStatus(str, Enum):
    PENDING = "PENDING"
    VIEWED = "VIEWED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ClientAuthAction(str, Enum):
    REQUEST_CREATED = "REQUEST_CREATED"
    LINK_VIEWED = "LINK_VIEWED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    CONSENT_INVALIDATED_FIGURES_ALTERED = "CONSENT_INVALIDATED_FIGURES_ALTERED"


def normalize_return_type(rt: str) -> str:
    """Canonicalize return type (e.g. gstr-1 -> GSTR-1)."""
    raw = (rt or "").strip().upper()
    if raw in ("GSTR-1", "GSTR1", "GSTR_1"):
        return "GSTR-1"
    if raw in ("GSTR-3B", "GSTR3B", "GSTR_3B"):
        return "GSTR-3B"
    if raw in ("GSTR-4", "GSTR4", "GSTR_4"):
        return "GSTR-4"
    if raw in ("GSTR-9", "GSTR9", "GSTR_9"):
        return "GSTR-9"
    if raw in ("GSTR-9C", "GSTR9C", "GSTR_9C"):
        return "GSTR-9C"
    return raw


def hash_review_token(raw_token: str) -> str:
    """Compute deterministic SHA-256 digest of a plaintext review token."""
    clean = (raw_token or "").strip()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def generate_review_token() -> tuple[str, str]:
    """Generate a high-entropy url-safe token and its SHA-256 hash.
    
    Returns (raw_token, token_hash). Only token_hash is stored in the database.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_review_token(raw_token)
    return raw_token, token_hash


@dataclass
class ClientAuthorizationData:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    return_type: str
    status: ClientAuthStatus
    token_hash: str
    figures_digest: str
    figures_summary: dict[str, Any] = field(default_factory=dict)
    signatory_name: Optional[str] = None
    signatory_designation: Optional[str] = None
    signatory_contact: Optional[str] = None
    consent_text_version: str = DEFAULT_CONSENT_TEXT_VERSION
    consent_declaration: Optional[str] = None
    identity_verification_method: str = "self_declaration"
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    authorized_at: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None
    revoked_by: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = ""
    expires_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "firm_id": self.firm_id,
            "client_gstin_id": self.client_gstin_id,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "status": self.status.value if isinstance(self.status, ClientAuthStatus) else str(self.status),
            "token_hash": self.token_hash,
            "figures_digest": self.figures_digest,
            "figures_summary": self.figures_summary or {},
            "signatory_name": self.signatory_name,
            "signatory_designation": self.signatory_designation,
            "signatory_contact": self.signatory_contact,
            "consent_text_version": self.consent_text_version,
            "consent_declaration": self.consent_declaration,
            "identity_verification_method": self.identity_verification_method or "self_declaration",
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "authorized_at": self.authorized_at,
            "rejected_at": self.rejected_at,
            "rejection_reason": self.rejection_reason,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
            "revoked_by": self.revoked_by,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "updated_at": self.updated_at,
        }

    def to_client_view_dict(self) -> dict[str, Any]:
        """Client-safe view (omitting internal CA IDs and staff identifiers)."""
        return {
            "id": self.id,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "status": self.status.value if isinstance(self.status, ClientAuthStatus) else str(self.status),
            "figures_digest": self.figures_digest,
            "figures_summary": self.figures_summary or {},
            "signatory_name": self.signatory_name,
            "signatory_designation": self.signatory_designation,
            "consent_text_version": self.consent_text_version,
            "consent_declaration": self.consent_declaration or STANDARD_CONSENT_DECLARATION,
            "identity_verification_method": self.identity_verification_method or "self_declaration",
            "authorized_at": self.authorized_at,
            "rejected_at": self.rejected_at,
            "rejection_reason": self.rejection_reason,
            "expires_at": self.expires_at,
        }


@dataclass
class ClientAuthAuditEntryData:
    id: str
    authorization_id: str
    firm_id: str
    client_gstin_id: Optional[str]
    gstin: str
    period: str
    return_type: str
    action: str
    from_status: Optional[str]
    to_status: str
    actor_type: str  # 'ca_user', 'client', 'system'
    actor_id: Optional[str]
    actor_name: str
    figures_digest: str
    client_ip: Optional[str]
    user_agent: Optional[str]
    notes: str
    metadata: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "authorization_id": self.authorization_id,
            "firm_id": self.firm_id,
            "client_gstin_id": self.client_gstin_id,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "action": self.action,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "figures_digest": self.figures_digest,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "notes": self.notes,
            "metadata": self.metadata or {},
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Thread-safe in-memory store for isolated unit tests
# ---------------------------------------------------------------------------
class _ClientAuthStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._authorizations: dict[str, ClientAuthorizationData] = {}  # key: (firm_id, client_gstin_id, period, return_type)
        self._by_token_hash: dict[str, ClientAuthorizationData] = {}
        self._by_id: dict[str, ClientAuthorizationData] = {}
        self._audit_trail: list[ClientAuthAuditEntryData] = []

    def _key(self, firm_id: str, client_gstin_id: str, period: str, return_type: str) -> str:
        return f"{firm_id}:{client_gstin_id}:{period.strip()}:{normalize_return_type(return_type)}"

    def get_by_key(self, firm_id: str, client_gstin_id: str, period: str, return_type: str) -> Optional[ClientAuthorizationData]:
        with self._lock:
            key = self._key(firm_id, client_gstin_id, period, return_type)
            return self._authorizations.get(key)

    def get_by_token_hash(self, token_hash: str) -> Optional[ClientAuthorizationData]:
        with self._lock:
            return self._by_token_hash.get(token_hash)

    def get_by_id(self, auth_id: str) -> Optional[ClientAuthorizationData]:
        with self._lock:
            return self._by_id.get(auth_id)

    def put(self, auth: ClientAuthorizationData) -> None:
        with self._lock:
            key = self._key(auth.firm_id, auth.client_gstin_id, auth.period, auth.return_type)
            self._authorizations[key] = auth
            self._by_token_hash[auth.token_hash] = auth
            self._by_id[auth.id] = auth

    def add_audit(self, entry: ClientAuthAuditEntryData) -> None:
        with self._lock:
            self._audit_trail.append(entry)

    def get_audit_trail(self, auth_id: str) -> list[ClientAuthAuditEntryData]:
        with self._lock:
            return [e for e in self._audit_trail if e.authorization_id == auth_id]

    def clear(self) -> None:
        with self._lock:
            self._authorizations.clear()
            self._by_token_hash.clear()
            self._by_id.clear()
            self._audit_trail.clear()


_client_store = _ClientAuthStore()


def _is_test_runner(sb: Any) -> bool:
    """Check if sb is a mock or running in test mode without real database."""
    if sb is None:
        return True
    try:
        from unittest.mock import Mock
        if isinstance(sb, Mock):
            return True
    except ImportError:
        pass
    if hasattr(sb, "_mock_return_value") or hasattr(sb, "mock_calls"):
        return True
    if getattr(sb, "is_real_db", None) is True or getattr(sb, "force_db", None) is True:
        return False
    from app.config import get_settings
    env = (get_settings().APP_ENV or "").lower().strip()
    if env == "test" or os.environ.get("RECONDESK_ENV", "").lower() == "test":
        return True
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_figures_summary(figures_payload: Any, return_type: str) -> dict[str, Any]:
    """Extract structured, client-friendly figure summaries for review."""
    if not isinstance(figures_payload, dict):
        return {}
    summary: dict[str, Any] = {}
    norm_rt = normalize_return_type(return_type)

    if norm_rt == "GSTR-1":
        summary["total_taxable_value"] = float(figures_payload.get("total_taxable_value", 0.0) or 0.0)
        summary["total_tax"] = float(figures_payload.get("total_tax", 0.0) or 0.0)
        summary["igst"] = float(figures_payload.get("igst", 0.0) or 0.0)
        summary["cgst"] = float(figures_payload.get("cgst", 0.0) or 0.0)
        summary["sgst"] = float(figures_payload.get("sgst", 0.0) or 0.0)
        summary["cess"] = float(figures_payload.get("cess", 0.0) or 0.0)
        summary["invoice_count"] = int(figures_payload.get("invoice_count", 0) or 0)
        # Detailed table counts if present
        for tbl in ("b2b", "b2cl", "b2cs", "exp", "cdnr", "cdnur", "hsn"):
            if tbl in figures_payload and isinstance(figures_payload[tbl], (list, dict)):
                val = figures_payload[tbl]
                summary[f"{tbl}_count"] = len(val) if isinstance(val, list) else len(val.keys())

    elif norm_rt == "GSTR-3B":
        summary["outward_taxable_value"] = float(figures_payload.get("outward_taxable_value", figures_payload.get("total_taxable_value", 0.0)) or 0.0)
        summary["outward_tax"] = float(figures_payload.get("outward_tax", figures_payload.get("total_tax", 0.0)) or 0.0)
        summary["eligible_itc"] = float(figures_payload.get("eligible_itc", figures_payload.get("itc_available", 0.0)) or 0.0)
        summary["ineligible_itc"] = float(figures_payload.get("ineligible_itc", 0.0) or 0.0)
        summary["net_tax_payable"] = float(figures_payload.get("net_tax_payable", figures_payload.get("tax_payable", 0.0)) or 0.0)
        summary["rcm_tax"] = float(figures_payload.get("rcm_tax", 0.0) or 0.0)
        summary["igst"] = float(figures_payload.get("igst", 0.0) or 0.0)
        summary["cgst"] = float(figures_payload.get("cgst", 0.0) or 0.0)
        summary["sgst"] = float(figures_payload.get("sgst", 0.0) or 0.0)
        summary["cess"] = float(figures_payload.get("cess", 0.0) or 0.0)

    else:
        # Generic summary
        for k in ("total_taxable_value", "total_tax", "tax_payable", "tax_paid"):
            if k in figures_payload:
                summary[k] = figures_payload[k]

    return summary


def _persist_client_authorization(sb: Any, auth: ClientAuthorizationData) -> None:
    """Save authorization record to in-memory store and database."""
    _client_store.put(auth)
    if sb is not None and not _is_test_runner(sb):
        try:
            payload = auth.to_dict()
            # Upsert into PostgreSQL / Aurora
            sb.table(CLIENT_AUTH_TABLE).upsert(payload).execute()
        except Exception as exc:
            _log.error("Failed to persist client authorization to database: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "DB_PERSISTENCE_FAILED", "message": "Failed to persist client authorization record."},
            ) from exc


def _record_client_audit_entry(
    sb: Any,
    *,
    authorization: ClientAuthorizationData,
    action: str,
    from_status: Optional[str],
    to_status: str,
    actor_type: str,
    actor_id: Optional[str] = None,
    actor_name: str = "",
    figures_digest: Optional[str] = None,
    notes: str = "",
    metadata: Optional[dict[str, Any]] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ClientAuthAuditEntryData:
    """Record an immutable client authorization audit entry."""
    entry = ClientAuthAuditEntryData(
        id=str(uuid4()),
        authorization_id=authorization.id,
        firm_id=authorization.firm_id,
        client_gstin_id=authorization.client_gstin_id,
        gstin=authorization.gstin,
        period=authorization.period,
        return_type=authorization.return_type,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        figures_digest=figures_digest or authorization.figures_digest,
        client_ip=client_ip,
        user_agent=user_agent,
        notes=notes,
        metadata=metadata or {},
        created_at=_now_iso(),
    )
    _client_store.add_audit(entry)

    if sb is not None and not _is_test_runner(sb):
        try:
            sb.table(CLIENT_AUDIT_TABLE).insert(entry.to_dict()).execute()
        except Exception as exc:
            _log.error("Failed to persist client audit entry to database: %s", exc)
    return entry


# ---------------------------------------------------------------------------
# Public & CA Service Functions
# ---------------------------------------------------------------------------

def create_authorization_request(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    figures_payload: Any,
    actor: dict[str, Any],
    expires_in_hours: int = 48,
) -> tuple[ClientAuthorizationData, str]:
    """CA user creates a client return authorization request and generates a review token.
    
    Returns (authorization_record, raw_token). The raw_token is returned ONLY here to allow
    sharing the review link, and is never stored in persistent storage.
    """
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    actor_role = normalize_role(actor.get("role"))
    if not is_writer_or_above(actor_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_ROLE_FOR_AUTHORIZATION_REQUEST",
                "message": f"Role '{actor_role}' is not authorized to create client review requests.",
            },
        )

    norm_rt = normalize_return_type(return_type)
    clean_gstin = gstin.strip().upper()
    clean_period = period.strip()
    figures_digest = compute_figures_digest(figures_payload)
    figures_summary = _extract_figures_summary(figures_payload, norm_rt)

    # Clamping expiry duration between 1 hour and 7 days (168h)
    clamped_hours = max(1, min(168, int(expires_in_hours or 48)))
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=clamped_hours)).isoformat()
    now_iso = now.isoformat()

    raw_token, token_hash = generate_review_token()
    actor_id = str(actor.get("id") or "")
    actor_name = str(actor.get("full_name") or actor.get("email") or "CA User")

    # Check for existing request to record transition and supersede if figures altered
    existing = get_latest_client_authorization(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=clean_period,
        return_type=norm_rt,
    )
    from_status = existing.status.value if existing else None
    if existing and existing.status in (ClientAuthStatus.PENDING, ClientAuthStatus.VIEWED, ClientAuthStatus.AUTHORIZED):
        if existing.figures_digest != figures_digest:
            from_st = existing.status.value
            existing.status = ClientAuthStatus.REVOKED
            existing.revocation_reason = "Superseded: Revised return figures prepared by CA"
            existing.revoked_at = now_iso
            existing.revoked_by = actor_id
            existing.updated_at = now_iso
            _persist_client_authorization(sb, existing)
            _record_client_audit_entry(
                sb,
                authorization=existing,
                action=ClientAuthAction.REVOKED.value,
                from_status=from_st,
                to_status=ClientAuthStatus.REVOKED.value,
                actor_type="ca_user",
                actor_id=actor_id,
                actor_name=actor_name,
                notes="Older authorization request revoked because revised return figures were prepared.",
                metadata={"revocation_reason": "Superseded by revised figures", "new_digest": figures_digest},
            )

    auth = ClientAuthorizationData(
        id=str(uuid4()),
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=clean_gstin,
        period=clean_period,
        return_type=norm_rt,
        status=ClientAuthStatus.PENDING,
        token_hash=token_hash,
        figures_digest=figures_digest,
        figures_summary=figures_summary,
        consent_text_version=DEFAULT_CONSENT_TEXT_VERSION,
        created_by=actor_id,
        created_at=now_iso,
        expires_at=expires_at,
        updated_at=now_iso,
    )

    _persist_client_authorization(sb, auth)
    _record_client_audit_entry(
        sb,
        authorization=auth,
        action=ClientAuthAction.REQUEST_CREATED.value,
        from_status=from_status,
        to_status=ClientAuthStatus.PENDING.value,
        actor_type="ca_user",
        actor_id=actor_id,
        actor_name=actor_name,
        notes=f"Generated client authorization request valid for {clamped_hours} hours.",
        metadata={"expires_in_hours": clamped_hours, "figures_digest": figures_digest},
    )
    return auth, raw_token


def get_latest_client_authorization(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    period: str,
    return_type: str,
) -> Optional[ClientAuthorizationData]:
    """Retrieve the latest client authorization record for a specific filing."""
    norm_rt = normalize_return_type(return_type)
    cached = _client_store.get_by_key(firm_id, client_gstin_id, period, norm_rt)
    if cached:
        return cached

    if sb is not None and not _is_test_runner(sb):
        try:
            res = (
                sb.table(CLIENT_AUTH_TABLE)
                .select("*")
                .eq("firm_id", firm_id)
                .eq("client_gstin_id", client_gstin_id)
                .eq("period", period.strip())
                .eq("return_type", norm_rt)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res.data and len(res.data) > 0:
                row = res.data[0]
                auth = _row_to_model(row)
                _client_store.put(auth)
                return auth
        except Exception as exc:
            _log.warning("Database lookup failed for client authorization: %s", exc)
    return None


def get_authorization_by_token(
    sb: Any,
    raw_token: str,
    *,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ClientAuthorizationData:
    """Retrieve authorization record by plaintext token, auto-marking VIEWED on first access."""
    if not raw_token or not raw_token.strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AUTHORIZATION_TOKEN_NOT_FOUND", "message": "Authorization token is missing or invalid."},
        )

    token_hash = hash_review_token(raw_token)
    auth = _client_store.get_by_token_hash(token_hash)

    if not auth and sb is not None and not _is_test_runner(sb):
        try:
            res = sb.table(CLIENT_AUTH_TABLE).select("*").eq("token_hash", token_hash).limit(1).execute()
            if res.data and len(res.data) > 0:
                auth = _row_to_model(res.data[0])
                _client_store.put(auth)
        except Exception as exc:
            _log.warning("Failed to lookup token hash in DB: %s", exc)

    if not auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AUTHORIZATION_TOKEN_NOT_FOUND", "message": "Invalid or expired review authorization link."},
        )

    # Check Revocation
    if auth.status == ClientAuthStatus.REVOKED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "AUTHORIZATION_TOKEN_REVOKED",
                "message": f"This review link has been revoked by your CA firm: {auth.revocation_reason or 'No reason provided.'}",
            },
        )

    # Check Expiration
    now = datetime.now(timezone.utc)
    try:
        exp_dt = datetime.fromisoformat(auth.expires_at.replace("Z", "+00:00"))
    except Exception:
        exp_dt = now

    if now > exp_dt:
        if auth.status in (ClientAuthStatus.PENDING, ClientAuthStatus.VIEWED):
            from_st = auth.status.value
            auth.status = ClientAuthStatus.EXPIRED
            auth.updated_at = _now_iso()
            _persist_client_authorization(sb, auth)
            _record_client_audit_entry(
                sb,
                authorization=auth,
                action=ClientAuthAction.EXPIRED.value,
                from_status=from_st,
                to_status=ClientAuthStatus.EXPIRED.value,
                actor_type="system",
                actor_name="Expiration Checker",
                notes="Review token reached its expiration time limit.",
                client_ip=client_ip,
                user_agent=user_agent,
            )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "AUTHORIZATION_TOKEN_EXPIRED",
                "message": "This return review link has expired. Please contact your CA firm to request a new link.",
            },
        )

    # Review-link click alone must NEVER count as authorization.
    # It transitions PENDING -> VIEWED on first review visit.
    if auth.status == ClientAuthStatus.PENDING:
        auth.status = ClientAuthStatus.VIEWED
        auth.client_ip = client_ip
        auth.user_agent = user_agent
        auth.updated_at = _now_iso()
        _persist_client_authorization(sb, auth)
        _record_client_audit_entry(
            sb,
            authorization=auth,
            action=ClientAuthAction.LINK_VIEWED.value,
            from_status=ClientAuthStatus.PENDING.value,
            to_status=ClientAuthStatus.VIEWED.value,
            actor_type="client",
            actor_name="Client Reviewer",
            notes="Client opened the return review portal.",
            client_ip=client_ip,
            user_agent=user_agent,
        )

    return auth


def submit_client_authorization(
    sb: Any,
    raw_token: str,
    *,
    signatory_name: str,
    signatory_designation: str,
    signatory_contact: str,
    consent_text_version: str = DEFAULT_CONSENT_TEXT_VERSION,
    consent_declaration: Optional[str] = None,
    expected_figures_digest: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ClientAuthorizationData:
    """Client explicitly authorizes return filing with self-declared signatory identity and legal affirmation."""
    auth = get_authorization_by_token(sb, raw_token, client_ip=client_ip, user_agent=user_agent)

    if auth.status == ClientAuthStatus.AUTHORIZED:
        return auth

    if auth.status == ClientAuthStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "RETURN_ALREADY_REJECTED",
                "message": "This return review was previously rejected. A new authorization link is required.",
            },
        )

    # Stale digest verification
    if expected_figures_digest and expected_figures_digest.strip() != auth.figures_digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FIGURES_DIGEST_MISMATCH",
                "message": "The return figures presented in review do not match the authorized return digest.",
            },
        )

    # Validate identity fields
    clean_name = (signatory_name or "").strip()
    clean_desig = (signatory_designation or "").strip()
    clean_contact = (signatory_contact or "").strip()

    if len(clean_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SIGNATORY_NAME", "message": "Full legal name of the authorized signatory is required."},
        )
    if len(clean_desig) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SIGNATORY_DESIGNATION", "message": "Signatory designation or role is required."},
        )
    if len(clean_contact) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SIGNATORY_CONTACT", "message": "A valid signatory phone or email is required."},
        )

    from_st = auth.status.value
    now_iso = _now_iso()

    auth.status = ClientAuthStatus.AUTHORIZED
    auth.signatory_name = clean_name
    auth.signatory_designation = clean_desig
    auth.signatory_contact = clean_contact
    auth.consent_text_version = consent_text_version or DEFAULT_CONSENT_TEXT_VERSION
    auth.consent_declaration = (consent_declaration or STANDARD_CONSENT_DECLARATION).strip()
    auth.identity_verification_method = "self_declaration"
    auth.authorized_at = now_iso
    auth.client_ip = client_ip
    auth.user_agent = user_agent
    auth.updated_at = now_iso

    _persist_client_authorization(sb, auth)
    _record_client_audit_entry(
        sb,
        authorization=auth,
        action=ClientAuthAction.AUTHORIZED.value,
        from_status=from_st,
        to_status=ClientAuthStatus.AUTHORIZED.value,
        actor_type="client",
        actor_name=f"{clean_name} ({clean_desig})",
        notes=f"Explicit filing authorization submitted by {clean_name} ({clean_desig}) via self-declaration.",
        client_ip=client_ip,
        user_agent=user_agent,
        metadata={
            "signatory_name": clean_name,
            "signatory_designation": clean_desig,
            "signatory_contact": clean_contact,
            "consent_version": auth.consent_text_version,
            "figures_digest": auth.figures_digest,
            "identity_verification_method": "self_declaration",
            "identity_assurance_level": "self_declared_with_ip_audit",
            "is_otp_verified": False,
        },
    )
    return auth


def reject_client_authorization(
    sb: Any,
    raw_token: str,
    *,
    rejection_reason: str,
    signatory_name: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ClientAuthorizationData:
    """Client explicitly rejects return figures with mandatory rejection reason."""
    auth = get_authorization_by_token(sb, raw_token, client_ip=client_ip, user_agent=user_agent)

    reason = (rejection_reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "REJECTION_REASON_REQUIRED",
                "message": "A detailed rejection reason (minimum 5 characters) is required.",
            },
        )

    from_st = auth.status.value
    now_iso = _now_iso()
    clean_name = (signatory_name or "").strip() or "Client Signatory"

    auth.status = ClientAuthStatus.REJECTED
    auth.rejected_at = now_iso
    auth.rejection_reason = reason
    auth.client_ip = client_ip
    auth.user_agent = user_agent
    auth.updated_at = now_iso

    _persist_client_authorization(sb, auth)
    _record_client_audit_entry(
        sb,
        authorization=auth,
        action=ClientAuthAction.REJECTED.value,
        from_status=from_st,
        to_status=ClientAuthStatus.REJECTED.value,
        actor_type="client",
        actor_name=clean_name,
        notes=f"Return figures rejected by client: {reason}",
        client_ip=client_ip,
        user_agent=user_agent,
        metadata={"rejection_reason": reason},
    )
    return auth


def revoke_authorization_request(
    sb: Any,
    *,
    authorization_id: str,
    firm_id: str,
    revocation_reason: str,
    actor: dict[str, Any],
) -> ClientAuthorizationData:
    """CA Manager or Partner revokes an active authorization request."""
    actor_role = normalize_role(actor.get("role"))
    if not is_manager_or_above(actor_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_ROLE_FOR_REVOCATION",
                "message": f"Role '{actor_role}' is not authorized to revoke client authorizations. Manager or Partner required.",
            },
        )

    reason = (revocation_reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "REVOCATION_REASON_REQUIRED", "message": "A revocation reason is required."},
        )

    auth = _client_store.get_by_id(authorization_id)
    if not auth and sb is not None and not _is_test_runner(sb):
        try:
            res = sb.table(CLIENT_AUTH_TABLE).select("*").eq("id", authorization_id).eq("firm_id", firm_id).limit(1).execute()
            if res.data and len(res.data) > 0:
                auth = _row_to_model(res.data[0])
                _client_store.put(auth)
        except Exception as exc:
            _log.warning("Failed to lookup authorization by id: %s", exc)

    if not auth or auth.firm_id != firm_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AUTHORIZATION_NOT_FOUND", "message": "Client authorization request not found."},
        )

    if auth.status in (ClientAuthStatus.REVOKED, ClientAuthStatus.EXPIRED):
        return auth

    from_st = auth.status.value
    now_iso = _now_iso()
    actor_id = str(actor.get("id") or "")
    actor_name = str(actor.get("full_name") or actor.get("email") or "CA Reviewer")

    auth.status = ClientAuthStatus.REVOKED
    auth.revoked_at = now_iso
    auth.revocation_reason = reason
    auth.revoked_by = actor_id
    auth.updated_at = now_iso

    _persist_client_authorization(sb, auth)
    _record_client_audit_entry(
        sb,
        authorization=auth,
        action=ClientAuthAction.REVOKED.value,
        from_status=from_st,
        to_status=ClientAuthStatus.REVOKED.value,
        actor_type="ca_user",
        actor_id=actor_id,
        actor_name=actor_name,
        notes=f"Revoked by CA firm: {reason}",
        metadata={"revocation_reason": reason},
    )
    return auth


def assert_client_authorization_gate(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    current_figures_payload: Optional[Any] = None,
    require_authorization: Optional[bool] = None,
) -> Optional[ClientAuthorizationData]:
    """Enforce server-side client authorization gate prior to filing operations.
    
    1. If a client authorization request exists for this return, it MUST be AUTHORIZED.
    2. Verifies cryptographic figure binding. If figures were modified since authorization,
       consent is revoked and HTTP 409 is raised.
    3. If no authorization exists, checks firm policy: if firm policy mandates client authorization,
       blocks with HTTP 403.
    """
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    norm_rt = normalize_return_type(return_type)

    auth = get_latest_client_authorization(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )

    if auth is not None:
        # Check authorization status
        if auth.status != ClientAuthStatus.AUTHORIZED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "CLIENT_AUTHORIZATION_REQUIRED",
                    "message": f"Return filing requires explicit client authorization. Current authorization status is '{auth.status.value}'.",
                    "status": auth.status.value,
                    "authorization_id": auth.id,
                },
            )

        # Check expiration
        now = datetime.now(timezone.utc)
        try:
            exp_dt = datetime.fromisoformat(auth.expires_at.replace("Z", "+00:00"))
        except Exception:
            exp_dt = now

        if now > exp_dt:
            from_st = auth.status.value
            auth.status = ClientAuthStatus.EXPIRED
            auth.updated_at = _now_iso()
            _persist_client_authorization(sb, auth)
            _record_client_audit_entry(
                sb,
                authorization=auth,
                action=ClientAuthAction.EXPIRED.value,
                from_status=from_st,
                to_status=ClientAuthStatus.EXPIRED.value,
                actor_type="system",
                actor_name="Filing Safety Gate",
                notes=f"Client authorization expired prior to filing (expired: {auth.expires_at}).",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "CLIENT_AUTHORIZATION_EXPIRED",
                    "message": f"Client authorization expired on {auth.expires_at}. Renewed authorization required.",
                    "authorization_id": auth.id,
                },
            )

        # Cryptographic figures tamper binding check
        if current_figures_payload is not None and auth.figures_digest:
            curr_digest = compute_figures_digest(current_figures_payload)
            if curr_digest != auth.figures_digest:
                _log.warning(
                    "Client authorization stale figures detected for %s %s! Authorized: %s, Current: %s",
                    gstin, period, auth.figures_digest, curr_digest,
                )
                from_st = auth.status.value
                auth.status = ClientAuthStatus.REVOKED
                auth.signatory_name = None
                auth.signatory_designation = None
                auth.signatory_contact = None
                auth.authorized_at = None
                auth.revocation_reason = "Consent invalidated: Return figures altered after authorization"
                auth.revoked_at = _now_iso()
                auth.updated_at = _now_iso()

                _persist_client_authorization(sb, auth)
                _record_client_audit_entry(
                    sb,
                    authorization=auth,
                    action=ClientAuthAction.CONSENT_INVALIDATED_FIGURES_ALTERED.value,
                    from_status=from_st,
                    to_status=ClientAuthStatus.REVOKED.value,
                    actor_type="system",
                    actor_name="Filing Gate Figure Verifier",
                    figures_digest=curr_digest,
                    notes=f"Client authorization revoked because return figures changed (expected: {auth.figures_digest[:12]}..., current: {curr_digest[:12]}...).",
                    metadata={"authorized_digest": auth.figures_digest, "current_digest": curr_digest},
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "CLIENT_AUTHORIZATION_STALE_FIGURES_ALTERED",
                        "message": (
                            f"Return figures were modified after client authorization was granted. "
                            f"Current digest ({curr_digest[:16]}...) does not match authorized digest ({auth.figures_digest[:16]}...). "
                            f"A renewed client review and authorization is required prior to filing."
                        ),
                        "authorized_digest": auth.figures_digest,
                        "current_digest": curr_digest,
                        "authorization_id": auth.id,
                    },
                )
        return auth

    # No authorization record exists
    if require_authorization is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CLIENT_AUTHORIZATION_REQUIRED",
                "message": "Filing requires prior client review and authorization.",
            },
        )

    # Check firm policy
    try:
        from app.services.filing_override_service import get_firm_filing_policy
        policy = get_firm_filing_policy(sb, firm_id)
        if policy and getattr(policy, "require_client_authorization", False) is True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "CLIENT_AUTHORIZATION_REQUIRED",
                    "message": "Firm filing policy mandates client authorization prior to GSTN return submission.",
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        _log.warning("Could not evaluate firm filing policy for client authorization: %s", exc)

    return None


def get_client_authorization_history(
    sb: Any,
    *,
    authorization_id: str,
    firm_id: str,
) -> list[dict[str, Any]]:
    """Retrieve tenant-scoped audit trail for a client authorization."""
    entries = _client_store.get_audit_trail(authorization_id)
    if entries:
        return [e.to_dict() for e in entries if e.firm_id == firm_id]

    if sb is not None and not _is_test_runner(sb):
        try:
            res = (
                sb.table(CLIENT_AUDIT_TABLE)
                .select("*")
                .eq("authorization_id", authorization_id)
                .eq("firm_id", firm_id)
                .order("created_at", desc=False)
                .execute()
            )
            if res.data:
                return res.data
        except Exception as exc:
            _log.warning("Audit trail lookup failed in database: %s", exc)
    return []


def _row_to_model(row: dict[str, Any]) -> ClientAuthorizationData:
    """Map DB row dict to ClientAuthorizationData."""
    raw_status = row.get("status") or "PENDING"
    try:
        status_enum = ClientAuthStatus(raw_status)
    except ValueError:
        status_enum = ClientAuthStatus.PENDING

    return ClientAuthorizationData(
        id=str(row.get("id")),
        firm_id=str(row.get("firm_id")),
        client_gstin_id=str(row.get("client_gstin_id")),
        gstin=str(row.get("gstin")),
        period=str(row.get("period")),
        return_type=normalize_return_type(str(row.get("return_type"))),
        status=status_enum,
        token_hash=str(row.get("token_hash")),
        figures_digest=str(row.get("figures_digest") or ""),
        figures_summary=row.get("figures_summary") or {},
        signatory_name=row.get("signatory_name"),
        signatory_designation=row.get("signatory_designation"),
        signatory_contact=row.get("signatory_contact"),
        consent_text_version=str(row.get("consent_text_version") or DEFAULT_CONSENT_TEXT_VERSION),
        consent_declaration=row.get("consent_declaration"),
        identity_verification_method=str(row.get("identity_verification_method") or "self_declaration"),
        client_ip=row.get("client_ip"),
        user_agent=row.get("user_agent"),
        authorized_at=row.get("authorized_at"),
        rejected_at=row.get("rejected_at"),
        rejection_reason=row.get("rejection_reason"),
        revoked_at=row.get("revoked_at"),
        revocation_reason=row.get("revocation_reason"),
        revoked_by=str(row.get("revoked_by")) if row.get("revoked_by") else None,
        created_by=str(row.get("created_by")) if row.get("created_by") else None,
        created_at=str(row.get("created_at") or ""),
        expires_at=str(row.get("expires_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )
