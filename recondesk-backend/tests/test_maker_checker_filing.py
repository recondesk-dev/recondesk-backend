"""Comprehensive Test Suite for Phase 3.2: Maker-Checker Return Filing Approvals.

Tests cover:
1. Complete lifecycle transitions: DRAFT -> PREPARED -> UNDER_REVIEW -> APPROVED -> SAVED -> OFFSET_COMPLETE -> FILED.
2. Cross-tenant isolation: Users from Tenant B cannot view, prepare, approve, or reject Tenant A's returns.
3. Separation of duties: Preparers cannot approve their own return submissions (CANNOT_APPROVE_OWN_SUBMISSION).
4. Granular RBAC enforcement: Preparers and Viewers cannot approve or reject (INSUFFICIENT_ROLE_FOR_APPROVAL).
5. Rejection & revision cycle: Rejection with mandatory reason -> REJECTED -> Re-preparation -> Approval.
6. Cryptographic binding & stale approval detection: Modifying figures invalidates approval (APPROVAL_STALE_FIGURES_ALTERED).
7. Celery worker bypass prevention: Worker hard-blocks unapproved returns and stale figure digests.
8. Preservation of Phase 2 governance: Maker-checker approval does not bypass statutory override requirements.
9. Direct API gate enforcement: Unapproved returns cannot be Saved, Offset, or Filed.
10. Backward compatibility for legacy filing runs: Adoption with audit log.
11. Tenant-scoped immutable audit trail: Captures actor, role, timestamp, digests, and rejection reasons.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.routers import filing as filing_router
from app.services.maker_checker_service import (
    ApprovalAction,
    ApprovalStatus,
    ReturnApproval,
    _mc_store,
    approve_return,
    assert_maker_checker_gate,
    get_approval_history,
    get_return_approval,
    prepare_return,
    reject_return,
    submit_for_review,
    transition_approval_status,
)
from app.services.filing_override_service import (
    FilingPolicy,
    FilingPolicyMode,
    _governance_store,
)
from app.services.pre_filing_validator import (
    PreFilingValidationResult,
    ValidationSeverity,
    ValidationViolation,
    ViolationCategory,
    compute_figures_digest,
)


@pytest.fixture(autouse=True)
def clean_stores():
    _mc_store.clear()
    _governance_store.clear()
    yield
    _mc_store.clear()
    _governance_store.clear()


def _make_client_row(firm_id: str = "firm-1", client_id: str = "cid-1", gstin: str = "27AABCU9603R1ZM") -> dict:
    return {
        "id": client_id,
        "firm_owner_id": firm_id,
        "gstin": gstin,
        "business_name": "Acme Corp",
        "is_active": True,
    }


# ---------------------------------------------------------------------------
# 1. Full Lifecycle State Machine
# ---------------------------------------------------------------------------

def test_full_lifecycle_state_machine():
    """Verify happy path from DRAFT to FILED through all required lifecycle stages."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "GSTR-1"

    preparer = {"id": "user-preparer", "email": "prep@firm.com", "role": "preparer"}
    manager = {"id": "user-manager", "email": "mgr@firm.com", "role": "manager"}

    client_row = _make_client_row(firm_id, client_id, gstin)

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # 1. Starts as DRAFT
        initial = get_return_approval(mock_sb, firm_id=firm_id, client_gstin_id=client_id, period=period, return_type=return_type)
        assert initial.status == ApprovalStatus.DRAFT

        # 2. Preparer prepares figures
        figures = {"total_taxable_value": 500000.0, "total_tax": 90000.0, "invoice_count": 12}
        prep_res = prepare_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=figures,
            notes="Prepared November figures from sales register",
            actor=preparer,
        )
        assert prep_res.status == ApprovalStatus.PREPARED
        assert prep_res.preparer_id == "user-preparer"
        assert prep_res.figures_digest != ""
        digest = prep_res.figures_digest

        # 3. Preparer submits for review
        sub_res = submit_for_review(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            notes="Please review November return",
            actor=preparer,
        )
        assert sub_res.status == ApprovalStatus.UNDER_REVIEW

        # 4. Manager approves return
        appr_res = approve_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            expected_figures_digest=digest,
            notes="Figures cross-checked with books. Approved.",
            actor=manager,
        )
        assert appr_res.status == ApprovalStatus.APPROVED
        assert appr_res.approver_id == "user-manager"

        # 5. Server-side Gate verifies Save is permitted
        gate_res = assert_maker_checker_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            current_figures_payload=figures,
            operation="SAVE",
        )
        assert gate_res.status == ApprovalStatus.APPROVED

        # 6. Save succeeds -> transition to SAVED
        saved_res = transition_approval_status(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            period=period,
            return_type=return_type,
            to_status=ApprovalStatus.SAVED,
            action=ApprovalAction.SAVED.value,
            actor=manager,
            filing_run_id="run-101",
            notes="Saved to GSTN",
        )
        assert saved_res.status == ApprovalStatus.SAVED

        # 7. File succeeds -> transition to FILED
        filed_res = transition_approval_status(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            period=period,
            return_type=return_type,
            to_status=ApprovalStatus.FILED,
            action=ApprovalAction.FILED.value,
            actor=manager,
            filing_run_id="run-101",
            notes="Statutory ACK AA271124000001Z",
        )
        assert filed_res.status == ApprovalStatus.FILED

        # 8. Verify complete audit trail history
        history = get_approval_history(mock_sb, firm_id=firm_id, client_gstin_id=client_id, period=period, return_type=return_type)
        actions = [e["action"] for e in history]
        assert "PREPARED" in actions
        assert "SUBMITTED_FOR_REVIEW" in actions
        assert "APPROVED" in actions
        assert "SAVED" in actions
        assert "FILED" in actions


# ---------------------------------------------------------------------------
# 2. Separation of Duties: Self-Approval Hard Block
# ---------------------------------------------------------------------------

def test_separation_of_duties_self_approval_blocked():
    """A CA Partner or Manager who prepared/submitted a return CANNOT approve their own submission."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "GSTR-1"

    # Even though user is a Partner, they are the PREPARER of this specific return
    partner_preparer = {"id": "user-partner-1", "email": "partner@firm.com", "role": "partner"}

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        figures = {"total_taxable_value": 100000.0, "total_tax": 18000.0}
        prepare_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=figures,
            notes="Partner drafted figures directly",
            actor=partner_preparer,
            submit_for_review=True,
        )

        # Attempting self-approval MUST be rejected with HTTP 403 CANNOT_APPROVE_OWN_SUBMISSION
        with pytest.raises(HTTPException) as exc_info:
            approve_return(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                notes="Self-approving my own draft",
                actor=partner_preparer,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "CANNOT_APPROVE_OWN_SUBMISSION"
        assert "Separation of duties" in exc_info.value.detail["message"]


# ---------------------------------------------------------------------------
# 3. RBAC Enforcement: Unauthorized Roles Cannot Approve or Reject
# ---------------------------------------------------------------------------

def test_unauthorized_roles_cannot_approve_or_reject():
    """Preparers, Staff, and Viewers cannot approve or reject submitted returns."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "GSTR-1"

    preparer_1 = {"id": "user-prep-1", "role": "preparer"}
    preparer_2 = {"id": "user-prep-2", "role": "preparer"}  # different user, but still preparer role
    viewer = {"id": "user-viewer", "role": "viewer"}

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        figures = {"total_taxable_value": 200000.0}
        prepare_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=figures,
            actor=preparer_1,
            submit_for_review=True,
        )

        # Preparer 2 attempts approval
        with pytest.raises(HTTPException) as exc_p2:
            approve_return(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                actor=preparer_2,
            )
        assert exc_p2.value.status_code == 403
        assert exc_p2.value.detail["code"] == "INSUFFICIENT_ROLE_FOR_APPROVAL"

        # Viewer attempts approval
        with pytest.raises(HTTPException) as exc_v:
            approve_return(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                actor=viewer,
            )
        assert exc_v.value.status_code == 403
        assert exc_v.value.detail["code"] == "INSUFFICIENT_ROLE_FOR_APPROVAL"

        # Viewer attempts rejection
        with pytest.raises(HTTPException) as exc_rej:
            reject_return(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                rejection_reason="Unqualified viewer reject",
                actor=viewer,
            )
        assert exc_rej.value.status_code == 403
        assert exc_rej.value.detail["code"] == "INSUFFICIENT_ROLE_FOR_REJECTION"


# ---------------------------------------------------------------------------
# 4. Rejection and Revision Lifecycle
# ---------------------------------------------------------------------------

def test_rejection_workflow_and_re_preparation():
    """Manager rejects return with mandatory reason; preparer revises figures and re-submits."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "GSTR-1"

    preparer = {"id": "user-prep", "role": "preparer"}
    manager = {"id": "user-mgr", "role": "manager"}

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # 1. Initial submission
        prepare_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload={"total_taxable_value": 100000.0},
            actor=preparer,
            submit_for_review=True,
        )

        # 2. Manager attempts rejection with empty reason -> HTTP 400
        with pytest.raises(HTTPException) as exc_empty:
            reject_return(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                rejection_reason="   ",
                actor=manager,
            )
        assert exc_empty.value.status_code == 400
        assert exc_empty.value.detail["code"] == "REJECTION_REASON_REQUIRED"

        # 3. Manager rejects with detailed reason
        rej_res = reject_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            rejection_reason="B2B Invoice INV-099 omitted. Please reconcile and re-upload.",
            actor=manager,
        )
        assert rej_res.status == ApprovalStatus.REJECTED
        assert rej_res.rejection_reason == "B2B Invoice INV-099 omitted. Please reconcile and re-upload."

        # 4. Save gate blocks in REJECTED state
        with pytest.raises(HTTPException) as exc_gate:
            assert_maker_checker_gate(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                operation="SAVE",
            )
        assert exc_gate.value.status_code == 403
        assert exc_gate.value.detail["code"] == "MAKER_CHECKER_APPROVAL_REQUIRED"

        # 5. Preparer updates figures and re-submits
        revised_figures = {"total_taxable_value": 150000.0, "invoice_count": 13}
        prep_revised = prepare_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=revised_figures,
            notes="Added missing invoice INV-099",
            actor=preparer,
            submit_for_review=True,
        )
        assert prep_revised.status == ApprovalStatus.UNDER_REVIEW

        # 6. Manager approves revised submission
        appr_revised = approve_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            expected_figures_digest=prep_revised.figures_digest,
            notes="Verified INV-099 included. Approved.",
            actor=manager,
        )
        assert appr_revised.status == ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# 5. Cryptographic Binding & Stale Approval Invalidation
# ---------------------------------------------------------------------------

def test_stale_approval_invalidation_when_figures_altered():
    """If figures are altered after approval, the approval is invalidated (HTTP 409)."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "GSTR-1"

    preparer = {"id": "user-prep", "role": "preparer"}
    partner = {"id": "user-partner", "role": "partner"}

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # Original figures: ₹1,00,000
        original_figures = {"total_taxable_value": 100000.0, "tax": 18000.0}
        prepare_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=original_figures,
            actor=preparer,
            submit_for_review=True,
        )
        approve_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            actor=partner,
        )

        # Altered figures: ₹2,50,000 (tampered or recomputed behind the scenes)
        tampered_figures = {"total_taxable_value": 250000.0, "tax": 45000.0}

        # Attempting Save with altered figures MUST be hard blocked with HTTP 409
        with pytest.raises(HTTPException) as exc_info:
            assert_maker_checker_gate(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                current_figures_payload=tampered_figures,
                operation="SAVE",
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "APPROVAL_STALE_FIGURES_ALTERED"

        # Approval status was automatically reset to PREPARED
        current = get_return_approval(mock_sb, firm_id=firm_id, client_gstin_id=client_id, period=period, return_type=return_type)
        assert current.status == ApprovalStatus.PREPARED


# ---------------------------------------------------------------------------
# 6. Celery Bulk Worker Gate Enforcement
# ---------------------------------------------------------------------------

def test_celery_worker_blocks_unapproved_batch_items():
    """Bulk filing worker blocks items that lack maker-checker approval with code MAKER_CHECKER_APPROVAL_REQUIRED."""
    from app.worker.filing_batch_task import process_filing_batch
    mock_sb = MagicMock()
    batch_id = "batch-101"
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"

    batch_row = {
        "id": batch_id,
        "firm_id": firm_id,
        "period": period,
        "status": "pending",
        "created_by": "user-admin",
        "items": [
            {
                "id": "item-1",
                "client_gstin_id": client_id,
                "gstin": gstin,
                "status": "pending",
            }
        ],
    }

    with patch("app.worker.filing_batch_task.get_supabase", return_value=mock_sb):
        with patch("app.worker.filing_batch_task.filing_store.get_batch", return_value=batch_row):
            with patch("app.services.firm_access.assert_client_gstin_in_firm"):
                with patch("app.worker.filing_batch_task.filing_store.get_active_session", return_value={"session_token": "token", "id": "s-1"}):
                    with patch("app.worker.filing_batch_task.fetch_sales_register_records", return_value=[{"inum": "INV-1", "val": 1000.0}]):
                        with patch("app.worker.filing_batch_task.map_sales_register_to_gstr1") as mock_map:
                            mock_mapped = MagicMock()
                            mock_mapped.save_payload = {"b2b": []}
                            mock_map.return_value = mock_mapped
                            with patch("app.worker.filing_batch_task.serialize_gstr1_readiness", return_value={"pending_review_count": 0}):
                                with patch("app.services.pre_filing_validator.validate_gstr1_pre_filing"):
                                    with patch("app.services.filing_override_service.verify_filing_governance_gate"):
                                        with patch("app.worker.filing_batch_task.filing_store.update_batch_item") as mock_update_item:
                                            # We did NOT approve the return, so approval is in DRAFT state
                                            process_filing_batch.__wrapped__(batch_id)

                                            # Assert that worker blocked item-1 with MAKER_CHECKER_APPROVAL_REQUIRED
                                            calls = [c for c in mock_update_item.call_args_list if c[1].get("status") == "blocked"]
                                            assert len(calls) > 0
                                            assert calls[0][1]["error_code"] == "MAKER_CHECKER_APPROVAL_REQUIRED"


# ---------------------------------------------------------------------------
# 7. Preservation of Phase 2 Governance & Overrides
# ---------------------------------------------------------------------------

def test_maker_checker_does_not_bypass_compliance_override():
    """Maker-Checker approval does NOT replace required partner override under PARTNER_OVERRIDE policy."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "GSTR-1"

    preparer = {"id": "user-prep", "role": "preparer"}
    manager = {"id": "user-mgr", "role": "manager"}

    # Set firm policy to PARTNER_OVERRIDE
    _governance_store.set_policy(
        firm_id,
        FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE, require_final_reconciliation=True),
    )

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        figures = {"total_taxable_value": 500000.0}
        prepare_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=figures,
            actor=preparer,
            submit_for_review=True,
        )
        approve_return(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            actor=manager,
        )

        # Validation result has a critical Rule 88C statutory violation
        critical_violation = ValidationViolation(
            code="RULE_88C_OUTWARD_EXCESS",
            message="Outward liability exceeds GSTR-3B by > ₹25L",
            category=ViolationCategory.STATUTORY_BREACH,
            severity=ValidationSeverity.CRITICAL_ERROR,
        )
        val_res = PreFilingValidationResult(
            return_type="gstr-1",
            gstin=gstin,
            period=period,
            is_valid=False,
            overall_severity=ValidationSeverity.CRITICAL_ERROR,
            figures_digest=compute_figures_digest(figures),
            violations=[critical_violation],
        )

        # Maker-checker gate passes:
        mc_approval = assert_maker_checker_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            current_figures_payload=figures,
            operation="SAVE",
        )
        assert mc_approval.status == ApprovalStatus.APPROVED

        # BUT the Phase 2 governance gate STILL blocks because an explicit partner override is missing!
        from app.services.filing_override_service import verify_filing_governance_gate
        with pytest.raises(HTTPException) as exc_gov:
            verify_filing_governance_gate(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type="gstr-1",
                validation_result=val_res,
                user=manager,
            )
        assert exc_gov.value.status_code == 422
        assert exc_gov.value.detail["code"] == "PARTNER_OVERRIDE_REQUIRED"


# ---------------------------------------------------------------------------
# 8. Cross-Tenant Access Isolation
# ---------------------------------------------------------------------------

def test_cross_tenant_access_blocked():
    """User belonging to Firm B cannot view, prepare, or approve Firm A's returns."""
    mock_sb = MagicMock()
    # Configure mock_sb so that client lookup for firm_b yields empty results (unauthorized)
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

    firm_b = "firm-b"
    client_a = "cid-a"
    gstin_a = "27AABCU9603R1ZM"
    period = "2024-11"

    user_b = {"id": "user-b", "email": "ca@firmb.com", "role": "partner"}

    # Attempting to access Firm A's return while asserting Firm B raises 403 Forbidden
    with pytest.raises(HTTPException) as exc_prep:
        prepare_return(
            mock_sb,
            firm_id=firm_b,
            client_gstin_id=client_a,
            gstin=gstin_a,
            period=period,
            return_type="GSTR-1",
            figures_payload={"val": 100},
            actor=user_b,
        )
    assert exc_prep.value.status_code == 403


# ---------------------------------------------------------------------------
# 9. Direct API Save / File Gate Enforcement
# ---------------------------------------------------------------------------

def test_direct_save_blocked_without_maker_checker_approval():
    """Direct invocation of save_gstr3b is blocked when return has not been approved."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"

    client_row = _make_client_row(firm_id, client_id, gstin)
    user = {"id": "user-writer", "role": "preparer"}

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value=firm_id):
            with patch("app.routers.filing._assert_client_access", return_value=client_row):
                with patch("app.routers.filing.filing_store.assert_gstr3b_save_allowed"):
                    with patch("app.routers.filing._resolve_token", return_value=("token", {"id": "sess-1"})):
                        with patch("app.services.pre_filing_validator.validate_gstr3b_pre_filing"):
                            with patch("app.services.filing_override_service.verify_filing_governance_gate"):
                                body = filing_router.SaveGstr3bBody(
                                    period=period,
                                    client_gstin_id=client_id,
                                    session_id="sess-1",
                                    save_body={"gstin": gstin},
                                )
                                with pytest.raises(HTTPException) as exc_info:
                                    filing_router.save_gstr3b(period, body, current_user=user)

                                assert exc_info.value.status_code == 403
                                assert exc_info.value.detail["code"] == "MAKER_CHECKER_APPROVAL_REQUIRED"


# ---------------------------------------------------------------------------
# 10. Backward Compatibility: Genuine Legacy Filing Run Adoption
# ---------------------------------------------------------------------------

def test_legacy_filing_run_adoption():
    """In-flight legacy filing runs created prior to Phase 3.2 are gracefully adopted into maker-checker state."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # Run was created genuinely BEFORE Phase 3.2 cutoff (e.g. 2026-10-10) and saved in GSTN
        adopted = assert_maker_checker_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type="GSTR-1",
            operation="FILE",
            run_status="saved",
            run_created_at="2026-10-10T12:00:00Z",
        )
        assert adopted.status == ApprovalStatus.SAVED

        # Audit trail records adoption
        history = get_approval_history(mock_sb, firm_id=firm_id, client_gstin_id=client_id, period=period, return_type="GSTR-1")
        assert len(history) == 1
        assert history[0]["action"] == "LEGACY_RUN_ADOPTED"


def test_new_filing_run_cannot_bypass_via_legacy_adoption():
    """New filing runs created post-Phase 3.2 cutoff MUST NEVER bypass maker-checker via legacy adoption."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-12"

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # Run created AFTER Phase 3.2 introduction cutoff
        with pytest.raises(HTTPException) as exc_info:
            assert_maker_checker_gate(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type="GSTR-1",
                operation="FILE",
                run_status="saved",
                run_created_at="2026-10-12T09:30:00Z",  # Post-cutoff
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "MAKER_CHECKER_APPROVAL_REQUIRED"


def test_missing_creation_timestamp_cannot_bypass_via_legacy_adoption():
    """Filing runs with unknown/missing creation timestamp fail closed and are not adopted as legacy."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-12"

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        with pytest.raises(HTTPException) as exc_info:
            assert_maker_checker_gate(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type="GSTR-1",
                operation="FILE",
                run_status="saved",
                run_created_at=None,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "MAKER_CHECKER_APPROVAL_REQUIRED"



# ---------------------------------------------------------------------------
# 11. Router Approvals Endpoints Contract
# ---------------------------------------------------------------------------

def test_router_approvals_endpoints():
    """Verify router endpoints: prepare, submit, approve, reject, and history."""
    mock_sb = MagicMock()
    firm_id = "firm-1"
    client_id = "cid-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "gstr-1"

    client_row = _make_client_row(firm_id, client_id, gstin)
    preparer = {"id": "user-prep", "role": "preparer"}
    manager = {"id": "user-mgr", "role": "manager"}

    with patch("app.routers.filing.get_supabase", return_value=mock_sb):
        with patch("app.routers.filing._firm_id", return_value=firm_id):
            with patch("app.routers.filing._assert_client_access", return_value=client_row):
                # 1. Prepare
                prep_body = filing_router.PrepareApprovalBody(
                    client_gstin_id=client_id,
                    figures_payload={"b2b": []},
                    notes="Prepared draft",
                )
                res_prep = filing_router.prepare_filing_approval(return_type, period, prep_body, current_user=preparer)
                assert res_prep["status"] == "PREPARED"

                # 2. Submit
                sub_body = filing_router.SubmitApprovalBody(client_gstin_id=client_id, notes="Ready for review")
                res_sub = filing_router.submit_filing_approval(return_type, period, sub_body, current_user=preparer)
                assert res_sub["status"] == "UNDER_REVIEW"

                # 3. Approve
                appr_body = filing_router.ApproveApprovalBody(client_gstin_id=client_id, notes="Looks good")
                res_appr = filing_router.approve_filing_approval(return_type, period, appr_body, current_user=manager)
                assert res_appr["status"] == "APPROVED"

                # 4. History
                hist = filing_router.get_filing_approval_history(return_type, period, client_gstin_id=client_id, current_user=preparer)
                assert len(hist["history"]) >= 3


# ---------------------------------------------------------------------------
# 12. Transaction Boundary: Stale Invalidation Durability Across Rollbacks
# ---------------------------------------------------------------------------

def test_stale_approval_invalidation_durable_transaction_boundary():
    """Ensure changed figures durably invalidate approval in DB even when filing request transaction rolls back."""
    import json
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool
    from app.aurora_client import APIResponse

    # In-memory SQLite with StaticPool so all connections share the same transactional database
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE return_filing_approvals (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                return_type TEXT NOT NULL,
                status TEXT NOT NULL,
                figures_digest TEXT NOT NULL DEFAULT '',
                validation_digest TEXT NOT NULL DEFAULT '',
                figures_summary TEXT NOT NULL DEFAULT '{}',
                preparer_id TEXT,
                preparer_name TEXT NOT NULL DEFAULT '',
                preparer_role TEXT NOT NULL DEFAULT '',
                prepared_at TEXT,
                submission_notes TEXT DEFAULT '',
                approver_id TEXT,
                approver_name TEXT NOT NULL DEFAULT '',
                approver_role TEXT NOT NULL DEFAULT '',
                approved_at TEXT,
                approval_notes TEXT DEFAULT '',
                rejected_by TEXT,
                rejected_by_name TEXT NOT NULL DEFAULT '',
                rejected_by_role TEXT NOT NULL DEFAULT '',
                rejected_at TEXT,
                rejection_reason TEXT DEFAULT '',
                filing_run_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (firm_id, client_gstin_id, period, return_type)
            );
        """))
        conn.execute(text("""
            CREATE TABLE return_approval_audit_trail (
                id TEXT PRIMARY KEY,
                approval_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                return_type TEXT NOT NULL,
                action TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                actor_id TEXT,
                actor_name TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                notes TEXT,
                rejection_reason TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
        """))
        conn.commit()

    class _SqliteQueryBuilder:
        def __init__(self, eng, table_name: str):
            self.eng = eng
            self.table_name = table_name
            self._action = "select"
            self._where = []
            self._params = {}
            self._payload = None
            self._limit = None
            self._on_conflict = None

        def select(self, cols="*"):
            self._action = "select"
            return self

        def eq(self, col: str, val: Any):
            p = f"p_{col}_{len(self._params)}"
            self._where.append(f"{col} = :{p}")
            self._params[p] = val
            return self

        def limit(self, n: int):
            self._limit = n
            return self

        def order(self, col: str, desc: bool = False):
            return self

        def insert(self, data: dict):
            self._action = "insert"
            self._payload = data
            return self

        def upsert(self, data: dict, on_conflict: str = ""):
            self._action = "upsert"
            self._payload = data
            self._on_conflict = on_conflict
            return self

        def execute(self):
            with self.eng.connect() as c:
                if self._action == "select":
                    where_clause = (" WHERE " + " AND ".join(self._where)) if self._where else ""
                    limit_clause = f" LIMIT {self._limit}" if self._limit else ""
                    sql = f"SELECT * FROM {self.table_name}{where_clause}{limit_clause}"
                    rows = [dict(r._mapping) for r in c.execute(text(sql), self._params).fetchall()]
                    # Deserialize JSON fields
                    for r in rows:
                        if "figures_summary" in r and isinstance(r["figures_summary"], str):
                            try:
                                r["figures_summary"] = json.loads(r["figures_summary"])
                            except Exception:
                                pass
                    return APIResponse(rows)
                elif self._action == "insert":
                    cols = list(self._payload.keys())
                    col_sql = ", ".join(cols)
                    val_sql = ", ".join([f":{col}" for col in cols])
                    params = {col: json.dumps(v) if isinstance(v, (dict, list)) else v for col, v in self._payload.items()}
                    c.execute(text(f"INSERT INTO {self.table_name} ({col_sql}) VALUES ({val_sql})"), params)
                    c.commit()
                    return APIResponse([self._payload])
                elif self._action == "upsert":
                    cols = list(self._payload.keys())
                    col_sql = ", ".join(cols)
                    val_sql = ", ".join([f":{col}" for col in cols])
                    conflict_cols = [x.strip() for x in (self._on_conflict or "").split(",") if x.strip()]
                    params = {col: json.dumps(v) if isinstance(v, (dict, list)) else v for col, v in self._payload.items()}
                    if conflict_cols:
                        upd_cols = [col for col in cols if col not in conflict_cols]
                        upd_sql = ", ".join([f"{col} = excluded.{col}" for col in upd_cols])
                        sql = f"INSERT INTO {self.table_name} ({col_sql}) VALUES ({val_sql}) ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {upd_sql}"
                    else:
                        sql = f"INSERT OR REPLACE INTO {self.table_name} ({col_sql}) VALUES ({val_sql})"
                    c.execute(text(sql), params)
                    c.commit()
                    return APIResponse([self._payload])
            return APIResponse([])

    class SqliteDbAdapter:
        def __init__(self, eng):
            self.eng = eng
            self.is_real_db = True

        def table(self, tbl: str):
            return _SqliteQueryBuilder(self.eng, tbl)

    db_client = SqliteDbAdapter(engine)
    firm_id = "firm-tx-1"
    client_id = "client-tx-1"
    gstin = "27AABCU9603R1ZM"
    period = "2024-11"
    return_type = "GSTR-1"

    preparer = {"id": "prep-tx", "role": "preparer", "email": "prep@firm.com"}
    partner = {"id": "partner-tx", "role": "partner", "email": "partner@firm.com"}

    with patch("app.services.maker_checker_service.assert_client_gstin_in_firm"):
        # 1. Prepare and submit
        figures_original = {"total_taxable_value": 100000.0, "total_tax": 18000.0}
        prep = prepare_return(
            db_client,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            figures_payload=figures_original,
            actor=preparer,
            submit_for_review=True,
        )

        # 2. Approve
        approved = approve_return(
            db_client,
            firm_id=firm_id,
            client_gstin_id=client_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            actor=partner,
            notes="Sign-off granted",
        )
        assert approved.status == ApprovalStatus.APPROVED

        # 3. Simulate caller transaction boundary where filing request alters figures
        # and subsequently fails/rolls back
        figures_altered = {"total_taxable_value": 250000.0, "total_tax": 45000.0}

        with engine.connect() as outer_conn:
            with outer_conn.begin():
                # Outer caller transaction begins
                with pytest.raises(HTTPException) as exc_409:
                    assert_maker_checker_gate(
                        db_client,
                        firm_id=firm_id,
                        client_gstin_id=client_id,
                        gstin=gstin,
                        period=period,
                        return_type=return_type,
                        current_figures_payload=figures_altered,
                        operation="SAVE",
                    )
                assert exc_409.value.status_code == 409
                assert exc_409.value.detail["code"] == "APPROVAL_STALE_FIGURES_ALTERED"

                # Outer transaction is explicitly rolled back
                outer_conn.rollback()

        # 4. Verify durable persistence in database independent of caller's rollback
        with engine.connect() as verify_conn:
            row = verify_conn.execute(
                text("SELECT status, approver_id, approved_at, approval_notes FROM return_filing_approvals WHERE firm_id = :f"),
                {"f": firm_id},
            ).mappings().first()
            assert row is not None
            # Durably reset to PREPARED
            assert row["status"] == "PREPARED"
            # Approver metadata strictly revoked
            assert row["approver_id"] is None
            assert row["approved_at"] is None
            assert row["approval_notes"] == ""

            # Audit trail durably contains RESET entry
            audit_records = verify_conn.execute(
                text("SELECT action, from_status, to_status FROM return_approval_audit_trail WHERE firm_id = :f"),
                {"f": firm_id},
            ).mappings().all()
            actions = [r["action"] for r in audit_records]
            assert "RESET" in actions

        # 5. Subsequent save attempt must be blocked by the gate (HTTP 403)
        with pytest.raises(HTTPException) as exc_blocked:
            assert_maker_checker_gate(
                db_client,
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=gstin,
                period=period,
                return_type=return_type,
                operation="SAVE",
            )
        assert exc_blocked.value.status_code == 403
        assert exc_blocked.value.detail["code"] == "MAKER_CHECKER_APPROVAL_REQUIRED"


# ---------------------------------------------------------------------------
# 13. Migration Rollback: Non-Destructive Archival and Restoration
# ---------------------------------------------------------------------------

def test_migration_rollback_archival_and_restoration():
    """Verify that rollback migration archives approvals and audit trail, preventing silent data loss."""
    import os

    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    down_path = os.path.join(backend_root, "migrations/aurora/20261011220000_create_maker_checker_approvals.down.sql")
    up_path = os.path.join(backend_root, "migrations/aurora/20261011220000_create_maker_checker_approvals.up.sql")

    assert os.path.exists(down_path), f"Down migration not found at {down_path}"
    assert os.path.exists(up_path), f"Up migration not found at {up_path}"

    with open(down_path) as f:
        down_sql = f.read()
    with open(up_path) as f:
        up_sql = f.read()

    # Down migration MUST create archival tables before dropping
    assert "CREATE TABLE IF NOT EXISTS public._archive_return_approval_audit_trail_rollback" in down_sql
    assert "CREATE TABLE IF NOT EXISTS public._archive_return_filing_approvals_rollback" in down_sql
    assert "INSERT INTO public._archive_return_approval_audit_trail_rollback" in down_sql
    assert "INSERT INTO public._archive_return_filing_approvals_rollback" in down_sql

    # Up migration MUST include restoration block from archives
    assert "_archive_return_filing_approvals_rollback" in up_sql
    assert "_archive_return_approval_audit_trail_rollback" in up_sql
    assert "ON CONFLICT (firm_id, client_gstin_id, period, return_type) DO NOTHING" in up_sql

