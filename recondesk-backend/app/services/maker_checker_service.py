"""Maker-Checker Return Filing Approval Engine (Phase 3.2).

Enforces a durable, tamper-evident approval workflow for GSTR-1 and GSTR-3B filings:
- Lifecycle: DRAFT -> PREPARED -> UNDER_REVIEW -> APPROVED -> SAVED -> OFFSET_COMPLETE -> FILED (and REJECTED).
- Separation of duties: Preparers cannot approve their own return submissions (HTTP 403 CANNOT_APPROVE_OWN_SUBMISSION).
- Cryptographic binding: Approvals are bound to deterministic SHA-256 digests of return figures.
  Material figure modifications invalidate approval (HTTP 409 APPROVAL_STALE_FIGURES_ALTERED).
- Server-side gate enforcement: Intercepts Save, Offset, and File calls (both online and Celery workers).
- Immutable audit trail: Captures actor, role, timestamp, digests, notes, and rejection reasons.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.models.roles import is_admin_or_partner, is_manager_or_above, is_writer_or_above, normalize_role
from app.services.firm_access import assert_client_gstin_in_firm
from app.services.pre_filing_validator import compute_figures_digest

_log = logging.getLogger(__name__)

APPROVALS_TABLE = "return_filing_approvals"
AUDIT_TABLE = "return_approval_audit_trail"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SAVED = "SAVED"
    OFFSET_COMPLETE = "OFFSET_COMPLETE"
    FILED = "FILED"


class ApprovalAction(str, Enum):
    PREPARED = "PREPARED"
    SUBMITTED_FOR_REVIEW = "SUBMITTED_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SAVED = "SAVED"
    OFFSET_COMPLETED = "OFFSET_COMPLETED"
    FILED = "FILED"
    RESET = "RESET"


def normalize_return_type(rt: str) -> str:
    """Canonicalize return type (e.g. gstr-1, GSTR1 -> GSTR-1)."""
    raw = (rt or "").strip().upper()
    if raw in ("GSTR-1", "GSTR1", "GSTR_1"):
        return "GSTR-1"
    if raw in ("GSTR-1A", "GSTR1A", "GSTR_1A"):
        return "GSTR-1A"
    if raw in ("GSTR-3B", "GSTR3B", "GSTR_3B"):
        return "GSTR-3B"
    if raw in ("GSTR-4", "GSTR4", "GSTR_4"):
        return "GSTR-4"
    if raw in ("GSTR-9", "GSTR9", "GSTR_9"):
        return "GSTR-9"
    if raw in ("GSTR-9C", "GSTR9C", "GSTR_9C"):
        return "GSTR-9C"
    if raw in ("GSTR-7", "GSTR7", "GSTR_7"):
        return "GSTR-7"
    if raw in ("GSTR-8", "GSTR8", "GSTR_8"):
        return "GSTR-8"
    if raw in ("GSTR-6", "GSTR6", "GSTR_6"):
        return "GSTR-6"
    if raw in ("GSTR-5", "GSTR5", "GSTR_5"):
        return "GSTR-5"
    if raw in ("GSTR-5A", "GSTR5A", "GSTR_5A"):
        return "GSTR-5A"
    return raw


@dataclass
class ReturnApproval:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    return_type: str
    status: ApprovalStatus
    figures_digest: str = ""
    validation_digest: str = ""
    figures_summary: dict[str, Any] = field(default_factory=dict)
    preparer_id: Optional[str] = None
    preparer_name: str = ""
    preparer_role: str = ""
    prepared_at: Optional[str] = None
    submission_notes: str = ""
    approver_id: Optional[str] = None
    approver_name: str = ""
    approver_role: str = ""
    approved_at: Optional[str] = None
    approval_notes: str = ""
    rejected_by: Optional[str] = None
    rejected_by_name: str = ""
    rejected_by_role: str = ""
    rejected_at: Optional[str] = None
    rejection_reason: str = ""
    filing_run_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "firm_id": self.firm_id,
            "client_gstin_id": self.client_gstin_id,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "status": self.status.value if isinstance(self.status, ApprovalStatus) else str(self.status),
            "figures_digest": self.figures_digest,
            "validation_digest": self.validation_digest,
            "figures_summary": self.figures_summary or {},
            "preparer_id": self.preparer_id,
            "preparer_name": self.preparer_name,
            "preparer_role": self.preparer_role,
            "prepared_at": self.prepared_at,
            "submission_notes": self.submission_notes,
            "approver_id": self.approver_id,
            "approver_name": self.approver_name,
            "approver_role": self.approver_role,
            "approved_at": self.approved_at,
            "approval_notes": self.approval_notes,
            "rejected_by": self.rejected_by,
            "rejected_by_name": self.rejected_by_name,
            "rejected_by_role": self.rejected_by_role,
            "rejected_at": self.rejected_at,
            "rejection_reason": self.rejection_reason,
            "filing_run_id": self.filing_run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ApprovalAuditEntry:
    id: str
    approval_id: str
    firm_id: str
    client_gstin_id: Optional[str]
    gstin: str
    period: str
    return_type: str
    action: str
    from_status: Optional[str]
    to_status: str
    actor_id: Optional[str]
    actor_name: str
    actor_role: str
    figures_digest: str
    notes: str
    rejection_reason: str
    metadata: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "approval_id": self.approval_id,
            "firm_id": self.firm_id,
            "client_gstin_id": self.client_gstin_id,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "action": self.action,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "actor_role": self.actor_role,
            "figures_digest": self.figures_digest,
            "notes": self.notes,
            "rejection_reason": self.rejection_reason,
            "metadata": self.metadata or {},
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# In-Memory Store for Local Testing and Isolation
# ---------------------------------------------------------------------------
class _MakerCheckerStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._approvals: dict[str, ReturnApproval] = {}  # key: (firm_id, client_gstin_id, period, return_type)
        self._audit_trail: list[ApprovalAuditEntry] = []

    def _key(self, firm_id: str, client_gstin_id: str, period: str, return_type: str) -> str:
        return f"{firm_id}:{client_gstin_id}:{period.strip()}:{normalize_return_type(return_type)}"

    def get_approval(self, firm_id: str, client_gstin_id: str, period: str, return_type: str) -> Optional[ReturnApproval]:
        with self._lock:
            key = self._key(firm_id, client_gstin_id, period, return_type)
            return self._approvals.get(key)

    def put_approval(self, approval: ReturnApproval) -> None:
        with self._lock:
            key = self._key(approval.firm_id, approval.client_gstin_id, approval.period, approval.return_type)
            self._approvals[key] = approval

    def add_audit(self, entry: ApprovalAuditEntry) -> None:
        with self._lock:
            self._audit_trail.append(entry)

    def get_audit_trail(self, approval_id: str) -> list[ApprovalAuditEntry]:
        with self._lock:
            return [e for e in self._audit_trail if e.approval_id == approval_id]

    def clear(self) -> None:
        with self._lock:
            self._approvals.clear()
            self._audit_trail.clear()


_mc_store = _MakerCheckerStore()


def reset_maker_checker_store_for_testing() -> None:
    _mc_store.clear()

# Phase 3.2 Cutoff: Only runs created strictly before this UTC timestamp qualify as legacy
PHASE_3_2_CUTOFF_ISO = "2026-10-11T22:00:00+00:00"


def _is_genuinely_legacy_run(run_created_at: Optional[Union[str, datetime]]) -> bool:
    """Verify that a filing run was created strictly BEFORE the Phase 3.2 introduction cutoff."""
    if not run_created_at:
        return False
    try:
        if isinstance(run_created_at, datetime):
            dt = run_created_at
        else:
            raw = str(run_created_at).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff_dt = datetime.fromisoformat(PHASE_3_2_CUTOFF_ISO)
        return dt < cutoff_dt
    except Exception as exc:
        _log.warning("Could not parse run_created_at '%s' for legacy check: %s", run_created_at, exc)
        return False


def _is_test_runner(sb: Any) -> bool:
    """Check if sb is a mock/test runner or in test environment without real DB."""
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


def _extract_summary(figures_payload: Any) -> dict[str, Any]:
    """Extract high-level overview counts and totals from GSTR figures."""
    if not isinstance(figures_payload, dict):
        return {}
    summary: dict[str, Any] = {}
    if "total_taxable_value" in figures_payload:
        summary["taxable_value"] = figures_payload.get("total_taxable_value")
    if "total_tax" in figures_payload:
        summary["total_tax"] = figures_payload.get("total_tax")
    if "invoice_count" in figures_payload:
        summary["invoice_count"] = figures_payload.get("invoice_count")
    if "tx_pmt" in figures_payload:
        summary["has_tx_pmt"] = True
    return summary


# ---------------------------------------------------------------------------
# Core Service Functions
# ---------------------------------------------------------------------------

def get_return_approval(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    period: str,
    return_type: str,
) -> ReturnApproval:
    """Retrieve existing approval record or return a fresh DRAFT instance."""
    norm_rt = normalize_return_type(return_type)
    
    # 1. Check in-memory store
    cached = _mc_store.get_approval(firm_id, client_gstin_id, period, norm_rt)
    if cached:
        return cached

    # 2. Database lookup
    if sb is not None and not _is_test_runner(sb):
        try:
            res = (
                sb.table(APPROVALS_TABLE)
                .select("*")
                .eq("firm_id", firm_id)
                .eq("client_gstin_id", client_gstin_id)
                .eq("period", period.strip())
                .eq("return_type", norm_rt)
                .limit(1)
                .execute()
            )
            if res.data and len(res.data) > 0:
                row = res.data[0]
                approval = ReturnApproval(
                    id=str(row["id"]),
                    firm_id=str(row["firm_id"]),
                    client_gstin_id=str(row["client_gstin_id"]),
                    gstin=str(row["gstin"]),
                    period=str(row["period"]),
                    return_type=str(row["return_type"]),
                    status=ApprovalStatus(row["status"]),
                    figures_digest=str(row.get("figures_digest") or ""),
                    validation_digest=str(row.get("validation_digest") or ""),
                    figures_summary=row.get("figures_summary") or {},
                    preparer_id=row.get("preparer_id"),
                    preparer_name=str(row.get("preparer_name") or ""),
                    preparer_role=str(row.get("preparer_role") or ""),
                    prepared_at=row.get("prepared_at"),
                    submission_notes=str(row.get("submission_notes") or ""),
                    approver_id=row.get("approver_id"),
                    approver_name=str(row.get("approver_name") or ""),
                    approver_role=str(row.get("approver_role") or ""),
                    approved_at=row.get("approved_at"),
                    approval_notes=str(row.get("approval_notes") or ""),
                    rejected_by=row.get("rejected_by"),
                    rejected_by_name=str(row.get("rejected_by_name") or ""),
                    rejected_by_role=str(row.get("rejected_by_role") or ""),
                    rejected_at=row.get("rejected_at"),
                    rejection_reason=str(row.get("rejection_reason") or ""),
                    filing_run_id=row.get("filing_run_id"),
                    created_at=str(row.get("created_at") or ""),
                    updated_at=str(row.get("updated_at") or ""),
                )
                _mc_store.put_approval(approval)
                return approval
        except Exception as exc:
            _log.warning("Database lookup for approval failed: %s", exc)

    # 3. Not found: Return default DRAFT record
    now = _now_iso()
    draft = ReturnApproval(
        id=str(uuid4()),
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin="",
        period=period.strip(),
        return_type=norm_rt,
        status=ApprovalStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )
    return draft


def _persist_approval(sb: Any, approval: ReturnApproval) -> None:
    """Save approval to persistent DB and process memory."""
    _mc_store.put_approval(approval)
    if sb is not None and not _is_test_runner(sb):
        try:
            sb.table(APPROVALS_TABLE).upsert(
                approval.to_dict(),
                on_conflict="firm_id,client_gstin_id,period,return_type",
            ).execute()
        except Exception as exc:
            _log.error("Failed to upsert approval into DB: %s", exc)
            if not _is_test_runner(sb):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "APPROVAL_STORAGE_ERROR", "message": "Failed to persist return approval state."},
                ) from exc


def _record_audit_entry(
    sb: Any,
    *,
    approval: ReturnApproval,
    action: str,
    from_status: Optional[str],
    to_status: str,
    actor: dict[str, Any],
    notes: str = "",
    rejection_reason: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> ApprovalAuditEntry:
    """Log an immutable audit entry in the tenant audit trail."""
    entry = ApprovalAuditEntry(
        id=str(uuid4()),
        approval_id=approval.id,
        firm_id=approval.firm_id,
        client_gstin_id=approval.client_gstin_id,
        gstin=approval.gstin,
        period=approval.period,
        return_type=approval.return_type,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor_id=str(actor.get("id")) if actor.get("id") else None,
        actor_name=str(actor.get("full_name") or actor.get("email") or "User"),
        actor_role=normalize_role(actor.get("role")),
        figures_digest=approval.figures_digest,
        notes=notes,
        rejection_reason=rejection_reason,
        metadata=metadata or {},
        created_at=_now_iso(),
    )
    _mc_store.add_audit(entry)
    if sb is not None and not _is_test_runner(sb):
        try:
            sb.table(AUDIT_TABLE).insert(entry.to_dict()).execute()
        except Exception as exc:
            _log.error("Failed to record maker-checker audit trail: %s", exc)
    return entry


def prepare_return(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    figures_payload: Any,
    validation_digest: str = "",
    notes: str = "",
    actor: dict[str, Any],
    submit_for_review: bool = False,
) -> ReturnApproval:
    """Authorized preparer submits return figures for review.
    
    Computes deterministic SHA-256 digest of exact figures and binds them to the approval lifecycle.
    """
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    actor_role = normalize_role(actor.get("role"))
    if not is_writer_or_above(actor_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_ROLE_FOR_PREPARATION",
                "message": f"Role '{actor_role}' is not authorized to prepare returns.",
            },
        )

    norm_rt = normalize_return_type(return_type)
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )
    from_status = approval.status.value

    # Terminal state check: cannot re-prepare a filed return
    if approval.status == ApprovalStatus.FILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "RETURN_ALREADY_FILED", "message": "Return is already filed with GSTN."},
        )

    fig_digest = compute_figures_digest(figures_payload)
    now = _now_iso()
    approval.gstin = gstin.strip().upper()
    approval.figures_digest = fig_digest
    approval.validation_digest = (validation_digest or "").strip()
    approval.figures_summary = _extract_summary(figures_payload)
    approval.preparer_id = str(actor.get("id"))
    approval.preparer_name = str(actor.get("full_name") or actor.get("email") or "Preparer")
    approval.preparer_role = actor_role
    approval.prepared_at = now
    approval.submission_notes = notes.strip()
    approval.updated_at = now

    target_status = ApprovalStatus.UNDER_REVIEW if submit_for_review else ApprovalStatus.PREPARED
    approval.status = target_status
    _persist_approval(sb, approval)

    action = ApprovalAction.SUBMITTED_FOR_REVIEW.value if submit_for_review else ApprovalAction.PREPARED.value
    _record_audit_entry(
        sb,
        approval=approval,
        action=action,
        from_status=from_status,
        to_status=target_status.value,
        actor=actor,
        notes=notes,
        metadata={"figures_digest": fig_digest, "submit_for_review": submit_for_review},
    )
    return approval


def submit_for_review(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    notes: str = "",
    actor: dict[str, Any],
) -> ReturnApproval:
    """Submit already prepared return for Maker-Checker review."""
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    actor_role = normalize_role(actor.get("role"))
    if not is_writer_or_above(actor_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_ROLE_FOR_SUBMISSION",
                "message": f"Role '{actor_role}' is not authorized to submit returns for review.",
            },
        )

    norm_rt = normalize_return_type(return_type)
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )
    from_status = approval.status.value

    if approval.status not in (ApprovalStatus.PREPARED, ApprovalStatus.REJECTED, ApprovalStatus.DRAFT):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_STATE_FOR_SUBMISSION",
                "message": f"Cannot submit return for review from state '{approval.status.value}'. Must be PREPARED, DRAFT, or REJECTED.",
            },
        )

    if not approval.figures_digest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_PREPARED_FIGURES", "message": "Return has no prepared figures to submit."},
        )

    now = _now_iso()
    approval.status = ApprovalStatus.UNDER_REVIEW
    approval.preparer_id = str(actor.get("id"))
    approval.preparer_name = str(actor.get("full_name") or actor.get("email") or "Preparer")
    approval.preparer_role = actor_role
    approval.prepared_at = now
    approval.submission_notes = notes.strip()
    approval.updated_at = now

    _persist_approval(sb, approval)
    _record_audit_entry(
        sb,
        approval=approval,
        action=ApprovalAction.SUBMITTED_FOR_REVIEW.value,
        from_status=from_status,
        to_status=ApprovalStatus.UNDER_REVIEW.value,
        actor=actor,
        notes=notes,
        metadata={"figures_digest": approval.figures_digest},
    )
    return approval


def approve_return(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    expected_figures_digest: Optional[str] = None,
    notes: str = "",
    actor: dict[str, Any],
) -> ReturnApproval:
    """Authorized Manager/Partner approves submitted return.
    
    ENFORCES SEPARATION OF DUTIES: Preparer cannot approve their own submission!
    """
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    actor_id = str(actor.get("id") or "")
    actor_role = normalize_role(actor.get("role"))

    # 1. Role Authority Check: strictly Manager, Partner, Owner, or Admin
    if not is_manager_or_above(actor_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_ROLE_FOR_APPROVAL",
                "message": f"Role '{actor_role}' is not authorized to approve returns. Manager, Partner, or Owner role required.",
            },
        )

    norm_rt = normalize_return_type(return_type)
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )
    from_status = approval.status.value

    # 2. Separation of Duties Check: Approver MUST NOT be the Preparer
    if approval.preparer_id and str(approval.preparer_id).strip() == actor_id.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CANNOT_APPROVE_OWN_SUBMISSION",
                "message": "Separation of duties violation: Return preparer cannot approve their own submission. Another Manager or Partner must review and approve.",
            },
        )

    # 3. State Invariant Check: Must be in UNDER_REVIEW
    if approval.status != ApprovalStatus.UNDER_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_STATE_FOR_APPROVAL",
                "message": f"Cannot approve return in state '{approval.status.value}'. Return must be UNDER_REVIEW.",
            },
        )

    # 4. Tamper / Stale Approval Check
    if expected_figures_digest and expected_figures_digest.strip() != approval.figures_digest.strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "APPROVAL_STALE_FIGURES_ALTERED",
                "message": "Return figures have changed since submission for review. Renewal of review and approval is required.",
                "expected_digest": expected_figures_digest,
                "current_digest": approval.figures_digest,
            },
        )

    now = _now_iso()
    approval.status = ApprovalStatus.APPROVED
    approval.approver_id = actor_id
    approval.approver_name = str(actor.get("full_name") or actor.get("email") or "Approver")
    approval.approver_role = actor_role
    approval.approved_at = now
    approval.approval_notes = notes.strip()
    approval.updated_at = now

    _persist_approval(sb, approval)
    _record_audit_entry(
        sb,
        approval=approval,
        action=ApprovalAction.APPROVED.value,
        from_status=from_status,
        to_status=ApprovalStatus.APPROVED.value,
        actor=actor,
        notes=notes,
        metadata={"figures_digest": approval.figures_digest, "approver_role": actor_role},
    )
    return approval


def reject_return(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    rejection_reason: str,
    actor: dict[str, Any],
) -> ReturnApproval:
    """Authorized Manager/Partner rejects return with mandatory reason."""
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    actor_id = str(actor.get("id") or "")
    actor_role = normalize_role(actor.get("role"))

    if not is_manager_or_above(actor_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_ROLE_FOR_REJECTION",
                "message": f"Role '{actor_role}' is not authorized to reject returns. Manager, Partner, or Owner role required.",
            },
        )

    reason = (rejection_reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "REJECTION_REASON_REQUIRED",
                "message": "A detailed rejection reason is required to reject a return submission.",
            },
        )

    norm_rt = normalize_return_type(return_type)
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )
    from_status = approval.status.value

    if approval.status not in (ApprovalStatus.UNDER_REVIEW, ApprovalStatus.PREPARED, ApprovalStatus.APPROVED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_STATE_FOR_REJECTION",
                "message": f"Cannot reject return in status '{approval.status.value}'.",
            },
        )

    now = _now_iso()
    approval.status = ApprovalStatus.REJECTED
    approval.rejected_by = actor_id
    approval.rejected_by_name = str(actor.get("full_name") or actor.get("email") or "Reviewer")
    approval.rejected_by_role = actor_role
    approval.rejected_at = now
    approval.rejection_reason = reason
    approval.updated_at = now

    _persist_approval(sb, approval)
    _record_audit_entry(
        sb,
        approval=approval,
        action=ApprovalAction.REJECTED.value,
        from_status=from_status,
        to_status=ApprovalStatus.REJECTED.value,
        actor=actor,
        notes=f"Rejected: {reason}",
        rejection_reason=reason,
        metadata={"figures_digest": approval.figures_digest},
    )
    return approval


def assert_maker_checker_gate(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    return_type: str,
    current_figures_payload: Optional[Any] = None,
    operation: str = "SAVE",  # "SAVE", "OFFSET", "FILE"
    run_status: Optional[str] = None,
    run_created_at: Optional[Union[str, datetime]] = None,
) -> ReturnApproval:
    """Enforce server-side Maker-Checker gate before Save, Offset, or File operations.
    
    Verifies that return has been approved and that figures have not been altered.
    Supports backward compatibility ONLY for genuinely pre-existing in-flight legacy runs
    created prior to the Phase 3.2 introduction cutoff (2026-10-11T22:00:00Z).
    New filing runs created after this cutoff must NEVER bypass maker-checker gates.
    """
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    norm_rt = normalize_return_type(return_type)
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )

    # Legacy run adoption guard:
    # Genuinely pre-existing runs created BEFORE Phase 3.2 was introduced and already in-flight
    # (saved, offset_complete, etc.) without an approval record are adopted into the lifecycle.
    # New filing runs created after the Phase 3.2 cutoff MUST NEVER be adopted.
    if (
        approval.status == ApprovalStatus.DRAFT
        and not approval.figures_digest
        and run_status
        and run_status.lower() in ("saved", "proceeded", "offset_complete", "evc_pending")
        and _is_genuinely_legacy_run(run_created_at)
    ):
        adopted_status = (
            ApprovalStatus.OFFSET_COMPLETE
            if run_status.lower() in ("offset_complete", "evc_pending") and norm_rt == "GSTR-3B"
            else ApprovalStatus.SAVED
        )
        approval.gstin = gstin.strip().upper()
        approval.status = adopted_status
        approval.submission_notes = f"Adopted pre-existing legacy run (created: {run_created_at})"
        _persist_approval(sb, approval)
        _record_audit_entry(
            sb,
            approval=approval,
            action="LEGACY_RUN_ADOPTED",
            from_status="DRAFT",
            to_status=adopted_status.value,
            actor={"id": None, "full_name": "Legacy Run Migration Gate", "role": "system"},
            notes=f"Adopted genuinely pre-existing filing run created at {run_created_at}.",
            metadata={"run_created_at": str(run_created_at) if run_created_at else None},
        )
        return approval

    # 1. Approval Existence & Status Check
    op = operation.upper()
    if op == "SAVE":
        allowed_statuses = (ApprovalStatus.APPROVED, ApprovalStatus.SAVED, ApprovalStatus.OFFSET_COMPLETE)
        if approval.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "MAKER_CHECKER_APPROVAL_REQUIRED",
                    "message": f"Return must be reviewed and approved by a Manager or Partner before GSTN Save. Current status is '{approval.status.value}'.",
                    "status": approval.status.value,
                    "approval_id": approval.id,
                },
            )

    elif op == "OFFSET":
        allowed_statuses = (ApprovalStatus.SAVED, ApprovalStatus.OFFSET_COMPLETE)
        if approval.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "MAKER_CHECKER_APPROVAL_REQUIRED",
                    "message": f"Return liability offset requires prior approved Save. Current status is '{approval.status.value}'.",
                    "status": approval.status.value,
                    "approval_id": approval.id,
                },
            )

    elif op == "FILE":
        if norm_rt == "GSTR-3B":
            allowed_statuses = (ApprovalStatus.OFFSET_COMPLETE, ApprovalStatus.FILED)
        else:
            allowed_statuses = (ApprovalStatus.SAVED, ApprovalStatus.FILED, ApprovalStatus.APPROVED)

        if approval.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "MAKER_CHECKER_APPROVAL_REQUIRED",
                    "message": f"Return filing requires approved maker-checker completion. Current status is '{approval.status.value}'.",
                    "status": approval.status.value,
                    "approval_id": approval.id,
                },
            )

    # 2. Cryptographic Figure Binding Check
    if current_figures_payload is not None and approval.figures_digest:
        curr_digest = compute_figures_digest(current_figures_payload)
        if curr_digest != approval.figures_digest:
            _log.warning(
                "Stale approval detected for %s %s! Approved: %s, Current: %s",
                gstin, period, approval.figures_digest, curr_digest,
            )
            # Invalidate approval: reset to PREPARED, revoke all approval fields, and record audit
            from_st = approval.status.value
            approval.status = ApprovalStatus.PREPARED
            approval.approver_id = None
            approval.approver_name = ""
            approval.approver_role = ""
            approval.approved_at = None
            approval.approval_notes = ""
            approval.updated_at = _now_iso()
            _persist_approval(sb, approval)
            _record_audit_entry(
                sb,
                approval=approval,
                action=ApprovalAction.RESET.value,
                from_status=from_st,
                to_status=ApprovalStatus.PREPARED.value,
                actor={"id": None, "full_name": "System Security Gate", "role": "system"},
                notes="Approval invalidated: figures altered after approval was granted.",
                metadata={"previous_digest": approval.figures_digest, "current_digest": curr_digest},
            )

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "APPROVAL_STALE_FIGURES_ALTERED",
                    "message": "Filing payload figures do not match the approved figures digest. Return figures were altered after approval; renewed review and approval are required.",
                    "approved_digest": approval.figures_digest,
                    "current_digest": curr_digest,
                },
            )

    return approval


def transition_approval_status(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    period: str,
    return_type: str,
    to_status: ApprovalStatus,
    action: str,
    actor: dict[str, Any],
    filing_run_id: Optional[str] = None,
    notes: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> ReturnApproval:
    """Transition return approval state following successful save, offset, or file."""
    norm_rt = normalize_return_type(return_type)
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )
    from_status = approval.status.value
    approval.status = to_status
    if filing_run_id:
        approval.filing_run_id = filing_run_id
    approval.updated_at = _now_iso()

    _persist_approval(sb, approval)
    _record_audit_entry(
        sb,
        approval=approval,
        action=action,
        from_status=from_status,
        to_status=to_status.value,
        actor=actor,
        notes=notes,
        metadata=metadata or {},
    )
    return approval


def get_approval_history(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    period: str,
    return_type: str,
) -> list[dict[str, Any]]:
    """Retrieve complete audit history for a return's maker-checker lifecycle."""
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    norm_rt = normalize_return_type(return_type)
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period,
        return_type=norm_rt,
    )

    # 1. From database if live
    if sb is not None and not _is_test_runner(sb):
        try:
            res = (
                sb.table(AUDIT_TABLE)
                .select("*")
                .eq("approval_id", approval.id)
                .order("created_at", desc=False)
                .execute()
            )
            if res.data:
                return res.data
        except Exception as exc:
            _log.warning("Audit trail query failed: %s", exc)

    # 2. From process store
    entries = _mc_store.get_audit_trail(approval.id)
    return [e.to_dict() for e in entries]


def list_pending_approvals(
    sb: Any,
    *,
    firm_id: str,
    current_user: dict[str, Any],
) -> list[dict[str, Any]]:
    """List all returns currently in UNDER_REVIEW status awaiting manager/partner approval."""
    with _mc_store._lock:
        pending = [
            a.to_dict()
            for a in _mc_store._approvals.values()
            if a.firm_id == firm_id and a.status == ApprovalStatus.UNDER_REVIEW
        ]
    if sb is not None and not _is_test_runner(sb):
        try:
            res = (
                sb.table(APPROVALS_TABLE)
                .select("*")
                .eq("firm_id", firm_id)
                .eq("status", ApprovalStatus.UNDER_REVIEW.value)
                .order("prepared_at", desc=False)
                .execute()
            )
            if res.data:
                return res.data
        except Exception:
            pass
    return pending

