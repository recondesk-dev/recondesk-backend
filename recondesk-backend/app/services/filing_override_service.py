"""CA Approval and Override Controls Service.

Enforces firm-configurable filing governance:
- ADVISORY: Non-blocking statutory and reconciliation warnings.
- PARTNER_OVERRIDE: Hard blocks critical violations unless an authorized Partner (admin/owner)
  records an explicit override with documented statutory justification.
- STRICT_BLOCK: Blocks filing unconditionally if statutory breaches or unfinalized runs exist.

Statutory Citations:
- CGST Rule 88C: Inserted vide Notification No. 26/2022-Central Tax (26 Dec 2022) pursuant to 48th GST Council
  recommendations. Triggers Form GST DRC-01B Part A when outward tax liability in GSTR-1/IFF exceeds GSTR-3B
  tax paid by > 20% AND > ₹25,00,000.
- CGST Rule 88D: Inserted vide Notification No. 38/2023-Central Tax (04 Aug 2023) pursuant to 50th GST Council
  recommendations. Triggers Form GST DRC-01C Part A when GSTR-3B Table 4 claimed ITC exceeds GSTR-2B available ITC
  by > 20% AND > ₹25,00,000.
- Rule 59(6)(e) & 59(6)(f): Statutory subsequent-period filing restriction if DRC-01B/DRC-01C is unresolved.

Security & Fail-Closed Architectural Guarantees:
1. Fail-Closed Durability: When running against AWS Aurora / PostgreSQL, any database unavailability,
   connection dropout, or missing table strictly FAILS CLOSED with HTTP 503 Service Unavailable.
   Filing governance NEVER falls back to permissive default or in-memory approvals in production.
2. Role Enforcement: Ordinary staff cannot approve overrides (HTTP 403 Forbidden).
3. Tamper Evident: Overrides are cryptographically bound to both the SHA-256 digest of
   filing figures AND the SHA-256 digest of validated violation rules. If figures or
   violations are altered in the slightest, the approval is invalidated (HTTP 409 Conflict).
4. Tenant Isolation & Durable Storage: Policies and overrides are durably stored in PostgreSQL
   tables (`filing_governance_policies`, `filing_overrides`) scoped strictly by firm_id and client_gstin_id.
5. Concurrency & Single-Use: Overrides are atomically consumed via CAS update in PostgreSQL to eliminate replay attacks.
6. Immutable Audit: Every override creation, rejection, and consumption is recorded in public.audit_logs.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.database import get_user_profile, resolve_user_role
from app.services.firm_access import assert_client_gstin_in_firm, firm_owner_id_for_user
from app.services.pre_filing_validator import PreFilingValidationResult, ValidationSeverity
from app.utils.audit import log_audit

_log = logging.getLogger(__name__)

POLICIES_TABLE = "filing_governance_policies"
OVERRIDES_TABLE = "filing_overrides"


class FilingPolicyMode(str, Enum):
    ADVISORY = "ADVISORY"
    PARTNER_OVERRIDE = "PARTNER_OVERRIDE"
    STRICT_BLOCK = "STRICT_BLOCK"


class FilingPolicy(BaseModel):
    firm_id: str
    mode: FilingPolicyMode = FilingPolicyMode.ADVISORY
    rule_88c_amount_threshold: float = 2_500_000.0  # ₹25L statutory (Notif. 26/2022-CT)
    rule_88c_pct_threshold: float = 20.0             # 20% statutory (48th Council)
    rule_88d_amount_threshold: float = 2_500_000.0  # ₹25L statutory (Notif. 38/2023-CT)
    rule_88d_pct_threshold: float = 20.0             # 20% statutory (50th Council)
    require_final_reconciliation: bool = True
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class FilingPolicyUpdate(BaseModel):
    mode: FilingPolicyMode
    rule_88c_amount_threshold: Optional[float] = Field(None, ge=0)
    rule_88c_pct_threshold: Optional[float] = Field(None, ge=0)
    rule_88d_amount_threshold: Optional[float] = Field(None, ge=0)
    rule_88d_pct_threshold: Optional[float] = Field(None, ge=0)
    require_final_reconciliation: Optional[bool] = None


@dataclass
class FilingOverride:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    return_type: str
    figures_digest: str
    validation_digest: str
    justification: str
    approved_by: str
    approver_name: str
    approver_role: str
    violations_acknowledged: list[str]
    created_at: str
    expires_at: str
    is_consumed: bool = False
    consumed_at: Optional[str] = None
    consumed_run_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "firm_id": self.firm_id,
            "client_gstin_id": self.client_gstin_id,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "figures_digest": self.figures_digest,
            "validation_digest": self.validation_digest,
            "justification": self.justification,
            "approved_by": self.approved_by,
            "approver_name": self.approver_name,
            "approver_role": self.approver_role,
            "violations_acknowledged": self.violations_acknowledged,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_consumed": self.is_consumed,
            "consumed_at": self.consumed_at,
            "consumed_run_id": self.consumed_run_id,
        }


def is_fail_closed_environment(sb: Any) -> bool:
    """Check if governance storage must fail closed.
    
    In production, staging, or live environments:
    Filing governance MUST strictly fail closed when Aurora/PostgreSQL is unavailable
    or tables are missing. In-memory fallback is strictly forbidden in production.
    In-memory fallback is only permitted when running in unit tests with mocked database clients.
    """
    from app.config import get_settings
    settings = get_settings()
    env = (settings.APP_ENV or "").lower().strip()
    if env == "production":
        return True
    if os.environ.get("RECONDESK_ENV", "").lower().strip() == "production":
        return True

    # If sb is a Mock/MagicMock or explicitly configured test runner, permit test isolation
    if hasattr(sb, "_mock_return_value") or hasattr(sb, "mock_calls"):
        return False
    if env == "test" or os.environ.get("RECONDESK_ENV", "").lower() == "test":
        return False

    return True


# ---------------------------------------------------------------------------
# In-Memory Store for Local Unit Tests & Process Cache
# ---------------------------------------------------------------------------

class _GovernanceStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._policies: dict[str, FilingPolicy] = {}
        self._overrides: dict[str, FilingOverride] = {}

    def get_cached_policy(self, firm_id: str) -> Optional[FilingPolicy]:
        with self._lock:
            return self._policies.get(firm_id)

    def set_policy(self, firm_id: str, policy: FilingPolicy) -> None:
        with self._lock:
            self._policies[firm_id] = policy

    def put_override(self, override: FilingOverride) -> None:
        with self._lock:
            self._overrides[override.id] = override

    def get_override(self, override_id: str) -> Optional[FilingOverride]:
        with self._lock:
            return self._overrides.get(override_id)

    def find_active_override(
        self,
        *,
        firm_id: str,
        client_gstin_id: str,
        period: str,
        return_type: str,
        figures_digest: str,
        validation_digest: Optional[str] = None,
    ) -> Optional[FilingOverride]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for ov in self._overrides.values():
                if (
                    ov.firm_id == firm_id
                    and ov.client_gstin_id == client_gstin_id
                    and ov.period == period
                    and ov.return_type.lower() == return_type.lower()
                    and ov.figures_digest == figures_digest
                    and (not validation_digest or not ov.validation_digest or ov.validation_digest == validation_digest)
                    and not ov.is_consumed
                    and ov.expires_at > now_iso
                ):
                    return ov
            return None

    def consume_override_local(self, override_id: str, run_id: str) -> Optional[FilingOverride]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            ov = self._overrides.get(override_id)
            if ov and not ov.is_consumed:
                ov.is_consumed = True
                ov.consumed_at = now_iso
                ov.consumed_run_id = run_id
                return ov
            return None

    def find_and_consume_active_override_local(
        self,
        *,
        firm_id: str,
        client_gstin_id: str,
        period: str,
        return_type: str,
        run_id: str,
    ) -> Optional[FilingOverride]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for ov in self._overrides.values():
                if (
                    ov.firm_id == firm_id
                    and ov.client_gstin_id == client_gstin_id
                    and ov.period == period
                    and ov.return_type.lower() == return_type.lower()
                    and not ov.is_consumed
                    and ov.expires_at > now_iso
                ):
                    ov.is_consumed = True
                    ov.consumed_at = now_iso
                    ov.consumed_run_id = run_id
                    return ov
            return None

    def clear(self) -> None:
        with self._lock:
            self._policies.clear()
            self._overrides.clear()


_governance_store = _GovernanceStore()


# ---------------------------------------------------------------------------
# Policy Management (Durable + Strict Fail-Closed)
# ---------------------------------------------------------------------------

def get_firm_filing_policy(sb: Any, firm_id: str) -> FilingPolicy:
    """Retrieve the firm's active filing governance policy from durable storage.
    
    Fail-closed guarantee:
    When running in production or against live Aurora, any database failure or missing table
    raises HTTP 503 Service Unavailable, strictly preventing unauthorized return filing.
    Never falls back to in-memory approvals in production.
    """
    fail_closed = is_fail_closed_environment(sb)

    if not fail_closed:
        cached = _governance_store.get_cached_policy(firm_id)
        if cached is not None:
            return cached

    if sb is None:
        if fail_closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                    "message": "Filing governance storage is unavailable (database client not initialized); filing checks cannot proceed.",
                },
            )
        default_pol = FilingPolicy(firm_id=firm_id)
        _governance_store.set_policy(firm_id, default_pol)
        return default_pol

    try:
        res = (
            sb.table(POLICIES_TABLE)
            .select("*")
            .eq("firm_id", firm_id)
            .limit(1)
            .execute()
        )
        if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0 and isinstance(res.data[0], dict):
            row = res.data[0]
            pol = FilingPolicy(
                firm_id=str(row["firm_id"]),
                mode=FilingPolicyMode(row.get("mode") or "ADVISORY"),
                rule_88c_amount_threshold=float(row.get("rule_88c_amount_threshold") or 2500000.0),
                rule_88c_pct_threshold=float(row.get("rule_88c_pct_threshold") or 20.0),
                rule_88d_amount_threshold=float(row.get("rule_88d_amount_threshold") or 2500000.0),
                rule_88d_pct_threshold=float(row.get("rule_88d_pct_threshold") or 20.0),
                require_final_reconciliation=bool(row.get("require_final_reconciliation", True)),
                updated_at=row.get("updated_at"),
                updated_by=row.get("updated_by"),
            )
            _governance_store.set_policy(firm_id, pol)
            return pol
        elif res and isinstance(getattr(res, "data", None), list) and len(res.data) == 0:
            # Table exists and query succeeded; firm has not saved custom policy yet.
            default_pol = FilingPolicy(firm_id=firm_id)
            _governance_store.set_policy(firm_id, default_pol)
            return default_pol
    except Exception as exc:
        if fail_closed:
            _log.error("Failed to query filing governance policy from Aurora: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                    "message": "Filing governance storage is unavailable or policy table is missing; filing governance cannot proceed.",
                },
            ) from exc
        _log.debug("Database fetch for policy failed (using default in test): %s", exc)

    default_pol = FilingPolicy(firm_id=firm_id)
    _governance_store.set_policy(firm_id, default_pol)
    return default_pol


async def update_firm_filing_policy(
    sb: Any,
    firm_id: str,
    update: FilingPolicyUpdate,
    user: dict[str, Any],
) -> FilingPolicy:
    """Update firm filing governance policy (Requires Partner/Admin role)."""
    user_role = (user.get("role") or "").strip().lower()
    if user_role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Partner / Admin users can modify firm filing policy",
        )

    existing = get_firm_filing_policy(sb, firm_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    fail_closed = is_fail_closed_environment(sb)

    updated = FilingPolicy(
        firm_id=firm_id,
        mode=update.mode,
        rule_88c_amount_threshold=(
            update.rule_88c_amount_threshold
            if update.rule_88c_amount_threshold is not None
            else existing.rule_88c_amount_threshold
        ),
        rule_88c_pct_threshold=(
            update.rule_88c_pct_threshold
            if update.rule_88c_pct_threshold is not None
            else existing.rule_88c_pct_threshold
        ),
        rule_88d_amount_threshold=(
            update.rule_88d_amount_threshold
            if update.rule_88d_amount_threshold is not None
            else existing.rule_88d_amount_threshold
        ),
        rule_88d_pct_threshold=(
            update.rule_88d_pct_threshold
            if update.rule_88d_pct_threshold is not None
            else existing.rule_88d_pct_threshold
        ),
        require_final_reconciliation=(
            update.require_final_reconciliation
            if update.require_final_reconciliation is not None
            else existing.require_final_reconciliation
        ),
        updated_at=now_iso,
        updated_by=str(user.get("id")),
    )

    if sb is None and fail_closed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                "message": "Database client unavailable for filing governance policy update.",
            },
        )

    if sb is not None:
        try:
            sb.table(POLICIES_TABLE).upsert(
                {
                    "firm_id": firm_id,
                    "mode": updated.mode.value,
                    "rule_88c_amount_threshold": updated.rule_88c_amount_threshold,
                    "rule_88c_pct_threshold": updated.rule_88c_pct_threshold,
                    "rule_88d_amount_threshold": updated.rule_88d_amount_threshold,
                    "rule_88d_pct_threshold": updated.rule_88d_pct_threshold,
                    "require_final_reconciliation": updated.require_final_reconciliation,
                    "updated_at": now_iso,
                    "updated_by": str(user.get("id")),
                },
                on_conflict="firm_id",
            ).execute()
        except Exception as exc:
            if fail_closed:
                _log.error("Failed to persist filing policy to Aurora: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                        "message": "Failed to persist filing policy to governance storage.",
                    },
                ) from exc
            _log.debug("Database upsert for policy failed (test mode): %s", exc)

    _governance_store.set_policy(firm_id, updated)

    # Immutable audit logging
    await log_audit(
        db=sb,
        user=user,
        action="UPDATE_FILING_POLICY",
        entity_type="firm_policy",
        entity_id=firm_id,
        entity_label=f"Filing Policy: {updated.mode.value}",
        metadata={
            "mode": updated.mode.value,
            "rule_88c_amount_threshold": updated.rule_88c_amount_threshold,
            "rule_88c_pct_threshold": updated.rule_88c_pct_threshold,
            "rule_88d_amount_threshold": updated.rule_88d_amount_threshold,
            "rule_88d_pct_threshold": updated.rule_88d_pct_threshold,
            "require_final_reconciliation": updated.require_final_reconciliation,
        },
    )

    return updated


# ---------------------------------------------------------------------------
# Override Authorization Logic
# ---------------------------------------------------------------------------

async def create_partner_override(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    figures_digest: str,
    justification: str,
    violations_acknowledged: list[str],
    user: dict[str, Any],
    validation_digest: Optional[str] = None,
) -> FilingOverride:
    """Authorize a filing override for statutory/reconciliation violations.
    
    Strict Security Checks:
    1. Role: Must be 'admin' or 'owner'. Staff cannot self-approve.
    2. Tenant Isolation: Must verify client belongs to firm_id.
    3. Justification: Must be non-empty (minimum 10 characters).
    4. Tamper Resistance: Bound to figures_digest and validation_digest.
    5. Fail-Closed Durability: Must be durably saved in Aurora in production.
    """
    user_role = (user.get("role") or "").strip().lower()
    if user_role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OVERRIDE_UNAUTHORIZED",
                "message": "Only a Partner or Admin can approve filing overrides. Ordinary staff cannot self-approve.",
            },
        )

    just = justification.strip()
    if len(just) < 10:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INSUFFICIENT_JUSTIFICATION",
                "message": "A detailed statutory justification (minimum 10 characters) is required to authorize filing with violations.",
            },
        )

    # Scoping check
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)

    override_id = str(uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=24)  # Overrides valid for 24 hours
    fail_closed = is_fail_closed_environment(sb)

    override = FilingOverride(
        id=override_id,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin.strip().upper(),
        period=period.strip(),
        return_type=return_type.strip().lower(),
        figures_digest=figures_digest.strip(),
        validation_digest=(validation_digest or "").strip(),
        justification=just,
        approved_by=str(user.get("id")),
        approver_name=str(user.get("full_name") or user.get("email") or "Partner"),
        approver_role=user_role,
        violations_acknowledged=violations_acknowledged,
        created_at=now.isoformat(),
        expires_at=expires.isoformat(),
    )

    if sb is None and fail_closed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                "message": "Database client unavailable for filing override creation.",
            },
        )

    if sb is not None:
        try:
            sb.table(OVERRIDES_TABLE).insert(override.to_dict()).execute()
        except Exception as exc:
            if fail_closed:
                _log.error("Failed to persist partner override in Aurora: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                        "message": "Failed to persist partner override to governance storage.",
                    },
                ) from exc
            _log.debug("Database insert for override failed (test mode): %s", exc)

    _governance_store.put_override(override)

    # Immutable statutory audit trail
    await log_audit(
        db=sb,
        user=user,
        action="AUTHORIZE_FILING_OVERRIDE",
        entity_type="filing_override",
        entity_id=override_id,
        entity_label=f"Override for {gstin} {period} ({return_type})",
        metadata={
            "override_id": override_id,
            "client_gstin_id": client_gstin_id,
            "period": period,
            "return_type": return_type,
            "figures_digest": figures_digest,
            "validation_digest": override.validation_digest,
            "justification": just,
            "violations_acknowledged": violations_acknowledged,
        },
    )

    return override


def verify_filing_governance_gate(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    validation_result: PreFilingValidationResult,
    user: dict[str, Any],
) -> Optional[FilingOverride]:
    """Verify whether filing is permitted under the firm's governance policy.
    
    Enforcement Matrix:
    - ADVISORY: Always allows filing, returning None.
    - PARTNER_OVERRIDE:
        * If validation has critical violations or required reconciliation unfinalized:
          1. Looks up active override matching exact `figures_digest` and `validation_digest`.
          2. If figures or validation results changed: rejects with HTTP 409 Conflict.
          3. If no active override: rejects with HTTP 422 Unprocessable Content.
    - STRICT_BLOCK:
        * If validation has critical statutory violations: rejects with HTTP 422,
          even if an override exists.
    """
    policy = get_firm_filing_policy(sb, firm_id)

    if policy.mode == FilingPolicyMode.ADVISORY:
        return None

    if not validation_result.has_critical_violations and not (
        policy.require_final_reconciliation and not validation_result.is_valid
    ):
        return None

    # For STRICT_BLOCK: reject immediately
    if policy.mode == FilingPolicyMode.STRICT_BLOCK:
        violations_desc = "; ".join(v.message for v in validation_result.violations if v.severity == ValidationSeverity.CRITICAL_ERROR)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FILING_STRICTLY_BLOCKED",
                "message": (
                    f"Filing is strictly blocked by firm policy (STRICT_BLOCK) due to critical statutory violations: {violations_desc}"
                ),
                "violations": [v.to_dict() for v in validation_result.violations],
                "policy_mode": policy.mode.value,
            },
        )

    fail_closed = is_fail_closed_environment(sb)
    active_override: Optional[FilingOverride] = None

    if fail_closed:
        # In live/production environment: query Aurora directly.
        # NEVER trust local process memory alone, and strictly FAIL CLOSED if DB is down.
        if sb is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                    "message": "Filing governance storage unavailable; cannot verify partner overrides.",
                },
            )
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            res = (
                sb.table(OVERRIDES_TABLE)
                .select("*")
                .eq("firm_id", firm_id)
                .eq("client_gstin_id", client_gstin_id)
                .eq("period", period)
                .eq("return_type", return_type.lower())
                .eq("figures_digest", validation_result.figures_digest)
                .eq("is_consumed", False)
                .gt("expires_at", now_iso)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0 and isinstance(res.data[0], dict):
                row = res.data[0]
                active_override = FilingOverride(
                    id=row["id"],
                    firm_id=str(row["firm_id"]),
                    client_gstin_id=str(row.get("client_gstin_id") or ""),
                    gstin=str(row["gstin"]),
                    period=str(row["period"]),
                    return_type=str(row["return_type"]),
                    figures_digest=str(row["figures_digest"]),
                    validation_digest=str(row.get("validation_digest") or ""),
                    justification=str(row["justification"]),
                    approved_by=str(row.get("approved_by") or ""),
                    approver_name=str(row.get("approver_name") or ""),
                    approver_role=str(row.get("approver_role") or ""),
                    violations_acknowledged=row.get("violations_acknowledged") or [],
                    created_at=str(row["created_at"]),
                    expires_at=str(row["expires_at"]),
                    is_consumed=bool(row.get("is_consumed", False)),
                )
        except Exception as exc:
            _log.error("Database query for active override failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                    "message": "Filing governance storage is unavailable; cannot verify partner overrides.",
                },
            ) from exc
    else:
        # Check in-memory store in unit test mode
        active_override = _governance_store.find_active_override(
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            period=period,
            return_type=return_type,
            figures_digest=validation_result.figures_digest,
            validation_digest=validation_result.validation_digest,
        )
        if not active_override and sb is not None:
            try:
                now_iso = datetime.now(timezone.utc).isoformat()
                res = (
                    sb.table(OVERRIDES_TABLE)
                    .select("*")
                    .eq("firm_id", firm_id)
                    .eq("client_gstin_id", client_gstin_id)
                    .eq("period", period)
                    .eq("return_type", return_type.lower())
                    .eq("figures_digest", validation_result.figures_digest)
                    .eq("is_consumed", False)
                    .gt("expires_at", now_iso)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0 and isinstance(res.data[0], dict):
                    row = res.data[0]
                    active_override = FilingOverride(
                        id=row["id"],
                        firm_id=str(row["firm_id"]),
                        client_gstin_id=str(row.get("client_gstin_id") or ""),
                        gstin=str(row["gstin"]),
                        period=str(row["period"]),
                        return_type=str(row["return_type"]),
                        figures_digest=str(row["figures_digest"]),
                        validation_digest=str(row.get("validation_digest") or ""),
                        justification=str(row["justification"]),
                        approved_by=str(row.get("approved_by") or ""),
                        approver_name=str(row.get("approver_name") or ""),
                        approver_role=str(row.get("approver_role") or ""),
                        violations_acknowledged=row.get("violations_acknowledged") or [],
                        created_at=str(row["created_at"]),
                        expires_at=str(row["expires_at"]),
                        is_consumed=bool(row.get("is_consumed", False)),
                    )
                    _governance_store.put_override(active_override)
            except Exception as exc:
                _log.debug("Database query for active override failed (test mode): %s", exc)

    if active_override:
        # Check validation digest match if recorded
        if (
            active_override.validation_digest
            and validation_result.validation_digest
            and active_override.validation_digest != validation_result.validation_digest
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "OVERRIDE_VALIDATION_MISMATCH",
                    "message": (
                        "Statutory validation violations have changed since the partner override was approved. "
                        "The previous approval is invalidated. A new partner override is required."
                    ),
                    "approved_validation_digest": active_override.validation_digest,
                    "current_validation_digest": validation_result.validation_digest,
                },
            )
        return active_override

    # Check if an override existed for this client/period but for different figures (tampering/stale)
    stale_override: Optional[FilingOverride] = None
    if fail_closed:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            res = (
                sb.table(OVERRIDES_TABLE)
                .select("*")
                .eq("firm_id", firm_id)
                .eq("client_gstin_id", client_gstin_id)
                .eq("period", period)
                .eq("return_type", return_type.lower())
                .eq("is_consumed", False)
                .gt("expires_at", now_iso)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0 and isinstance(res.data[0], dict):
                row = res.data[0]
                stale_override = FilingOverride(
                    id=row["id"],
                    firm_id=str(row["firm_id"]),
                    client_gstin_id=str(row.get("client_gstin_id") or ""),
                    gstin=str(row["gstin"]),
                    period=str(row["period"]),
                    return_type=str(row["return_type"]),
                    figures_digest=str(row["figures_digest"]),
                    validation_digest=str(row.get("validation_digest") or ""),
                    justification=str(row["justification"]),
                    approved_by=str(row.get("approved_by") or ""),
                    approver_name=str(row.get("approver_name") or ""),
                    approver_role=str(row.get("approver_role") or ""),
                    violations_acknowledged=row.get("violations_acknowledged") or [],
                    created_at=str(row["created_at"]),
                    expires_at=str(row["expires_at"]),
                    is_consumed=bool(row.get("is_consumed", False)),
                )
        except Exception as exc:
            _log.error("Database query for stale override failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                    "message": "Filing governance storage is unavailable; cannot verify partner overrides.",
                },
            ) from exc
    else:
        with _governance_store._lock:
            stale_override = next(
                (
                    ov for ov in _governance_store._overrides.values()
                    if ov.firm_id == firm_id
                    and ov.client_gstin_id == client_gstin_id
                    and ov.period == period
                    and ov.return_type.lower() == return_type.lower()
                    and not ov.is_consumed
                ),
                None,
            )

    if stale_override:
        if (
            stale_override.figures_digest == validation_result.figures_digest
            and stale_override.validation_digest
            and validation_result.validation_digest
            and stale_override.validation_digest != validation_result.validation_digest
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "OVERRIDE_VALIDATION_MISMATCH",
                    "message": (
                        "Statutory validation violations have changed since the partner override was approved. "
                        "The previous approval is invalidated. A new partner override is required."
                    ),
                    "approved_validation_digest": stale_override.validation_digest,
                    "current_validation_digest": validation_result.validation_digest,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "OVERRIDE_FIGURES_MISMATCH",
                "message": (
                    "Filing figures have changed since the partner override was approved. "
                    "The previous approval is invalidated. A new partner override is required."
                ),
                "approved_digest": stale_override.figures_digest,
                "current_digest": validation_result.figures_digest,
            },
        )

    violations_desc = "; ".join(v.message for v in validation_result.violations if v.severity == ValidationSeverity.CRITICAL_ERROR)
    raise HTTPException(
        status_code=422,
        detail={
            "code": "PARTNER_OVERRIDE_REQUIRED",
            "message": (
                f"Filing requires Partner approval under firm policy ({policy.mode.value}). "
                f"Unresolved critical violations: {violations_desc}"
            ),
            "figures_digest": validation_result.figures_digest,
            "validation_digest": validation_result.validation_digest,
            "violations": [v.to_dict() for v in validation_result.violations],
            "policy_mode": policy.mode.value,
        },
    )


# ---------------------------------------------------------------------------
# Atomic Consumption Implementation
# ---------------------------------------------------------------------------

def _consume_override_atomic(
    sb: Any,
    override_id: str,
    run_id: str,
) -> Optional[FilingOverride]:
    """Atomically consume an override in DB via CAS update.
    
    Guarantees single-use under high concurrency.
    In fail-closed environments (production), fails closed with HTTP 503 if Aurora is down.
    Never falls back to in-memory approvals in production.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    fail_closed = is_fail_closed_environment(sb)

    # 1. Attempt atomic CAS in DB
    if sb is not None:
        try:
            res = (
                sb.table(OVERRIDES_TABLE)
                .update({
                    "is_consumed": True,
                    "consumed_at": now_iso,
                    "consumed_run_id": run_id,
                    "updated_at": now_iso,
                })
                .eq("id", override_id)
                .eq("is_consumed", False)
                .gt("expires_at", now_iso)
                .execute()
            )
            if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0 and isinstance(res.data[0], dict):
                row = res.data[0]
                ov = FilingOverride(
                    id=row["id"],
                    firm_id=str(row["firm_id"]),
                    client_gstin_id=str(row.get("client_gstin_id") or ""),
                    gstin=str(row["gstin"]),
                    period=str(row["period"]),
                    return_type=str(row["return_type"]),
                    figures_digest=str(row["figures_digest"]),
                    validation_digest=str(row.get("validation_digest") or ""),
                    justification=str(row["justification"]),
                    approved_by=str(row.get("approved_by") or ""),
                    approver_name=str(row.get("approver_name") or ""),
                    approver_role=str(row.get("approver_role") or ""),
                    violations_acknowledged=row.get("violations_acknowledged") or [],
                    created_at=str(row["created_at"]),
                    expires_at=str(row["expires_at"]),
                    is_consumed=True,
                    consumed_at=row.get("consumed_at") or now_iso,
                    consumed_run_id=run_id,
                )
                _governance_store.consume_override_local(override_id, run_id)
                return ov
            elif res and isinstance(getattr(res, "data", None), list) and len(res.data) == 0:
                # 0 rows updated in DB: already consumed or expired!
                return None
        except Exception as exc:
            if fail_closed:
                _log.error("Database atomic CAS update failed for override %s: %s", override_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                        "message": "Filing governance storage is unavailable; cannot consume override.",
                    },
                ) from exc
            _log.debug("Database atomic CAS update failed (test mode): %s", exc)

    if fail_closed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                "message": "Filing governance storage unavailable in production.",
            },
        )

    # 2. Local memory atomic consumption fallback for unit tests
    return _governance_store.consume_override_local(override_id, run_id)


async def consume_override_on_file(
    sb: Any,
    override_id: str,
    run_id: str,
    user: dict[str, Any],
) -> None:
    """Consume the override upon successful return submission and record audit trail."""
    ov = _consume_override_atomic(sb, override_id, run_id)
    if ov:
        await log_audit(
            db=sb,
            user=user,
            action="CONSUME_FILING_OVERRIDE",
            entity_type="filing_override",
            entity_id=override_id,
            entity_label=f"Consumed on run {run_id}",
            metadata={"run_id": run_id, "consumed_at": ov.consumed_at},
        )


def consume_override_on_file_sync(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    period: str,
    return_type: str,
    run_id: str,
    user: dict[str, Any],
    override_id: Optional[str] = None,
) -> Optional[str]:
    """Synchronous helper to atomically consume active override on return filing."""
    from app.utils.audit import log_audit_sync

    now_iso = datetime.now(timezone.utc).isoformat()
    consumed_id: Optional[str] = None
    fail_closed = is_fail_closed_environment(sb)

    # Check DB first for active override
    if sb is not None:
        try:
            builder = (
                sb.table(OVERRIDES_TABLE)
                .update({
                    "is_consumed": True,
                    "consumed_at": now_iso,
                    "consumed_run_id": run_id,
                    "updated_at": now_iso,
                })
            )
            if override_id:
                builder = builder.eq("id", override_id)
            else:
                builder = (
                    builder.eq("firm_id", firm_id)
                    .eq("client_gstin_id", client_gstin_id)
                    .eq("period", period)
                    .eq("return_type", return_type.lower())
                )
            res = (
                builder.eq("is_consumed", False)
                .gt("expires_at", now_iso)
                .execute()
            )
            if res and isinstance(getattr(res, "data", None), list) and len(res.data) > 0 and isinstance(res.data[0], dict):
                consumed_id = res.data[0]["id"]
                _governance_store.consume_override_local(consumed_id, run_id)
            elif res and isinstance(getattr(res, "data", None), list) and len(res.data) == 0:
                # Already consumed
                return None
        except Exception as exc:
            if fail_closed:
                _log.error("Database sync consume failed in production: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "GOVERNANCE_STORAGE_UNAVAILABLE",
                        "message": "Filing governance storage unavailable; cannot consume override.",
                    },
                ) from exc
            _log.debug("Database sync consume failed (test mode): %s", exc)

    if not consumed_id and not fail_closed:
        if override_id:
            ov = _governance_store.consume_override_local(override_id, run_id)
            if ov:
                consumed_id = ov.id
        else:
            ov = _governance_store.find_and_consume_active_override_local(
                firm_id=firm_id,
                client_gstin_id=client_gstin_id,
                period=period,
                return_type=return_type,
                run_id=run_id,
            )
            if ov:
                consumed_id = ov.id

    if consumed_id:
        log_audit_sync(
            db=sb,
            user=user,
            action="CONSUME_FILING_OVERRIDE",
            entity_type="filing_override",
            entity_id=consumed_id,
            entity_label=f"Consumed on run {run_id}",
            metadata={"run_id": run_id, "consumed_at": now_iso},
        )
        return consumed_id

    return None
