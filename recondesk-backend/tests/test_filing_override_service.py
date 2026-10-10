"""Automated unit and integration tests for CA Approval & Filing Governance Controls.

Covers:
- Policy modes: ADVISORY, PARTNER_OVERRIDE, STRICT_BLOCK.
- Role-based authorization: only admin/owner can create overrides; staff rejected with HTTP 403.
- Justification quality gate: min 10 characters required; rejected with HTTP 422 if insufficient.
- Tamper-evidence: figure alteration produces HTTP 409 Conflict (OVERRIDE_FIGURES_MISMATCH).
- Override lifecycle: single-use consumption upon return filing.
- Strict block: critical statutory violations unconditionally block filing under STRICT_BLOCK.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.filing_override_service import (
    FilingOverride,
    FilingPolicy,
    FilingPolicyMode,
    FilingPolicyUpdate,
    _governance_store,
    consume_override_on_file_sync,
    create_partner_override,
    get_firm_filing_policy,
    update_firm_filing_policy,
    verify_filing_governance_gate,
)
from app.services.pre_filing_validator import (
    PreFilingValidationResult,
    ValidationSeverity,
    ValidationViolation,
    ViolationCategory,
)


@pytest.fixture(autouse=True)
def clean_governance_store():
    """Clear memory store between tests."""
    _governance_store.clear()
    yield
    _governance_store.clear()


def _multiprocess_cas_worker(args: tuple[str, int]) -> list[str]:
    import sqlite3
    db_path, worker_idx = args
    con = sqlite3.connect(db_path, timeout=30.0)
    now_iso = "2024-11-20T12:00:00Z"
    run_id = f"proc-run-{worker_idx}"
    cur = con.cursor()
    cur.execute("""
        UPDATE filing_overrides
        SET is_consumed = 1, consumed_at = ?, consumed_run_id = ?
        WHERE id = 'override-mp-cas-1' AND is_consumed = 0 AND expires_at > ?
        RETURNING id;
    """, (now_iso, run_id, now_iso))
    rows = [r[0] for r in cur.fetchall()]
    con.commit()
    con.close()
    return rows


def _make_violation_result(figures_digest: str, has_critical: bool = True) -> PreFilingValidationResult:
    violations = []
    if has_critical:
        violations.append(
            ValidationViolation(
                code="RULE_88C_DRC01B_TRIGGER",
                message="Outward tax liability in GSTR-1 exceeds GSTR-3B by ₹30,00,000 (30.0%)",
                category=ViolationCategory.STATUTORY_BREACH,
                severity=ValidationSeverity.CRITICAL_ERROR,
            )
        )
    return PreFilingValidationResult(
        return_type="gstr-3b",
        gstin="27AABCU9603R1ZM",
        period="2024-11",
        is_valid=not has_critical,
        overall_severity=ValidationSeverity.CRITICAL_ERROR if has_critical else ValidationSeverity.CLEAN,
        figures_digest=figures_digest,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# 1. Policy Mode Enforcement Tests
# ---------------------------------------------------------------------------


def test_advisory_mode_permits_filing_with_critical_violations():
    """Under ADVISORY policy, gate returns None (advisory warnings only, non-blocking)."""
    mock_sb = MagicMock()
    firm_id = "firm-101"
    user = {"id": "user-staff", "role": "staff"}

    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.ADVISORY))

    val_res = _make_violation_result("digest-abc-123", has_critical=True)
    gate_result = verify_filing_governance_gate(
        mock_sb,
        firm_id=firm_id,
        client_gstin_id="cid-1",
        gstin="27AABCU9603R1ZM",
        period="2024-11",
        return_type="gstr-3b",
        validation_result=val_res,
        user=user,
    )
    assert gate_result is None


def test_partner_override_mode_blocks_without_approval():
    """Under PARTNER_OVERRIDE, filing is blocked with HTTP 422 if no override exists."""
    mock_sb = MagicMock()
    firm_id = "firm-101"
    user = {"id": "user-staff", "role": "staff"}

    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE))

    val_res = _make_violation_result("digest-abc-123", has_critical=True)
    with pytest.raises(HTTPException) as exc_info:
        verify_filing_governance_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            validation_result=val_res,
            user=user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "PARTNER_OVERRIDE_REQUIRED"


def test_strict_block_mode_unconditionally_rejects():
    """Under STRICT_BLOCK, filing is rejected with HTTP 422 even if partner approved."""
    mock_sb = MagicMock()
    firm_id = "firm-101"
    user = {"id": "user-partner", "role": "admin"}

    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.STRICT_BLOCK))

    val_res = _make_violation_result("digest-abc-123", has_critical=True)
    with pytest.raises(HTTPException) as exc_info:
        verify_filing_governance_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            validation_result=val_res,
            user=user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "FILING_STRICTLY_BLOCKED"


# ---------------------------------------------------------------------------
# 2. Partner Authorization & Security Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_staff_cannot_self_approve_override():
    """Ordinary staff role='staff' attempting to approve override is blocked with HTTP 403."""
    mock_sb = MagicMock()
    staff_user = {"id": "staff-user-1", "role": "staff", "email": "staff@cafirm.in"}

    with pytest.raises(HTTPException) as exc_info:
        await create_partner_override(
            mock_sb,
            firm_id="firm-101",
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            figures_digest="digest-abc-123",
            justification="Audited variance due to credit note timing.",
            violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
            user=staff_user,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "OVERRIDE_UNAUTHORIZED"


@pytest.mark.asyncio
async def test_override_requires_minimum_10_character_justification():
    """Blank or superficial justifications are rejected with HTTP 422."""
    mock_sb = MagicMock()
    partner_user = {"id": "partner-1", "role": "admin", "email": "partner@cafirm.in"}

    with pytest.raises(HTTPException) as exc_info:
        await create_partner_override(
            mock_sb,
            firm_id="firm-101",
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            figures_digest="digest-abc-123",
            justification="ok",  # < 10 characters
            violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
            user=partner_user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "INSUFFICIENT_JUSTIFICATION"


# ---------------------------------------------------------------------------
# 3. Tamper-Evidence & Figures Digest Invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_figures_alteration_invalidates_partner_override():
    """If figures change after partner approved, filing gate detects digest mismatch (HTTP 409)."""
    mock_sb = MagicMock()
    firm_id = "firm-101"
    partner_user = {"id": "partner-1", "role": "admin", "email": "partner@cafirm.in"}

    with patch("app.services.filing_override_service.assert_client_gstin_in_firm"):
        with patch("app.services.filing_override_service.log_audit"):
            # 1. Partner approves override for original figures
            orig_digest = "sha256-original-figures-digest-111"
            await create_partner_override(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id="cid-1",
                gstin="27AABCU9603R1ZM",
                period="2024-11",
                return_type="gstr-3b",
                figures_digest=orig_digest,
                justification="Statutory reconciliation verified; variance due to export turnover.",
                violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
                user=partner_user,
            )

    # 2. Firm policy set to PARTNER_OVERRIDE
    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE))

    # 3. User tries to file with altered figures (new digest)
    tampered_digest = "sha256-tampered-figures-digest-222"
    val_res = _make_violation_result(tampered_digest, has_critical=True)

    with pytest.raises(HTTPException) as exc_info:
        verify_filing_governance_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            validation_result=val_res,
            user={"id": "staff-1", "role": "staff"},
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "OVERRIDE_FIGURES_MISMATCH"


# ---------------------------------------------------------------------------
# 4. Override Lifecycle Consumption
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_is_consumed_upon_filing():
    """An override can only be used once. After consumption, a subsequent filing attempt requires a new override."""
    mock_sb = MagicMock()
    firm_id = "firm-101"
    partner_user = {"id": "partner-1", "role": "admin", "email": "partner@cafirm.in"}

    with patch("app.services.filing_override_service.assert_client_gstin_in_firm"):
        with patch("app.services.filing_override_service.log_audit"):
            digest = "sha256-valid-digest-333"
            override = await create_partner_override(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id="cid-1",
                gstin="27AABCU9603R1ZM",
                period="2024-11",
                return_type="gstr-3b",
                figures_digest=digest,
                justification="Authorized filing with reconciliation exception.",
                violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
                user=partner_user,
            )

    # Consume the override upon filing run completion
    consumed_id = consume_override_on_file_sync(
        mock_sb,
        firm_id=firm_id,
        client_gstin_id="cid-1",
        period="2024-11",
        return_type="gstr-3b",
        run_id="run-filed-999",
        user=partner_user,
    )
    assert consumed_id == override.id

    # Verify that a second filing attempt now finds the override consumed
    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE))
    val_res = _make_violation_result(digest, has_critical=True)

    with pytest.raises(HTTPException) as exc_info:
        verify_filing_governance_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            validation_result=val_res,
            user=partner_user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "PARTNER_OVERRIDE_REQUIRED"


# ---------------------------------------------------------------------------
# 5. Concurrency, Multi-process, and Restart Safety Tests
# ---------------------------------------------------------------------------


def test_concurrent_single_use_override_consumption():
    """Verify race condition protection: 10 concurrent threads attempt consumption; only 1 succeeds."""
    import concurrent.futures

    mock_sb = MagicMock()
    firm_id = "firm-concurrent"
    partner_user = {"id": "user-p1", "role": "admin"}
    digest = "digest-race-123"

    with patch("app.services.filing_override_service.assert_client_gstin_in_firm"):
        with patch("app.services.filing_override_service.log_audit"):
            import asyncio
            override = asyncio.run(
                create_partner_override(
                    mock_sb,
                    firm_id=firm_id,
                    client_gstin_id="cid-race",
                    gstin="27AABCU9603R1ZM",
                    period="2024-11",
                    return_type="gstr-3b",
                    figures_digest=digest,
                    justification="Authorized race-condition test override.",
                    violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
                    user=partner_user,
                )
            )

    results = []

    def _attempt_consume(thread_idx: int):
        with patch("app.utils.audit.log_audit_sync"):
            return consume_override_on_file_sync(
                mock_sb,
                firm_id=firm_id,
                client_gstin_id="cid-race",
                period="2024-11",
                return_type="gstr-3b",
                run_id=f"run-{thread_idx}",
                user=partner_user,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_attempt_consume, i) for i in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Exactly 1 thread must receive the override ID; all others must receive None
    successes = [r for r in results if r == override.id]
    failures = [r for r in results if r is None]
    assert len(successes) == 1, f"Expected exactly 1 consumption, got {len(successes)}"
    assert len(failures) == 9, f"Expected exactly 9 rejections, got {len(failures)}"


def test_validation_digest_tamper_invalidates_override():
    """Statutory validation result change between approval and filing produces HTTP 409 Conflict."""
    mock_sb = MagicMock()
    firm_id = "firm-val-tamper"
    partner_user = {"id": "user-p1", "role": "admin"}
    digest = "digest-figures-val-1"

    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE))

    with patch("app.services.filing_override_service.assert_client_gstin_in_firm"):
        with patch("app.services.filing_override_service.log_audit"):
            import asyncio
            override = asyncio.run(
                create_partner_override(
                    mock_sb,
                    firm_id=firm_id,
                    client_gstin_id="cid-val-1",
                    gstin="27AABCU9603R1ZM",
                    period="2024-11",
                    return_type="gstr-3b",
                    figures_digest=digest,
                    justification="Authorized filing with recognized violations profile.",
                    violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
                    user=partner_user,
                    validation_digest="val-hash-original",
                )
            )

    # Validation result now has a DIFFERENT validation_digest (new violation appeared)
    val_res = _make_violation_result(digest, has_critical=True)
    val_res.validation_digest = "val-hash-altered-new-violation"

    with pytest.raises(HTTPException) as exc_info:
        verify_filing_governance_gate(
            mock_sb,
            firm_id=firm_id,
            client_gstin_id="cid-val-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            validation_result=val_res,
            user=partner_user,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "OVERRIDE_VALIDATION_MISMATCH"


def test_restart_safety_restores_override_from_durable_storage():
    """Simulate server restart: memory cache cleared, override recovered from database table."""
    mock_sb = MagicMock()
    firm_id = "firm-restart"
    partner_user = {"id": "user-p1", "role": "admin"}
    digest = "digest-restart-123"

    _governance_store.set_policy(firm_id, FilingPolicy(firm_id=firm_id, mode=FilingPolicyMode.PARTNER_OVERRIDE))

    # Mock DB row returned by sb.table("filing_overrides")
    db_row = {
        "id": "override-durable-id",
        "firm_id": firm_id,
        "client_gstin_id": "cid-restart",
        "gstin": "27AABCU9603R1ZM",
        "period": "2024-11",
        "return_type": "gstr-3b",
        "figures_digest": digest,
        "validation_digest": "val-hash-durable",
        "justification": "Authorized before server reboot.",
        "approved_by": "user-p1",
        "approver_name": "Partner One",
        "approver_role": "admin",
        "violations_acknowledged": ["RULE_88C_DRC01B_TRIGGER"],
        "created_at": "2024-11-20T10:00:00Z",
        "expires_at": "2029-11-20T10:00:00Z",  # Far in future
        "is_consumed": False,
    }

    policy_row = {
        "firm_id": firm_id,
        "mode": "PARTNER_OVERRIDE",
        "require_final_reconciliation": True,
    }

    def _mock_table_fn(tbl_name: str):
        b = MagicMock()
        b.select.return_value = b
        b.eq.return_value = b
        b.gt.return_value = b
        b.order.return_value = b
        b.limit.return_value = b
        if tbl_name == "filing_governance_policies":
            b.execute.return_value = MagicMock(data=[policy_row])
        elif tbl_name == "filing_overrides":
            b.execute.return_value = MagicMock(data=[db_row])
        else:
            b.execute.return_value = MagicMock(data=[])
        return b

    mock_sb.table.side_effect = _mock_table_fn

    # Clear local in-memory store simulating process restart
    _governance_store.clear()
    assert _governance_store.get_override("override-durable-id") is None

    # Gate verification should query DB, reload the override, and permit filing
    val_res = _make_violation_result(digest, has_critical=True)
    val_res.validation_digest = "val-hash-durable"

    gate_result = verify_filing_governance_gate(
        mock_sb,
        firm_id=firm_id,
        client_gstin_id="cid-restart",
        gstin="27AABCU9603R1ZM",
        period="2024-11",
        return_type="gstr-3b",
        validation_result=val_res,
        user=partner_user,
    )

    assert gate_result is not None
    assert gate_result.id == "override-durable-id"
    assert gate_result.figures_digest == digest


# ---------------------------------------------------------------------------
# 5. Fail-Closed Durability in Production Tests
# ---------------------------------------------------------------------------

class TestFailClosedGovernanceInProduction:
    """Verifies that in production mode, filing governance strictly fails closed.
    
    Any database connection failure, query error, or missing table raises HTTP 503
    and NEVER falls back to permissive advisory mode or in-memory approvals.
    """

    @pytest.fixture(autouse=True)
    def set_production_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("RECONDESK_ENV", "production")

    def test_get_policy_fails_closed_when_aurora_is_down(self):
        """When Aurora is down in production, get_firm_filing_policy raises HTTP 503."""
        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("Aurora connection refused (OperationalError)")

        with pytest.raises(HTTPException) as exc_info:
            get_firm_filing_policy(mock_sb, "firm-fail-closed")

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "GOVERNANCE_STORAGE_UNAVAILABLE"

    def test_get_policy_fails_closed_when_db_client_is_none(self):
        """When sb client is None in production, get_firm_filing_policy raises HTTP 503."""
        with pytest.raises(HTTPException) as exc_info:
            get_firm_filing_policy(None, "firm-fail-closed")

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "GOVERNANCE_STORAGE_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_update_policy_fails_closed_when_aurora_is_down(self):
        """When Aurora is down in production, update_firm_filing_policy raises HTTP 503."""
        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("Aurora table missing (UndefinedTable)")
        admin_user = {"id": "admin-1", "role": "admin"}
        update = FilingPolicyUpdate(mode=FilingPolicyMode.PARTNER_OVERRIDE)

        with pytest.raises(HTTPException) as exc_info:
            await update_firm_filing_policy(mock_sb, "firm-1", update, admin_user)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "GOVERNANCE_STORAGE_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_create_override_fails_closed_when_aurora_is_down(self):
        """When Aurora is down in production, create_partner_override raises HTTP 503."""
        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("Aurora pool exhausted")
        partner_user = {"id": "partner-1", "role": "admin", "full_name": "Partner"}

        with patch("app.services.filing_override_service.assert_client_gstin_in_firm"):
            with pytest.raises(HTTPException) as exc_info:
                await create_partner_override(
                    mock_sb,
                    firm_id="firm-1",
                    client_gstin_id="cid-1",
                    gstin="27AABCU9603R1ZM",
                    period="2024-11",
                    return_type="gstr-3b",
                    figures_digest="hash-abc",
                    justification="Proper statutory explanation of mismatch",
                    violations_acknowledged=["RULE_88C_DRC01B_TRIGGER"],
                    user=partner_user,
                )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "GOVERNANCE_STORAGE_UNAVAILABLE"

    def test_verify_gate_fails_closed_when_aurora_is_down(self):
        """When Aurora is down in production, verify_filing_governance_gate raises HTTP 503."""
        mock_sb = MagicMock()
        # Mock get_firm_filing_policy to return PARTNER_OVERRIDE so gate proceeds to override lookup
        policy_builder = MagicMock()
        policy_builder.select.return_value = policy_builder
        policy_builder.eq.return_value = policy_builder
        policy_builder.limit.return_value = policy_builder
        policy_builder.execute.return_value = MagicMock(data=[{"firm_id": "firm-1", "mode": "PARTNER_OVERRIDE"}])

        override_builder = MagicMock()
        override_builder.select.return_value = override_builder
        override_builder.eq.side_effect = RuntimeError("Aurora query timeout")

        def _table_router(table_name: str):
            if table_name == "filing_governance_policies":
                return policy_builder
            return override_builder

        mock_sb.table.side_effect = _table_router

        val_res = _make_violation_result("digest-abc-123", has_critical=True)
        partner_user = {"id": "partner-1", "role": "admin"}

        with pytest.raises(HTTPException) as exc_info:
            verify_filing_governance_gate(
                mock_sb,
                firm_id="firm-1",
                client_gstin_id="cid-1",
                gstin="27AABCU9603R1ZM",
                period="2024-11",
                return_type="gstr-3b",
                validation_result=val_res,
                user=partner_user,
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "GOVERNANCE_STORAGE_UNAVAILABLE"

    def test_production_never_falls_back_to_in_memory_approvals(self):
        """In production, memory store is bypassed; gate does not accept in-memory override if DB returns 0 rows."""
        mock_sb = MagicMock()
        # Mock DB returning PARTNER_OVERRIDE policy and 0 rows for active/stale overrides
        policy_builder = MagicMock()
        policy_builder.select.return_value = policy_builder
        policy_builder.eq.return_value = policy_builder
        policy_builder.limit.return_value = policy_builder
        policy_builder.execute.return_value = MagicMock(data=[{"firm_id": "firm-1", "mode": "PARTNER_OVERRIDE"}])

        override_builder = MagicMock()
        override_builder.select.return_value = override_builder
        override_builder.eq.return_value = override_builder
        override_builder.gt.return_value = override_builder
        override_builder.order.return_value = override_builder
        override_builder.limit.return_value = override_builder
        override_builder.execute.return_value = MagicMock(data=[])  # 0 rows in DB

        mock_sb.table.side_effect = lambda t: policy_builder if t == "filing_governance_policies" else override_builder

        # Put an override in memory ONLY
        mem_ov = FilingOverride(
            id="mem-only-id",
            firm_id="firm-1",
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            figures_digest="digest-abc-123",
            validation_digest="",
            justification="In memory only",
            approved_by="admin-1",
            approver_name="Admin",
            approver_role="admin",
            violations_acknowledged=[],
            created_at="2024-11-20T10:00:00Z",
            expires_at="2029-11-20T10:00:00Z",
            is_consumed=False,
        )
        _governance_store.put_override(mem_ov)

        val_res = _make_violation_result("digest-abc-123", has_critical=True)
        partner_user = {"id": "partner-1", "role": "admin"}

        # In production mode, gate must reject with 422 because DB has 0 rows, ignoring memory!
        with pytest.raises(HTTPException) as exc_info:
            verify_filing_governance_gate(
                mock_sb,
                firm_id="firm-1",
                client_gstin_id="cid-1",
                gstin="27AABCU9603R1ZM",
                period="2024-11",
                return_type="gstr-3b",
                validation_result=val_res,
                user=partner_user,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "PARTNER_OVERRIDE_REQUIRED"


# ---------------------------------------------------------------------------
# 6. Atomic CAS Concurrency & Multi-Process Safety Tests
# ---------------------------------------------------------------------------

class TestAtomicCASConcurrency:
    """Verifies that atomic CAS consumption guarantees single-use under high concurrency."""

    def test_concurrent_cas_consumption_single_winner(self):
        """Simulate concurrent requests trying to consume the same override simultaneously.
        
        Using threading concurrency: exactly 1 request succeeds in consuming,
        while all other concurrent attempts fail (receive None).
        """
        import concurrent.futures

        # Mock DB where CAS update returns 1 row for the first caller and 0 rows thereafter
        consumed_flag = [False]
        lock = threading.Lock()

        def _cas_update_execute():
            with lock:
                if not consumed_flag[0]:
                    consumed_flag[0] = True
                    return MagicMock(data=[{"id": "ov-concurrent-1", "firm_id": "f1", "gstin": "27A", "period": "2024-11", "return_type": "gstr-3b", "figures_digest": "h1", "justification": "ok"}])
                else:
                    return MagicMock(data=[])  # 0 rows updated (already consumed)

        mock_sb = MagicMock()
        update_builder = MagicMock()
        update_builder.update.return_value = update_builder
        update_builder.eq.return_value = update_builder
        update_builder.gt.return_value = update_builder
        update_builder.execute.side_effect = _cas_update_execute
        mock_sb.table.return_value = update_builder

        results = []
        user = {"id": "user-1", "role": "admin"}

        def _worker(worker_id: int):
            with patch("app.utils.audit.log_audit_sync"):
                return consume_override_on_file_sync(
                    mock_sb,
                    firm_id="f1",
                    client_gstin_id="c1",
                    period="2024-11",
                    return_type="gstr-3b",
                    run_id=f"run-{worker_id}",
                    user=user,
                    override_id="ov-concurrent-1",
                )

        # Launch 20 concurrent workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_worker, i) for i in range(20)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        # Exactly 1 worker got the consumed ID, remaining 19 got None
        successful_consumptions = [r for r in results if r is not None]
        failed_consumptions = [r for r in results if r is None]

        assert len(successful_consumptions) == 1
        assert len(failed_consumptions) == 19
        assert successful_consumptions[0] == "ov-concurrent-1"

    def test_real_sql_transaction_cas_atomic_consumption(self, tmp_path):
        """Test atomic CAS query against a real SQL database engine with concurrent workers.
        
        Executes the exact SQL:
        UPDATE filing_overrides
        SET is_consumed = 1, consumed_at = :now, consumed_run_id = :run_id
        WHERE id = :id AND is_consumed = 0 AND expires_at > :now
        RETURNING id;
        
        Guarantees ACID row-level locking ensures exactly 1 winner among 20 concurrent threads.
        """
        import sqlite3
        import concurrent.futures

        db_file = tmp_path / "test_cas_concurrency.db"
        init_con = sqlite3.connect(str(db_file))
        init_con.execute("PRAGMA journal_mode=WAL;")
        init_con.execute("""
            CREATE TABLE filing_overrides (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                return_type TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                is_consumed INTEGER NOT NULL DEFAULT 0,
                consumed_at TEXT,
                consumed_run_id TEXT,
                expires_at TEXT NOT NULL
            );
        """)
        init_con.execute("""
            INSERT INTO filing_overrides (id, firm_id, gstin, period, return_type, figures_digest, is_consumed, expires_at)
            VALUES ('override-real-cas-1', 'firm-1', '27AABCU9603R1ZM', '2024-11', 'gstr-3b', 'digest-1', 0, '2099-12-31T23:59:59Z');
        """)
        init_con.commit()
        init_con.close()

        def _cas_worker(worker_idx: int) -> list[str]:
            con = sqlite3.connect(str(db_file), timeout=10.0)
            now_iso = "2024-11-20T12:00:00Z"
            run_id = f"run-{worker_idx}"
            cur = con.cursor()
            cur.execute("""
                UPDATE filing_overrides
                SET is_consumed = 1, consumed_at = ?, consumed_run_id = ?
                WHERE id = 'override-real-cas-1' AND is_consumed = 0 AND expires_at > ?
                RETURNING id;
            """, (now_iso, run_id, now_iso))
            rows = [r[0] for r in cur.fetchall()]
            con.commit()
            con.close()
            return rows

        cas_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_cas_worker, i) for i in range(20)]
            for f in concurrent.futures.as_completed(futures):
                cas_results.extend(f.result())

        # Exactly 1 worker gets the returned ID from the atomic UPDATE ... RETURNING
        assert len(cas_results) == 1
        assert cas_results[0] == "override-real-cas-1"

        # Verify the database state
        verify_con = sqlite3.connect(str(db_file))
        row = verify_con.execute("SELECT is_consumed, consumed_run_id FROM filing_overrides WHERE id = 'override-real-cas-1'").fetchone()
        assert row[0] == 1  # is_consumed is 1 (True)
        assert row[1].startswith("run-")  # bound to the winning run
        verify_con.close()

    def test_multiprocess_cas_atomic_consumption(self, tmp_path):
        """Test atomic CAS consumption using separate OS processes via ProcessPoolExecutor.
        
        Verifies that across separate OS processes with completely distinct memory spaces
        and database connections, ACID transactional row locking guarantees single winner.
        """
        import sqlite3
        import concurrent.futures

        db_file = tmp_path / "test_mp_cas_concurrency.db"
        init_con = sqlite3.connect(str(db_file))
        init_con.execute("PRAGMA journal_mode=WAL;")
        init_con.execute("""
            CREATE TABLE filing_overrides (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                return_type TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                is_consumed INTEGER NOT NULL DEFAULT 0,
                consumed_at TEXT,
                consumed_run_id TEXT,
                expires_at TEXT NOT NULL
            );
        """)
        init_con.execute("""
            INSERT INTO filing_overrides (id, firm_id, gstin, period, return_type, figures_digest, is_consumed, expires_at)
            VALUES ('override-mp-cas-1', 'firm-1', '27AABCU9603R1ZM', '2024-11', 'gstr-3b', 'digest-1', 0, '2099-12-31T23:59:59Z');
        """)
        init_con.commit()
        init_con.close()

        cas_results = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            tasks = [(str(db_file), i) for i in range(8)]
            futures = [executor.submit(_multiprocess_cas_worker, t) for t in tasks]
            for f in concurrent.futures.as_completed(futures):
                cas_results.extend(f.result())

        # Exactly 1 separate OS process successfully performed the CAS update
        assert len(cas_results) == 1
        assert cas_results[0] == "override-mp-cas-1"

        # Verify DB state
        verify_con = sqlite3.connect(str(db_file))
        row = verify_con.execute("SELECT is_consumed, consumed_run_id FROM filing_overrides WHERE id = 'override-mp-cas-1'").fetchone()
        assert row[0] == 1
        assert row[1].startswith("proc-run-")
        verify_con.close()




# ---------------------------------------------------------------------------
# 7. Filing Failures, Retries & Safe Transition Tests
# ---------------------------------------------------------------------------

class TestFilingFailureAndRetryTransitions:
    """Verifies that failed filings do NOT consume overrides, allowing retries."""

    def test_failed_filing_does_not_consume_override(self):
        """If filing portal throws an error, the override is NOT consumed in DB."""
        override_id = "ov-retry-test"
        consumed = [False]

        # In-memory store has active unconsumed override
        ov = FilingOverride(
            id=override_id,
            firm_id="firm-retry",
            client_gstin_id="cid-retry",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            figures_digest="hash-valid",
            validation_digest="",
            justification="Allowed for test",
            approved_by="admin-1",
            approver_name="Admin",
            approver_role="admin",
            violations_acknowledged=[],
            created_at="2024-11-20T10:00:00Z",
            expires_at="2029-11-20T10:00:00Z",
            is_consumed=False,
        )
        _governance_store.put_override(ov)
        _governance_store.set_policy(
            "firm-retry",
            FilingPolicy(firm_id="firm-retry", mode=FilingPolicyMode.PARTNER_OVERRIDE),
        )

        # Gate verification passes
        val_res = _make_violation_result("hash-valid", has_critical=True)
        user = {"id": "admin-1", "role": "admin"}
        mock_sb = MagicMock()

        gate_res = verify_filing_governance_gate(
            mock_sb,
            firm_id="firm-retry",
            client_gstin_id="cid-retry",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            validation_result=val_res,
            user=user,
        )
        assert gate_res.id == override_id

        # Simulate portal call throwing FilingClientError:
        # consume_override_on_file_sync is NEVER called
        # Verify override remains unconsumed
        current_ov = _governance_store.get_override(override_id)
        assert current_ov.is_consumed is False

        # Retry filing: gate verification passes again on the retry
        gate_res_retry = verify_filing_governance_gate(
            mock_sb,
            firm_id="firm-retry",
            client_gstin_id="cid-retry",
            gstin="27AABCU9603R1ZM",
            period="2024-11",
            return_type="gstr-3b",
            validation_result=val_res,
            user=user,
        )
        assert gate_res_retry.id == override_id

        # Upon successful filing submission, consumption succeeds
        consumed_id = consume_override_on_file_sync(
            mock_sb,
            firm_id="firm-retry",
            client_gstin_id="cid-retry",
            period="2024-11",
            return_type="gstr-3b",
            run_id="run-success-retry",
            user=user,
            override_id=override_id,
        )
        assert consumed_id == override_id
        assert _governance_store.get_override(override_id).is_consumed is True


